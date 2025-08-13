from __future__ import annotations
import os, re, time, json
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AfterSchoolPlanner/0.2)"}
BELL_HINTS = ["bell schedule","daily schedule","dismissal","release time","school hours"]
CAL_HINTS  = ["calendar","academic calendar","school calendar","events","ics","ical"]
TIMEOUT = 20

class CrawlResult:
    def __init__(self, bell_url: str | None, cal_url: str | None, ics_url: str | None):
        self.bell_url = bell_url
        self.cal_url = cal_url
        self.ics_url = ics_url

def fetch_html(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.ok:
            return r.text
    except Exception:
        return None
    return None

def fetch_rendered_html(url: str, wait_ms: int = 1500) -> str | None:
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

def extract_links(base_url: str, html: str) -> list[tuple[str,str]]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        text = " ".join(a.get_text(strip=True).split())[:240].lower()
        links.append((href, text))
    return links

def score_link(text: str, hints: list[str]) -> int:
    score = sum(10 for h in hints if h in text)
    if any(t in text for t in ["am","pm",":"]):
        score += 1
    return score

def pick_best_links(base_url: str, links: list[tuple[str,str]]):
    bell = sorted(links, key=lambda x: score_link(x[1], BELL_HINTS), reverse=True)
    cal  = sorted(links, key=lambda x: score_link(x[1], CAL_HINTS),  reverse=True)
    bell_url = bell[0][0] if bell and score_link(bell[0][1], BELL_HINTS) > 0 else None
    cal_url  = cal[0][0]  if cal and score_link(cal[0][1], CAL_HINTS)  > 0 else None
    ics_url  = next((h for h,t in links[:200] if h.lower().endswith((".ics",".ical")) or "ics" in t), None)
    return bell_url, cal_url, ics_url

def pick_links_with_openai(base_url: str, links: list[tuple[str,str]], max_anchors: int = 60):
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return pick_best_links(base_url, links)
        client = OpenAI(api_key=api_key)
        sample = links[:max_anchors]
        content = (
            "Pick the single best Bell Schedule link, Academic Calendar link, and any .ics link. "
            "Return strict JSON {\"bell_url\":str|null,\"cal_url\":str|null,\"ics_url\":str|null}.\n"
            f"BASE: {base_url}\n" + "\n".join([f"- {h} => {t}" for h,t in sample])
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":content}],
            temperature=0
        )
        raw = resp.choices[0].message.content
        i,j = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[i:j+1]) if i!=-1 and j!=-1 else {}
        return data.get("bell_url"), data.get("cal_url"), data.get("ics_url")
    except Exception:
        return pick_best_links(base_url, links)

def crawl_school(home_url: str, use_openai: bool = True, max_anchors: int = 60, delay: float = 0.0, use_headless_fallback: bool = True) -> CrawlResult:
    html = fetch_html(home_url)
    if (not html or len(html) < 500) and use_headless_fallback:
        rendered = fetch_rendered_html(home_url)
        html = rendered or html
    if not html:
        return CrawlResult(None, None, None)

    links = extract_links(home_url, html)
    if use_openai:
        bell_url, cal_url, ics_url = pick_links_with_openai(home_url, links, max_anchors=max_anchors)
    else:
        bell_url, cal_url, ics_url = pick_best_links(home_url, links)

    if delay>0:
        time.sleep(delay)
    return CrawlResult(bell_url, cal_url, ics_url)
