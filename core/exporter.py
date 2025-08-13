from __future__ import annotations
import pandas as pd
from datetime import time
from typing import List, Dict
from jinja2 import Template

DEFAULT_COLUMNS = ["School","Date","Start Time","End Time","Title","Notes"]

def format_time(t: time) -> str:
    return t.strftime("%I:%M %p").lstrip("0")

def export_facilitron(sessions: List[Dict], columns: list[str] = None, title_tpl: str = None, notes_tpl: str = None) -> pd.DataFrame:
    columns = columns or DEFAULT_COLUMNS
    title_tpl = title_tpl or "After-School Program — {{school}}"
    notes_tpl = notes_tpl or "Dismissal: {{dismissal}}"

    T = Template(title_tpl)
    N = Template(notes_tpl)

    rows = []
    total = len(sessions)
    for i, s in enumerate(sessions, start=1):
        row = {
            "School": s["school"],
            "Date": s["date"].strftime("%m/%d/%Y"),
            "Start Time": format_time(s["start_time"]),
            "End Time": format_time(s["end_time"]),
            "Title": T.render(school=s["school"], dismissal=s["dismissal"], session_index=i, total_sessions=total),
            "Notes": N.render(school=s["school"], dismissal=s["dismissal"], session_index=i, total_sessions=total),
        }
        row = {c: row.get(c, "") for c in columns}
        rows.append(row)
    return pd.DataFrame(rows)
