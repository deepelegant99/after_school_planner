import os, streamlit as st
import pandas as pd

# Crawler + helpers
from core.crawler import crawl_school, fetch_html, extract_links, CRAWLER_VERSION
try:
    from core.crawler import fetch_rendered_html as _fetch_rendered_html
except Exception:
    _fetch_rendered_html = None

# Parsers / scheduler / export
from core.parsers_bell import parse_dismissal_time_from_html
from core.parsers_calendar import (
    fetch_text, parse_html_no_school_candidates, parse_ics_dates, classify_no_school_ai
)
from core.scheduler import ScheduleParams, compute_weekly_sessions
from core.exporter import export_facilitron

import tomllib
from dotenv import load_dotenv
load_dotenv()

# ---------- Page header ----------
st.set_page_config(page_title="After-School Planner — Run", page_icon="🏁", layout="wide")
st.caption(
    f"AI key loaded: {bool(os.getenv('OPENAI_API_KEY'))} · "
    f"Headless available: {'True' if _fetch_rendered_html else 'False'} · "
    f"Crawler version: {CRAWLER_VERSION}"
)

# ---------- PDF helpers ----------
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

with open("config.toml","rb") as f:
    cfg = tomllib.load(f)

st.title("Run & Export")

if "input_df" not in st.session_state:
    st.warning("Upload CSV in **Settings & Input** first.")
    st.stop()

# Sidebar toggles
with st.sidebar:
    show_debug = st.toggle("Show per-school debug", value=True)
    show_top_anchors = st.toggle("Also show top anchor candidates", value=False)

# ---------- Params ----------
params = ScheduleParams(
    buffer_minutes=st.session_state["buffer_minutes"],
    session_duration_minutes=st.session_state["session_duration_minutes"],
    earliest_start=st.session_state["earliest_start"],
    latest_end=st.session_state["latest_end"],
    target_sessions=st.session_state["target_sessions"],
    min_sessions=st.session_state["min_sessions"],
)
q_start = st.session_state["q_start"]; q_end = st.session_state["q_end"]
use_openai = st.session_state["use_openai"]
ai_assist_bell = st.session_state["ai_assist_bell"]
ai_assist_calendar = st.session_state["ai_assist_calendar"]
use_headless_fallback = st.session_state["use_headless_fallback"]
max_anchors = st.session_state["max_anchors"]
delay_sec = st.session_state["delay_between_schools_seconds"]

input_df = st.session_state["input_df"].copy()

progress = st.progress(0)
all_sessions, results_rows = [], []

# --------- sanity helpers ---------
def _clean_optional(val: object) -> str | None:
    """
    Convert CSV cells like NaN/"nan"/"none"/"null"/"" into None.
    Otherwise return stripped string.
    """
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    if s.lower() in ("nan", "none", "null"):
        return None
    return s

# --------- local scoring for homepage fallback ---------
_BELL_HINTS = ["bell schedule","bell schedules","daily schedule","dismissal","release time",
               "school hours","hours & schedule","hours and schedule","bell time","bell times"]
_CAL_HINTS  = ["calendar","academic calendar","school calendar","events","event calendar",
               "year","holidays","vacation","ics","ical","subscribe","add to calendar"]

def _score(text: str, hints: list[str]) -> int:
    t = (text or "").lower()
    base = sum(1 for h in hints if h in t)
    if any(x in t for x in [" am"," pm",":"]):
        base += 1
    if "bell" in t and ("sched" in t or "time" in t or "hours" in t):
        base += 1
    return base

def _pick_from_homepage(url: str):
    html = fetch_html(url) or ""
    anchors = extract_links(url, html) if html else []
    bell = cal = None
    ics = next((h for h,t in anchors if (isinstance(h,str) and h.lower().endswith((".ics",".ical"))) or "text/calendar" in t), None)
    bell_candidates = sorted(anchors, key=lambda x: _score(x[1], _BELL_HINTS), reverse=True)
    cal_candidates  = sorted(anchors, key=lambda x: _score(x[1], _CAL_HINTS),  reverse=True)
    if bell_candidates and _score(bell_candidates[0][1], _BELL_HINTS) > 0:
        bell = bell_candidates[0][0]
    if cal_candidates and _score(cal_candidates[0][1], _CAL_HINTS) > 0:
        cal = cal_candidates[0][0]
    return bell, cal, ics, {
        "home_anchor_count_html": len(anchors),
        "home_bell_top": bell_candidates[:6],
        "home_cal_top": cal_candidates[:6],
    }

