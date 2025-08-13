from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Dict, Set
from dateutil import parser as dtp

WEEKDAYS = {"mon":0, "tue":1, "wed":2, "thu":3, "thur":3, "fri":4}

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

def compute_weekly_sessions(
    school: str,
    weekday_str: str,
    dismissal_time_str: str,
    quarter_start: date,
    quarter_end: date,
    params: ScheduleParams,
    no_school_dates: Set[date],
) -> List[Dict]:
    wd = WEEKDAYS[weekday_str.strip().lower()[:3]]
    dismissal = dtp.parse(dismissal_time_str).time()
    start_time = clamp_start(dismissal, params.earliest_start, params.buffer_minutes)
    end_time = (datetime.combine(date.today(), start_time) + timedelta(minutes=params.session_duration_minutes)).time()
    if end_time > params.latest_end:
        end_time = params.latest_end
        latest_start_allowed = (datetime.combine(date.today(), params.latest_end) - timedelta(minutes=params.session_duration_minutes)).time()
        if start_time > latest_start_allowed:
            start_time = latest_start_allowed

    sessions = []
    d = quarter_start
    while d.weekday() != wd:
        d = d + timedelta(days=1)
    while d <= quarter_end and len(sessions) < params.target_sessions:
        if d not in no_school_dates:
            sessions.append({
                "school": school,
                "date": d,
                "start_time": start_time,
                "end_time": end_time,
                "dismissal": dismissal,
            })
        d = d + timedelta(days=7)
    return sessions
