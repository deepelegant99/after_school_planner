import os, streamlit as st
import pandas as pd
from datetime import date, time
import tomllib
from dotenv import load_dotenv
load_dotenv()  # reads .env into os.environ

st.set_page_config(page_title="After-School Planner — Settings", page_icon="📅", layout="wide")
st.write("AI key loaded:", bool(os.getenv("OPENAI_API_KEY")))

with open("config.toml","rb") as f:
    cfg = tomllib.load(f)

st.title("After-School Planner")
st.caption("CSV → crawl → parse → plan → CSV & PDF")

with st.sidebar:
    st.header("Quarter Window")
    q_start = st.date_input("Quarter start", value=date.today())
    q_end = st.date_input("Quarter end", value=date(date.today().year, 12, 31))

    st.header("Timing")
    buffer_minutes = st.number_input("Buffer minutes", min_value=0, max_value=120, value=cfg["scheduler"]["buffer_minutes"])
    session_duration_minutes = st.number_input("Session duration (min)", min_value=30, max_value=240, value=cfg["scheduler"]["session_duration_minutes"])
    earliest_start = st.time_input("Earliest start", value=time.fromisoformat(cfg["scheduler"]["earliest_start"]))
    latest_end = st.time_input("Latest end", value=time.fromisoformat(cfg["scheduler"]["latest_end"]))

    st.header("Sessions")
    target_sessions = st.number_input("Target sessions", min_value=1, max_value=30, value=10)
    min_sessions = st.number_input("Minimum sessions", min_value=1, max_value=30, value=8)

    st.header("Crawl & Parsing Options")
    use_openai = st.toggle("Use OpenAI to pick links (recommended)", value=True)
    ai_assist_bell = st.toggle("Use AI to choose dismissal time (smarter)", value=True)
    ai_assist_calendar = st.toggle("Use AI to classify no‑class entries", value=True)
    use_headless_fallback = st.toggle("Headless browser fallback for JS sites", value=True)
    max_anchors = st.number_input("max_anchors to send to AI", min_value=10, max_value=200, value=60)
    delay_between_schools_seconds = st.number_input("Delay between schools (sec)", min_value=0, max_value=10, value=2)

uploaded = st.file_uploader(
    "Upload CSV (school_name, school_url, Day of the week[, bell_schedule_page_url, school_calendar_page_url])",
    type=["csv"]
)

if uploaded:
    df = pd.read_csv(uploaded)
    st.session_state["input_df"] = df
    st.success("CSV loaded.")
    st.dataframe(df, use_container_width=True)

st.session_state.update({
    "q_start": q_start, "q_end": q_end,
    "buffer_minutes": int(buffer_minutes),
    "session_duration_minutes": int(session_duration_minutes),
    "earliest_start": earliest_start,
    "latest_end": latest_end,
    "target_sessions": int(target_sessions),
    "min_sessions": int(min_sessions),
    "use_openai": bool(use_openai),
    "ai_assist_bell": bool(ai_assist_bell),
    "ai_assist_calendar": bool(ai_assist_calendar),
    "use_headless_fallback": bool(use_headless_fallback),
    "max_anchors": int(max_anchors),
    "delay_between_schools_seconds": int(delay_between_schools_seconds),
})

st.info("Go to **Run & Export** when ready →")