for idx, row in input_df.iterrows():
    progress.progress(int((idx+1)/len(input_df)*100))

    school  = _clean_optional(row.get("school_name")) or ""
    url     = _clean_optional(row.get("school_url")) or ""
    weekday = _clean_optional(row.get("Day of the week")) or ""

    # CLEAN these so we don't get the literal string "nan" blocking the crawl
    bell_override = _clean_optional(row.get("bell_schedule_page_url"))
    cal_override  = _clean_optional(row.get("school_calendar_page_url"))

    bell_url = bell_override
    cal_url  = cal_override
    ics_url  = None

    def _is_ics(u): return isinstance(u,str) and u.lower().endswith((".ics",".ical"))
    if cal_override and _is_ics(cal_override):
        ics_url = cal_override
        cal_url = None

    # 1) Try crawler (OpenAI + heuristics)
    crawl_debug = None
    if not bell_url or not cal_url:
        crawl = crawl_school(
            url,
            use_openai=use_openai,
            max_anchors=max_anchors,
            delay=delay_sec,
            use_headless_fallback=use_headless_fallback,
        )
        bell_url = bell_url or getattr(crawl, "bell_url", None)
        cal_url  = cal_url  or getattr(crawl, "cal_url",  None)
        ics_url  = ics_url  or getattr(crawl, "ics_url",  None)
        crawl_debug = getattr(crawl, "debug", None)

    # 2) Homepage fallback IF still missing
    homepage_dbg = {}
    if not bell_url or not cal_url or not ics_url:
        hb, hc, hi, homepage_dbg = _pick_from_homepage(url)
        bell_url = bell_url or hb
        cal_url  = cal_url  or hc
        ics_url  = ics_url  or hi

    # ---- per-school debug ----
    if show_debug:
        with st.expander(f"Debug — {school}"):
            dbg = {"input_url": url, "bell_url": bell_url, "calendar_url": cal_url, "ics_url": ics_url}
            if crawl_debug:  dbg["crawler_debug"] = crawl_debug
            if homepage_dbg: dbg.update(homepage_dbg)
            st.json(dbg)
            if show_top_anchors and homepage_dbg:
                st.write("Top bell candidates (homepage):"); st.write(homepage_dbg.get("home_bell_top", []))
                st.write("Top calendar candidates (homepage):"); st.write(homepage_dbg.get("home_cal_top", []))

    # ---- Dismissal ----
    dismissal_str = None
    if bell_url:
        bell_html = fetch_html(bell_url)
        dismissal_str = parse_dismissal_time_from_html(
            bell_html or "", preferred_weekday=weekday, use_ai=ai_assist_bell
        )
    if not dismissal_str:
        dismissal_str = "3:00 pm"

    # ---- No-school dates ----
    no_school = set()
    if ics_url:
        no_school |= parse_ics_dates(ics_url)
    if cal_url:
        cal_html = fetch_text(cal_url)
        if cal_html:
            candidates = parse_html_no_school_candidates(cal_html)
            if ai_assist_calendar:
                no_school |= classify_no_school_ai(candidates)
            else:
                from dateutil import parser as dtp
                no_school |= {dtp.parse(tok, fuzzy=True).date() for _, tok in candidates}

    # ---- Sessions ----
    sessions = compute_weekly_sessions(
        school=school, weekday_str=weekday, dismissal_time_str=dismissal_str,
        quarter_start=q_start, quarter_end=q_end, params=params, no_school_dates=no_school,
    )
    all_sessions.extend(sessions)

    results_rows.append({
        "school": school,
        "weekday": weekday,
        "bell_url": bell_url or "",
        "calendar_url": cal_url or "",
        "ics_url": ics_url or "",
        "dismissal": dismissal_str,
        "sessions": len(sessions),
        "no_class_dates": "; ".join(sorted({d.strftime('%m/%d/%Y') for d in no_school if q_start <= d <= q_end})),
    })

# ---------- Tables ----------
st.subheader("Crawl & Parse Summary (sortable)")
summary_df = pd.DataFrame(results_rows)
st.dataframe(summary_df, use_container_width=True)

st.subheader("Planned Sessions Preview (sortable)")
preview_df = pd.DataFrame([{
    **s,
    "date": s["date"].strftime("%Y-%m-%d"),
    "start_time": s["start_time"].strftime("%I:%M %p").lstrip('0'),
    "end_time": s["end_time"].strftime("%I:%M %p").lstrip('0'),
} for s in all_sessions])
st.dataframe(preview_df, use_container_width=True)

# ---------- Rollup ----------
from collections import defaultdict
by_school = defaultdict(list)
for s in all_sessions: by_school[s["school"]].append(s)

rows = []
for school, items in by_school.items():
    dates = sorted([x["date"] for x in items])
    all_no_school_quarter = sorted(d for d in no_school if q_start <= d <= q_end)
    rows.append({
        "School": school,
        "Start Date": dates[0].strftime("%m/%d/%Y") if dates else "",
        "End Date": dates[-1].strftime("%m/%d/%Y") if dates else "",
        "Start Time": items[0]["start_time"].strftime("%I:%M %p").lstrip('0') if items else "",
        "End Time": items[0]["end_time"].strftime("%I:%M %p").lstrip('0') if items else "",
        "Target Sessions": params.target_sessions,
        "Scheduled Sessions": len(items),
        "Session Dates": "; ".join(d.strftime("%m/%d/%Y") for d in dates),
        "No-Class Dates (Observed)": (
            summary_df[summary_df["school"] == school].iloc[0]["no_class_dates"]
            if not summary_df[summary_df["school"] == school].empty else ""
        ),
        "No-School (All in Quarter)": "; ".join(d.strftime("%m/%d/%Y") for d in all_no_school_quarter),
    })
out_df = pd.DataFrame(rows)

st.subheader("Summary (sortable)")
st.dataframe(out_df, use_container_width=True)

# ---------- Downloads ----------
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
        all_sessions, columns=export_cols,
        title_tpl=cfg["export"]["title_template"], notes_tpl=cfg["export"]["notes_template"],
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
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=24, leftMargin=24, topMargin=24, bottomMargin=24)
        styles = getSampleStyleSheet()
        story = [Paragraph("After-School Planner — Summary", styles["Title"]), Spacer(1, 12)]
        data = [list(df.columns)] + df.values.tolist()
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.lightgrey),
            ("TEXTCOLOR",(0,0),(-1,0),colors.black),
            ("GRID",(0,0),(-1,-1),0.25,colors.grey),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),9),
            ("ALIGN",(0,0),(-1,-1),"LEFT"),
        ]))
        story.append(table); doc.build(story)
        pdf = buffer.getvalue(); buffer.close(); return pdf
    st.download_button("Download Summary PDF", data=build_pdf(out_df),
                       file_name="after_school_summary.pdf", mime="application/pdf")
