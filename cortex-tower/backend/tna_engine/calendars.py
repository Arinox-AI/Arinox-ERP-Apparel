"""Working-day arithmetic per site. Pure. D5: the seeded calendars are 7-day with no holidays; the mechanism stays as data."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = 4000


def as_date(v) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


class WorkingCalendar:
    """``working_weekdays`` (Monday = 0), ``holidays`` and ``special_working_days`` (a holiday or weekend that works). ``shift`` counts WORKING days."""

    def __init__(self, working_weekdays: Iterable[int] = range(7), holidays: Iterable = (), special_working_days: Iterable = (), cal_id: str = ""):
        self.id = cal_id
        self.weekdays = set(int(x) for x in working_weekdays)
        self.holidays = {as_date(h) for h in holidays}
        self.special = {as_date(h) for h in special_working_days}

    def works(self, d: date) -> bool:
        if d in self.special:
            return True
        return d.weekday() in self.weekdays and d not in self.holidays

    def snap(self, d: date, direction: int = 1) -> date:
        """``d`` if it works, else the nearest working day in ``direction`` (1 forward, -1 back)."""
        n = 0
        while not self.works(d) and n < GUARD:
            d += timedelta(days=direction)
            n += 1
        return d

    def shift(self, d: date, n: int) -> date:
        """``d`` moved ``n`` working days (negative: back). ``d`` itself is first snapped in the direction of travel (n = 0 snaps forward)."""
        step = 1 if n >= 0 else -1
        cur = self.snap(d, step)
        left, guard = abs(n), 0
        while left and guard < GUARD:
            cur += timedelta(days=step)
            if self.works(cur):
                left -= 1
            guard += 1
        return cur

    def between(self, a: date, b: date) -> int:
        """Signed working days from ``a`` to ``b`` (b later: positive). ``between(a, a) == 0``."""
        if a == b:
            return 0
        lo, hi, sign = (a, b, 1) if a < b else (b, a, -1)
        n, cur = 0, lo
        while cur < hi:
            cur += timedelta(days=1)
            if self.works(cur):
                n += 1
        return sign * n

    def holidays_in(self, a: date, b: date) -> list[date]:
        return sorted(h for h in self.holidays if a <= h <= b)


def load_calendars(path: str = "") -> dict[str, WorkingCalendar]:
    raw = json.load(open(path or os.path.join(HERE, "calendars.json")))
    return {k: WorkingCalendar(v.get("working_weekdays", range(7)), v.get("holidays", ()), v.get("special_working_days", ()), k)
            for k, v in raw.items() if not k.startswith("_")}


def holiday_list_gap(cal_holidays_end: Optional[date], plan_end: date) -> bool:
    """True when a plan reaches past the end of the holiday data (a data-quality warning, TNA plan section 6.9). No data = no warning (D5)."""
    return bool(cal_holidays_end) and plan_end > cal_holidays_end
