from __future__ import annotations

from datetime import date, datetime

DAY_FORMAT = "%A, %d %b %Y"


def describe_day(day: date) -> str:
    return day.strftime(DAY_FORMAT)


def describe_moment(value: str | None) -> str:
    """Human label for an ISO date or datetime, so weekdays are never inferred."""
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return ""
    if len(value) == 10:
        return describe_day(moment.date())
    return f"{describe_day(moment.date())} at {moment:%H:%M}"
