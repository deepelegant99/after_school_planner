# After-School Planner (Streamlit)

Automates: CSV of schools → crawl Bell Schedule & Academic Calendar → parse dismissal & no‑school dates → compute weekly after‑school plan → export **Summary CSV/PDF** + **Facilitron CSV**.

## Input CSV
Required columns:
- `school_name`
- `school_url`
- `weekday` (Mon/Tue/Wed/Thur/Fri)

Optional columns (skip crawling if provided):
- `bell_schedule_page_url`
- `school_calendar_page_url`

See `sample_data/sample_input.csv`.

## Install & Run
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install   # headless fallback

# (optional) AI assists
export OPENAI_API_KEY=sk-...   # Windows PowerShell: $env:OPENAI_API_KEY="sk-..."

streamlit run app.py
```

## What the app does
- **Find links**: HTML first; if empty/JS-heavy, **headless fallback** (Playwright). AI classifies anchors (top `max_anchors`) to pick Bell/Calendar/ICS.
- **Parse times**: Regex/table scan of bell page; **AI assist** to decide the “normal” dismissal time for the chosen weekday.
- **Parse calendar**: Prefer ICS; otherwise HTML lines → **AI assist** labels “no class” days.
- **Schedule**: Within quarter window; skip no-class dates; respect buffer, earliest start, latest end, duration; hit target sessions if possible.
- **Export**: 
  - **Summary CSV/PDF** (Start Date, End Date, Session Dates, No‑Class Dates, counts)
  - **Facilitron CSV** (per‑session rows with times)

## Notes
- All AI assists are toggles in the sidebar (default: ON).
- `max_anchors` controls how many links we send to the model (default: 60).
