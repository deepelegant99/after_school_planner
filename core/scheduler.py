from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Dict, Set
from dateutil import parser as dtp

# Accept several common spellings/abbreviations
WEEKDAYS = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "weds": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
}

@dataclass
class ScheduleParams:
    buffer_minutes: int
    session_duration_minutes: int
    earliest_start: time
    latest_end: time
    target_sessions: int
    min_sessions: int

def clamp_start(dismissal: time, earliest: time, buffer_min: int) -> time:
    base = (datetime.combine(date.today(), dismissal) + timedelta(minutes=buffer_min)).time()
    return max(base, earliest)

def _weekday_index(weekday_str: str) -> int:
    if not weekday_str:
        raise ValueError("Weekday string is empty or None.")
    key = weekday_str.strip().lower()
    # Use first 3 chars if exact not found
    if key not in WEEKDAYS:
        key = key[:3]
    if key not in WEEKDAYS:
        raise ValueError(f"Unrecognized weekday: {weekday_str!r}")
    return WEEKDAYS[key]

def compute_weekly_sessions(
    school: str,
    weekday_str: str,
    dismissal_time_str: str,
    quarter_start: date,
    quarter_end: date,
    params: ScheduleParams,
    no_school_dates: Set[date],
) -> List[Dict]:
    wd = _weekday_index(weekday_str)

    # Robust dismissal parsing
    dismissal = dtp.parse(dismissal_time_str).time()

    # Start/end time with buffer + clamps
    start_time = clamp_start(dismissal, params.earliest_start, params.buffer_minutes)
    end_time = (datetime.combine(date.today(), start_time)
                + timedelta(minutes=params.session_duration_minutes)).time()
    if end_time > params.latest_end:
        end_time = params.latest_end
        latest_start_allowed = (datetime.combine(date.today(), params.latest_end)
                                - timedelta(minutes=params.session_duration_minutes)).time()
        if start_time > latest_start_allowed:
            start_time = latest_start_allowed

    sessions: List[Dict] = []
    d = quarter_start

    # Align to the first wanted weekday
    while d.weekday() != wd:
        d += timedelta(days=1)

    # Generate sessions
    while d <= quarter_end and len(sessions) < params.target_sessions:
        if d not in no_school_dates:
            sessions.append({
                "school": school,
                "date": d,
                "start_time": start_time,
                "end_time": end_time,
                "dismissal": dismissal,
            })
        d += timedelta(days=7)

    return sessions
