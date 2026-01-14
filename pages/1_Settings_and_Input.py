# pages/1_Settings_and_Input.py
from __future__ import annotations

import streamlit as st
import pandas as pd
from datetime import date, time, datetime, timedelta

st.set_page_config(page_title="After-School Planner — Settings & Input", page_icon="🛠️", layout="wide")
st.title("Settings & Input")

# -------------------------------
# Helper
# -------------------------------
def _norm_webcal(u: str | None) -> str | None:
    if not u:
        return u
    uu = str(u).strip()
    return "https://" + uu[len("webcal://"):] if uu.lower().startswith("webcal://") else uu

# -------------------------------
# Controls (kept minimal but compatible with page 2)
# -------------------------------
with st.expander("Planner settings", expanded=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        buffer_minutes = st.number_input("Buffer minutes after dismissal", 0, 120, value=15)
        session_duration_minutes = st.number_input("Session duration (minutes)", 30, 300, value=60)
    with c2:
        earliest_start = st.time_input("Earliest start", time(15, 0))
        latest_end = st.time_input("Latest end", time(18, 0))
    with c3:
        target_sessions = st.number_input("Target sessions", 1, 60, value=10)
        min_sessions = st.number_input("Minimum sessions", 1, 60, value=8)

with st.expander("Quarter window", expanded=True):
    today = date.today()
    default_start = date(today.year, 8, 15)
    default_end = date(today.year, 11, 5)
    q_start = st.date_input("Quarter start", value=default_start)
    q_end = st.date_input("Quarter end", value=default_end)

with st.expander("Crawler/AI", expanded=False):
    use_openai = st.toggle("Use AI to classify no-class entries", value=True)
    ai_assist_bell = st.toggle("AI-assisted bell parsing", value=True)
    ai_assist_calendar = st.toggle("AI-assisted calendar parsing", value=True)
    use_headless_fallback = st.toggle("Headless browser fallback for JS sites", value=True)
    max_anchors = st.number_input("Max anchors to send to AI", 10, 200, value=80)
    delay_between_schools_seconds = st.number_input("Delay between schools (sec)", 0, 10, value=1)

# -------------------------------
# CSV Upload
# -------------------------------
st.subheader("Upload CSV")
uploaded = st.file_uploader(
    "Upload CSV (school_name/program, school_url, weekday, bell_schedule_page_url, school_calendar_page_url, district, district_ics_url)",
    type=["csv"],
)

if uploaded:
    # Keep 'None'/'nan'/'null' as strings; we sanitize below
    df = pd.read_csv(uploaded, keep_default_na=False)

    # Normalize Notion-friendly headers to internal names
    normalized_cols = {col: str(col).strip() for col in df.columns}
    df = df.rename(columns=normalized_cols)
    friendly_to_internal = {
        "Program": "school_name",
        "School URL": "school_url",
        "Weekday": "weekday",
        "Bell Schedule URL": "bell_schedule_page_url",
        "School Calendar URL": "school_calendar_page_url",
        "District": "district",
        "District ICS": "district_ics_url",
    }
    df = df.rename(columns=friendly_to_internal)

    # Ensure newer columns exist
    for col in [
        "weekday",
        "district",
        "district_ics_url",
        "bell_schedule_page_url",
        "school_calendar_page_url",
    ]:
        if col not in df.columns:
            df[col] = ""

    # Trim/clean common text columns
    for col in [
        "school_name",
        "school_url",
        "weekday",
        "bell_schedule_page_url",
        "school_calendar_page_url",
        "district",
        "district_ics_url",
    ]:
        df[col] = df[col].astype(str).str.strip()

    # Normalize district ICS
    df["district_ics_url"] = df["district_ics_url"].map(lambda s: _norm_webcal(s) if isinstance(s, str) else s)

    # Build district -> ics map (ignore blanks; dedupe)
    looks_like_ics = df["district_ics_url"].str.contains(r"\.ics(?:$|\?)", case=False, na=False, regex=True)
    _map_df = df.loc[(df["district"].ne("")) & looks_like_ics, ["district", "district_ics_url"]].drop_duplicates()
    st.session_state["district_ics_map"] = dict(_map_df.itertuples(index=False, name=None))

    # Optional school -> district_ics mapping for roll-up "Observed"
    st.session_state["school2ics"] = {
        r["school_name"]: r["district_ics_url"]
        for _, r in df.iterrows()
        if r.get("school_name") and r.get("district_ics_url")
    }

    # Keep DF for page 2
    st.session_state["input_df"] = df

    st.success("CSV loaded.")
    display_df = df.rename(
        columns={
            "school_name": "Program",
            "school_url": "School URL",
            "weekday": "Weekday",
            "district": "District",
            "district_ics_url": "District ICS",
            "bell_schedule_page_url": "Bell Schedule URL",
            "school_calendar_page_url": "School Calendar URL",
        }
    )
    st.dataframe(display_df, use_container_width=True)

# -------------------------------
# Persist planner/crawler settings into session
# -------------------------------
st.session_state.update({
    "buffer_minutes": int(buffer_minutes),
    "session_duration_minutes": int(session_duration_minutes),
    "earliest_start": earliest_start,
    "latest_end": latest_end,
    "target_sessions": int(target_sessions),
    "min_sessions": int(min_sessions),
    "q_start": q_start,
    "q_end": q_end,
    "use_openai": bool(use_openai),
    "ai_assist_bell": bool(ai_assist_bell),
    "ai_assist_calendar": bool(ai_assist_calendar),
    "use_headless_fallback": bool(use_headless_fallback),
    "max_anchors": int(max_anchors),
    "delay_between_schools_seconds": int(delay_between_schools_seconds),
})

st.markdown("Go to **Run & Export** when ready →")
