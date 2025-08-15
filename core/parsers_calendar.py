from __future__ import annotations
import os, re, json
from bs4 import BeautifulSoup
from dateutil import parser as dtp
from datetime import date
from typing import Set, List, Tuple
import requests
from ics import Calendar

# add more names we see in K-12 calendars
NO_SCHOOL_TERMS = [
    "no school", "school closed", "schools closed", "holiday", "break",
    "professional development", "professional learning", "staff development",
    "inservice", "in-service", "teacher work day", "workday", "pupil free",
    "conference (no school)", "conference day", "parent-teacher conference",
    "minimum day", "early release"  # treat these as no class; toggle later if you want
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AfterSchoolPlanner/0.2)"}

def fetch_text(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.ok:
            return r.text
    except Exception:
        return None
    return None

# (keep your helper as-is)
def parse_ics_dates(ics_url: str) -> Set[date]:
    out: Set[date] = set()
    try:
        url = ics_url.strip()
        if url.lower().startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]  # normalize webcal -> https

        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        cal = Calendar(r.text)

        # explicit holiday names frequently used without "holiday"/"no school"
        HOLIDAY_NAMES = {
            "labor day", "veterans day", "thanksgiving", "thanksgiving break",
            "winter break", "winter recess", "spring break", "fall break",
            "mlk day", "martin luther king", "presidents day", "memorial day",
            "independence day", "new year", "christmas", "rosh hashanah",
            "yom kippur", "diwali", "easter monday", "good friday", "chinese new year"
        }

        for e in cal.events:
            title = (e.name or "").lower().strip()
            if any(term in title for term in NO_SCHOOL_TERMS) or any(h in title for h in HOLIDAY_NAMES):
                d0 = e.begin.date()
                d1 = e.end.date() if e.end else d0
                dd = d0
                while dd <= d1:
                    out.add(dd)
                    dd = dd.fromordinal(dd.toordinal() + 1)
    except Exception:
        pass
    return out

def parse_html_no_school_candidates(html: str) -> List[Tuple[str,str]]:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)
    lines = [l for l in text.splitlines() if any(term in l.lower() for term in NO_SCHOOL_TERMS)]
    out: List[Tuple[str,str]] = []
    for line in lines:
        for m in re.finditer(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:,\s*\d{4})?\b", line, flags=re.I):
            out.append((line, m.group(0)))
    return out

def classify_no_school_ai(candidates: List[Tuple[str,str]]) -> Set[date]:
    if not candidates:
        return set()
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {dtp.parse(tok, fuzzy=True).date() for _, tok in candidates}
        client = OpenAI(api_key=api_key)
        rows = [f"- {text} | {tok}" for text,tok in candidates[:50]]
        prompt = (
            "From these school calendar lines, pick entries that mean there is NO after-school class "
            "(e.g., No School, Holiday, Minimum Day with no after-school). "
            "Return JSON array of ISO dates (YYYY-MM-DD). Lines:\n" + "\n".join(rows)
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0
        )
        raw = resp.choices[0].message.content.strip()
        i,j = raw.find("["), raw.rfind("]")
        data = json.loads(raw[i:j+1]) if i!=-1 and j!=-1 else []
        return {dtp.parse(s).date() for s in data}
    except Exception:
        return {dtp.parse(tok, fuzzy=True).date() for _, tok in candidates}
