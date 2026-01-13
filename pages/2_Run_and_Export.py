# pages/2_Run_and_Export.py
from __future__ import annotations

import os
from io import BytesIO
import json
from datetime import date
from typing import Set

import streamlit as st
import pandas as pd

# Core app pieces
from core.crawler import crawl_school, fetch_html, CRAWLER_VERSION
from core.parsers_bell import parse_dismissal_time_from_html
from core.parsers_calendar import (
    fetch_text,
    parse_html_no_school_candidates,
    parse_ics_dates,
    classify_no_school_ai,
)
from core.scheduler import ScheduleParams, compute_weekly_sessions
from core.exporter import export_facilitron

# PDF (reportlab)
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

import tomllib
from dotenv import load_dotenv

# -------------------------------
# Setup
# -------------------------------
load_dotenv()
st.set_page_config(page_title="After-School Planner — Run", page_icon="🏁", layout="wide")
st.title("Run & Export")
st.caption(
    f"AI key loaded: **{bool(os.getenv('OPENAI_API_KEY'))}** · "
    f"Headless available: **True** · "
    f"Crawler version: **{CRAWLER_VERSION}**"
)

with open("config.toml", "rb") as f:
    cfg = tomllib.load(f)

def _blank_to_none(x: str | None):
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() in {"none", "null", "nan"}:
        return None
    return s

def _looks_like_ics(s: str | None) -> bool:
    if not s:
        return False
    ss = s.strip().lower()
    return ss.endswith(".ics") or ss.endswith(".ical")

