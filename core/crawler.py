from __future__ import annotations
import os, re, time, json, requests, asyncio
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

CRAWLER_VERSION = "0.5.1"


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AfterSchoolPlanner/0.5)"}
TIMEOUT = 20

# Broader hints
BELL_HINTS = [
    "bell schedule","bell schedules","daily schedule","dismissal","release time",
    "school hours","hours & schedule","hours and schedule","bell time","bell times",
]
CAL_HINTS  = [
    "calendar","academic calendar","school calendar","events","event calendar",
    "year","holidays","vacation","ics","ical","subscribe","add to calendar",
]

TIME_TOKENS = (" am"," pm",":")  # cheap time signal

class CrawlResult:
    def __init__(self, bell_url: str | None, cal_url: str | None, ics_url: str | None, debug: dict | None = None):
        self.bell_url = bell_url
        self.cal_url = cal_url
        self.ics_url = ics_url
        self.debug = debug or {}

def fetch_html(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.ok:
            return r.text
    except Exception:
        return None
    return None

def fetch_rendered_html(url: str, wait_ms: int = 1500) -> str | None:
    # Optional: requires playwright installed + browsers
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(url, timeout=TIMEOUT*1000)
            page.wait_for_timeout(wait_ms)
            html = page.content()
            browser.close()
            return html
    except Exception:
        return None

def extract_links(base_url: str, html: str) -> list[tuple[str, str]]:
    """(href, text_lower)"""
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        text = " ".join(a.get_text(" ", strip=True).split()).lower()
        links.append((href, text))
    # also check <link> tags (rel=alternate, type=text/calendar, etc.)
    for link in soup.find_all("link", href=True):
        href = urljoin(base_url, link["href"]).split("#")[0]
        text = " ".join((link.get("type") or "", " ".join(link.get("rel") or []))).lower()
        links.append((href, text))
    # de-dup
    seen = set(); uniq = []
    for h,t in links:
        if h in seen: continue
        seen.add(h); uniq.append((h,t))
    return uniq

def _same_domain(u1: str, u2: str) -> bool:
    return urlparse(u1).netloc == urlparse(u2).netloc

def _has_time_signal(text: str) -> bool:
    t = text.lower()
    return any(tok in t for tok in TIME_TOKENS)

def score_bell(text: str) -> int:
    t = text.lower()
    score = 0
    # direct phrase hits
    for h in BELL_HINTS:
        if h in t: score += 8
    # fuzzy: 'bell' + ('sched' OR 'time') OR time tokens
    if "bell" in t and ("sched" in t or "time" in t or "hours" in t):
        score += 6
    if "bell" in t and _has_time_signal(t):
        score += 4
    return score

def score_cal(text: str) -> int:
    t = text.lower()
    score = 0
    for h in CAL_HINTS:
        if h in t: score += 6
    if "calendar" in t and ("event" in t or "school" in t or "academic" in t):
        score += 4
    return score

def top_candidates(links, scorer, k=6):
    scored = [(h, t, scorer(t)) for (h,t) in links]
    scored = [x for x in scored if x[2] > 0]
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:k]

def pick_best_links(base_url: str, links: list[tuple[str,str]]) -> tuple[str|None, str|None, str|None, dict]:
    bell_cands = top_candidates(links, score_bell, 8)
    cal_cands  = top_candidates(links, score_cal, 8)
    bell_url = bell_cands[0][0] if bell_cands else None
    cal_url  = cal_cands[0][0]  if cal_cands else None
    ics_url  = next((h for h,t in links if h.lower().endswith((".ics",".ical")) or "text/calendar" in t or "ics" in t), None)
    dbg = {
        "bell_top": bell_cands,
        "cal_top": cal_cands,
        "ics_guess": ics_url,
    }
    return bell_url, cal_url, ics_url, dbg

def _two_hop_links(base_url: str, html: str, use_headless_fallback: bool, limit_children: int = 12) -> tuple[list[tuple[str,str]], dict]:
    """Homepage anchors + first hop into same-domain pages to collect more anchors."""
    debug = {}
    links0 = extract_links(base_url, html)
    debug["anchor_count_home"] = len(links0)

    # pick same-domain children to visit (prefer likely nav pages)
    children = [h for h,t in links0 if _same_domain(base_url, h)]
    children = children[:limit_children]

    expanded = links0[:]
    for child in children:
        html2 = fetch_html(child)
        # headless only if we got almost nothing
        if (not html2 or len(html2) < 600) and use_headless_fallback:
            html2 = fetch_rendered_html(child) or html2
        if html2:
            expanded.extend(extract_links(child, html2))

    # de-dup
    seen = set(); uniq = []
    for h,t in expanded:
        if h in seen: continue
        seen.add(h); uniq.append((h,t))

    debug["anchor_count_expanded"] = len(uniq)
    return uniq, debug

def pick_links_with_openai(base_url: str, links: list[tuple[str,str]], max_anchors: int = 150):
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("no api key")
        client = OpenAI(api_key=api_key)
        sample = links[:max_anchors]
        content = (
            "Pick the single best Bell Schedule page, the best Academic Calendar page, "
            "and any direct .ics link. Respond with STRICT JSON: "
            '{"bell_url": str|null, "cal_url": str|null, "ics_url": str|null}.\n'
            f"BASE: {base_url}\n"
            + "\n".join([f"- {h} => {t}" for h,t in sample])
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":content}],
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        i, j = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[i:j+1]) if i!=-1 and j!=-1 else {}
        return data.get("bell_url"), data.get("cal_url"), data.get("ics_url")
    except Exception:
        return None, None, None

def crawl_school(home_url: str, use_openai: bool = True, max_anchors: int = 150,
                 delay: float = 0.0, use_headless_fallback: bool = True) -> CrawlResult:
    debug = {"home_url": home_url}

    html = fetch_html(home_url)
    method = "html"
    if (not html or len(html) < 600) and use_headless_fallback:
        rendered = fetch_rendered_html(home_url)
        if rendered and len(rendered) > (len(html) if html else 0):
            html = rendered
            method = "headless"

    if not html:
        debug.update({"method":"none","html_len":0,"anchor_count":0,"reason":"fetch_failed"})
        return CrawlResult(None, None, None, debug)

    links, hop_dbg = _two_hop_links(home_url, html, use_headless_fallback, limit_children=12)
    debug.update({"method": method, "html_len": len(html), **hop_dbg})

    # Try OpenAI first (if available), then heuristics
    bell_url = cal_url = ics_url = None
    if use_openai:
        b, c, i = pick_links_with_openai(home_url, links, max_anchors=max_anchors)
        bell_url, cal_url, ics_url = b or None, c or None, i or None
        debug["used_openai"] = True

    if not bell_url or not cal_url or not ics_url:
        b2, c2, i2, dbg = pick_best_links(home_url, links)
        debug["heuristic_dbg"] = dbg
        bell_url = bell_url or b2
        cal_url  = cal_url  or c2
        ics_url  = ics_url  or i2

    if delay > 0:
        time.sleep(delay)

    return CrawlResult(bell_url, cal_url, ics_url, debug)
