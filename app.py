import streamlit as st
from dotenv import load_dotenv
load_dotenv()  # reads .env into os.environ

st.set_page_config(page_title="After-School Planner", page_icon="🏫", layout="wide")
st.title("After-School Planner")
st.write("Use the pages on the left: **Settings & Input** → **Run & Export**.")
st.caption("If it schedules itself, it’s Skynet. If it schedules after-school, it’s us.")
