from __future__ import annotations
import os, re
from bs4 import BeautifulSoup
from typing import Optional, List, Tuple

TIME_REGEX = re.compile(r"\b(1[0-2]|0?[1-9]):([0-5][0-9])\s*(am|pm)\b", re.I)
ALT_TIME_REGEX = re.compile(r"\b(1[0-2]|0?[1-9])\s*(am|pm)\b", re.I)
KEY_ROWS = ["dismissal","release","end of day","school ends","regular day","mon","tue","wed","thu","fri","minimum day","early release"]

def parse_candidate_times(html: str) -> List[Tuple[str,str]]:
    out = []
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all(["table"]):
        for tr in table.find_all("tr"):
            cells = [" ".join(td.get_text(" ", strip=True).split()).lower() for td in tr.find_all(["td","th"])]
            if not cells: continue
            row_text = " ".join(cells)
            if any(k in row_text for k in KEY_ROWS):
                m = TIME_REGEX.search(row_text) or ALT_TIME_REGEX.search(row_text)
                if m:
                    out.append((row_text, m.group(0)))
    for line in soup.get_text("\n", strip=True).lower().splitlines():
        if any(k in line for k in ["dismissal","release","end of day","school hours","minimum day"]):
            m = TIME_REGEX.search(line) or ALT_TIME_REGEX.search(line)
            if m:
                out.append((line, m.group(0)))
    return out

def choose_dismissal_ai(candidates: List[Tuple[str,str]], weekday: str) -> Optional[str]:
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or not candidates:
            return candidates[0][1] if candidates else None
        client = OpenAI(api_key=api_key)
        lines = [f"- {text} => {t}" for text,t in candidates[:15]]
        prompt = (
            "Given bell schedule lines and times, pick the NORMAL dismissal time for the specified weekday. "
            "Prefer Regular Day over Minimum/Early Release unless text says the weekday is a minimum day. "
            "Return only the time string (e.g., '3:05 pm').\n"
            f"Weekday: {weekday}\n" + "\n".join(lines)
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return candidates[0][1] if candidates else None

def parse_dismissal_time_from_html(html: str, preferred_weekday: str | None = None, use_ai: bool = False) -> Optional[str]:
    if not html:
        return None
    candidates = parse_candidate_times(html)
    if not candidates:
        return None
    if use_ai and preferred_weekday:
        chosen = choose_dismissal_ai(candidates, preferred_weekday)
        if chosen:
            return chosen
    for text, t in candidates:
        if "regular" in text or "dismissal" in text or "release" in text:
            return t
    return candidates[0][1]
