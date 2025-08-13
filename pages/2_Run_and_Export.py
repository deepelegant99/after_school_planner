import os, streamlit as st
import pandas as pd
from core.crawler import crawl_school, fetch_html
from core.parsers_bell import parse_dismissal_time_from_html
from core.parsers_calendar import fetch_text, parse_html_no_school_candidates, parse_ics_dates, classify_no_school_ai
from core.scheduler import ScheduleParams, compute_weekly_sessions
from core.exporter import export_facilitron
import tomllib
from dotenv import load_dotenv
load_dotenv()  # reads .env into os.environ
st.write("AI key loaded:", bool(os.getenv("OPENAI_API_KEY")))

# PDF helpers
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

st.set_page_config(page_title="After-School Planner — Run", page_icon="🏁", layout="wide")

with open("config.toml","rb") as f:
    cfg = tomllib.load(f)

st.title("Run & Export")

if "input_df" not in st.session_state:
    st.warning("Upload CSV in **Settings & Input** first.")
    st.stop()

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

input_df = st.session_state["input_df"].copy()

progress = st.progress(0)
all_sessions = []
results_rows = []

for idx, row in input_df.iterrows():
    pct = int((idx+1)/len(input_df)*100)
    progress.progress(pct)

    school = row.get("school_name", "").strip()
    url = row.get("school_url", "").strip()
    weekday = row.get("Day of the week", "").strip()

    bell_override = str(row.get("bell_schedule_page_url", "")).strip() or None
    cal_override = str(row.get("school_calendar_page_url", "")).strip() or None

    bell_url = bell_override
    cal_url = cal_override
    ics_url = None
    
    def _is_ics(u): 
        return isinstance(u, str) and u.lower().endswith((".ics", ".ical"))

    if cal_override and _is_ics(cal_override):
        ics_url = cal_override  # treat override as ICS
        cal_url = None


    if not bell_url or not cal_url:
        crawl = crawl_school(url, use_openai=use_openai, max_anchors=max_anchors, delay=delay_sec, use_headless_fallback=use_headless_fallback)
        bell_url = bell_url or crawl.bell_url
        cal_url = cal_url or crawl.cal_url
        ics_url = crawl.ics_url

    dismissal_str = None
    if bell_url:
        bell_html = fetch_html(bell_url)
        dismissal_str = parse_dismissal_time_from_html(bell_html or "", preferred_weekday=weekday, use_ai=ai_assist_bell)

    if not dismissal_str:
        dismissal_str = "3:00 pm"  # fallback

    # no-school dates
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

st.subheader("Crawl & Parse Summary (sortable)")
summary_df = pd.DataFrame(results_rows)
st.dataframe(summary_df, use_container_width=True)

st.subheader("Planned Sessions Preview (sortable)")
preview_df = pd.DataFrame([{**s, "date": s["date"].strftime("%Y-%m-%d"),
                            "start_time": s["start_time"].strftime("%I:%M %p").lstrip('0'),
                            "end_time": s["end_time"].strftime("%I:%M %p").lstrip('0')}
                           for s in all_sessions])
st.dataframe(preview_df, use_container_width=True)

# Build per-school summary output
from collections import defaultdict
by_school = defaultdict(list)
for s in all_sessions:
    by_school[s["school"]].append(s)

rows = []
for school, items in by_school.items():
    dates = sorted([x["date"] for x in items])
    start_date = dates[0].strftime("%m/%d/%Y") if dates else ""
    end_date = dates[-1].strftime("%m/%d/%Y") if dates else ""
    start_time = items[0]["start_time"].strftime("%I:%M %p").lstrip('0') if items else ""
    end_time = items[0]["end_time"].strftime("%I:%M %p").lstrip('0') if items else ""
    target = params.target_sessions
    scheduled = len(items)
    match = summary_df[summary_df["school"] == school]
    no_class = match.iloc[0]["no_class_dates"] if not match.empty else ""
    rows.append({
        "School": school,
        "Start Date": start_date,
        "End Date": end_date,
        "Start Time": start_time,
        "End Time": end_time,
        "Target Sessions": target,
        "Scheduled Sessions": scheduled,
        "Session Dates": "; ".join(d.strftime("%m/%d/%Y") for d in dates),
        "No-Class Dates (Observed)": no_class,
    })

out_df = pd.DataFrame(rows)

st.subheader("Summary (sortable)")
st.dataframe(out_df, use_container_width=True)

# ---- CSV downloads ----
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

# ---- PDF download (Summary) ----
with col3:
    def build_pdf(df: pd.DataFrame) -> bytes:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=24, leftMargin=24, topMargin=24, bottomMargin=24)
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph("After-School Planner — Summary", styles["Title"]))
        story.append(Spacer(1, 12))
        data = [list(df.columns)] + df.values.tolist()
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("TEXTCOLOR", (0,0), (-1,0), colors.black),
            ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ]))
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