def _norm_webcal(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip()
    if u.lower().startswith("webcal://"):
        return "https://" + u[len("webcal://"):]
    return u

def _get_district_ics_map() -> dict[str, str]:
    return st.session_state.get("district_ics_map", {}) or {}

# Cache parsed ICS dates per district ICS so we only fetch/parse once
if "_district_ics_cache" not in st.session_state:
    st.session_state["_district_ics_cache"] = {}

def _get_district_no_school(ics_url: str) -> Set[date]:
    cache = st.session_state["_district_ics_cache"]
    if not ics_url:
        return set()
    ics_url = _norm_webcal(ics_url)
    if ics_url in cache:
        return cache[ics_url]
    dates = parse_ics_dates(ics_url)
    cache[ics_url] = dates
    return dates

# -------------------------------
# Required inputs from page 1
# -------------------------------
if "input_df" not in st.session_state:
    st.warning("Upload CSV in **Settings & Input** first.")
    st.stop()

input_df = st.session_state["input_df"].copy()
params = ScheduleParams(
    buffer_minutes=st.session_state["buffer_minutes"],
    session_duration_minutes=st.session_state["session_duration_minutes"],
    earliest_start=st.session_state["earliest_start"],
    latest_end=st.session_state["latest_end"],
    target_sessions=st.session_state["target_sessions"],
    min_sessions=st.session_state["min_sessions"],
)

q_start = st.session_state["q_start"]
q_end = st.session_state["q_end"]

use_openai = st.session_state["use_openai"]
ai_assist_bell = st.session_state["ai_assist_bell"]
ai_assist_calendar = st.session_state["ai_assist_calendar"]
use_headless_fallback = st.session_state["use_headless_fallback"]
max_anchors = st.session_state["max_anchors"]
delay_sec = st.session_state["delay_between_schools_seconds"]

district_ics_map = _get_district_ics_map()  # {"Fremont Unified": "https://...basic.ics", ...}

# Debug toggles (optional)
col_dbg1, col_dbg2 = st.columns([1, 1])
with col_dbg1:
    show_debug = st.toggle("Show per-school debug", value=False)
with col_dbg2:
    show_candidates = st.toggle("Also show top anchor candidates", value=False)

# -------------------------------
# Crawl + plan
# -------------------------------
progress = st.progress(0)
all_sessions: list[dict] = []
results_rows: list[dict] = []

df = input_df.reset_index(drop=True)
for i, row in df.iterrows():
    pct = int(((i + 1) / max(1, len(df))) * 100)
    progress.progress(pct)

    school = _blank_to_none(row.get("school_name"))
    url = _blank_to_none(row.get("school_url"))
    weekday = _blank_to_none(row.get("weekday"))

    bell_override = _blank_to_none(row.get("bell_schedule_page_url"))
    cal_override = _blank_to_none(row.get("school_calendar_page_url"))
    district = _blank_to_none(row.get("district"))
    district_ics_url = _norm_webcal(_blank_to_none(row.get("district_ics_url")))

    bell_url = bell_override
    cal_url = cal_override
    ics_url = None

    # Treat a school_calendar_page_url ending with .ics as an ICS override
    if cal_override and _looks_like_ics(cal_override):
        ics_url = cal_override
        cal_url = None

    # Crawl if needed
    crawl_obj = None
    if not bell_url or not cal_url:
        crawl_obj = crawl_school(
            url,
            use_openai=use_openai,
            max_anchors=max_anchors,
            delay=delay_sec,
            use_headless_fallback=use_headless_fallback,
        )
        bell_url = bell_url or getattr(crawl_obj, "bell_url", None)
        cal_url = cal_url or getattr(crawl_obj, "cal_url", None)
        ics_url = ics_url or getattr(crawl_obj, "ics_url", None)

    # Dismissal time
    dismissal_str = None
    if bell_url:
        bell_html = fetch_html(bell_url)
        dismissal_str = parse_dismissal_time_from_html(
            bell_html or "", preferred_weekday=weekday, use_ai=ai_assist_bell
        )
    if not dismissal_str:
        dismissal_str = "3:00 pm"  # fallback

    # No-school dates (school ICS → district ICS → HTML)
    no_school: Set[date] = set()

    # 1) direct school ICS
    if ics_url:
        no_school |= parse_ics_dates(_norm_webcal(ics_url))

    # 2) district ICS (only fetch once per URL)
    if not no_school and district:
        candidate = district_ics_url or district_ics_map.get(district, "")
        if candidate:
            no_school |= _get_district_no_school(candidate)

    # 3) HTML fallback
    if not no_school and cal_url:
        cal_html = fetch_text(cal_url)
        if cal_html:
            candidates = parse_html_no_school_candidates(cal_html)
            if ai_assist_calendar:
                no_school |= classify_no_school_ai(candidates)
            else:
                from dateutil import parser as dtp
                for _, tok in candidates:
                    try:
                        no_school.add(dtp.parse(tok, fuzzy=True).date())
                    except Exception:
                        pass

    # Plan sessions
    sessions = compute_weekly_sessions(
        school=school,
        weekday_str=weekday,
        dismissal_time_str=dismissal_str,
        quarter_start=q_start,
        quarter_end=q_end,
        params=params,
        no_school_dates=no_school,
    )
    all_sessions.extend(sessions)

    # Assemble result row
    results_rows.append(
        {
            "school": school,
            "weekday": weekday,
            "bell_url": bell_url or "",
            "calendar_url": cal_url or "",
            "ics_url": _norm_webcal(ics_url) or "",
            "district": district or "",
            "district_ics_url": district_ics_url or district_ics_map.get(district or "", ""),
            "dismissal": dismissal_str,
            "sessions": len(sessions),
            "no_class_dates": "; ".join(
                sorted(
                    {
                        d.strftime("%m/%d/%Y")
                        for d in no_school
                        if q_start <= d <= q_end
                    }
                )
            ),
        }
    )

    # Optional debug
    if show_debug:
        school2ics = st.session_state.get("school2ics", {})
        dbg = {
            "input_url": row.get("school_url", ""),
            "weekday": weekday,
            "bell_url": bell_url,
            "calendar_url": cal_url,
            "ics_url": ics_url,
            "district": row.get("district", ""),
            "district_ics_url": row.get("district_ics_url", ""),
            "dismissal_guess": dismissal_str,
            "sessions_planned": params.target_sessions,
            "resolved_district_ics_url": school2ics.get(school, ""),
        }
        with st.expander(f"Debug — {school}"):
            st.code(json.dumps(dbg, indent=2), language="json")
            if show_candidates and crawl_obj is not None:
                if getattr(crawl_obj, "heuristic_dbg", None):
                    hd = crawl_obj.heuristic_dbg
                    if "bell_top" in hd:
                        st.write("Top bell candidates (homepage):")
                        st.code(json.dumps(hd["bell_top"], indent=2))
                    if "cal_top" in hd:
                        st.write("Top calendar candidates (homepage):")
                        st.code(json.dumps(hd["cal_top"], indent=2))

# -------------------------------
# DataFrames
# -------------------------------
st.subheader("Crawl & Parse Summary (sortable)")
summary_df = pd.DataFrame(results_rows)
st.dataframe(summary_df, use_container_width=True)

st.subheader("Planned Sessions Preview (sortable)")
preview_df = pd.DataFrame(
    [
        {
            **s,
            "date": s["date"].strftime("%Y-%m-%d"),
            "start_time": s["start_time"].strftime("%I:%M %p").lstrip("0"),
            "end_time": s["end_time"].strftime("%I:%M %p").lstrip("0"),
        }
        for s in all_sessions
    ]
)
st.dataframe(preview_df, use_container_width=True)

# -------------------------------
# Per-school Roll-up Summary
# -------------------------------
from collections import defaultdict

by_school = defaultdict(list)
for s in all_sessions:
    by_school[s["school"]].append(s)

rows = []
school2ics = st.session_state.get("school2ics", {})

for school, items in by_school.items():
    dates = sorted([x["date"] for x in items])
    start_time = items[0]["start_time"] if items else None
    end_time   = items[0]["end_time"]   if items else None

    # District no-school dates observed within the quarter range for this school
    ics_url = (school2ics.get(school) or "").strip()
    observed = []
    if ics_url and dates:
        q_s, q_e = dates[0], dates[-1]
        observed = sorted(
            d for d in _get_district_no_school(ics_url)
            if q_s <= d <= q_e
        )

    rows.append({
        "School": school,
        "Start Date": dates[0].strftime("%m/%d/%Y") if dates else "",
        "End Date":   dates[-1].strftime("%m/%d/%Y") if dates else "",
        "Start Time": start_time.strftime("%I:%M %p").lstrip('0') if start_time else "",
        "End Time":   end_time.strftime("%I:%M %p").lstrip('0') if end_time else "",
        "Target Sessions": params.target_sessions,
        "Scheduled Sessions": len(items),
        "Session Dates": "; ".join(d.strftime("%m/%d/%Y") for d in dates),
        "No-Class Dates (Observed)": "; ".join(d.strftime("%m/%d/%Y") for d in observed) if observed else "",
    })

out_df = pd.DataFrame(rows)

st.subheader("Summary (sortable)")
st.dataframe(out_df, use_container_width=True)

# -------------------------------
# Downloads
# -------------------------------
col1, col2, col3 = st.columns(3)

with col1:
    st.download_button(
        label="Download Summary CSV",
        data=out_df.to_csv(index=False).encode("utf-8"),
        file_name="after_school_summary.csv",
        mime="text/csv",
    )

with col2:
    export_cols = cfg["export"]["columns"]
    fac_df = export_facilitron(
        all_sessions,
        columns=export_cols,
        title_tpl=cfg["export"]["title_template"],
        notes_tpl=cfg["export"]["notes_template"],
    )
    st.download_button(
        label="Download Facilitron CSV",
        data=fac_df.to_csv(index=False).encode("utf-8"),
        file_name="facilitron_export.csv",
        mime="text/csv",
    )

with col3:
    def build_pdf(df: pd.DataFrame) -> bytes:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=24,
            leftMargin=24,
            topMargin=24,
            bottomMargin=24,
        )
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph("After-School Planner — Summary", styles["Title"]))
        story.append(Spacer(1, 12))
        data = [list(df.columns)] + df.values.tolist()
        table = Table(data, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ]
            )
        )
        story.append(table)
        doc.build(story)
        pdf = buffer.getvalue()
        buffer.close()
        return pdf

    pdf_bytes = build_pdf(out_df)
    st.download_button(
        label="Download Summary PDF",
        data=pdf_bytes,
        file_name="after_school_summary.pdf",
        mime="application/pdf",
    )
