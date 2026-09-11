from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class ShopPolicy:
    data: Dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "ShopPolicy":
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        required = {"name", "timezone", "hours", "services", "slot_minutes", "handoff"}
        missing = required - set(data)
        if missing:
            raise ValueError("Policy is missing: " + ", ".join(sorted(missing)))
        ZoneInfo(data["timezone"])
        return cls(data)

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.data["timezone"])

    @property
    def slot_minutes(self) -> int:
        return int(self.data["slot_minutes"])

    @property
    def late_policy_minutes(self) -> int:
        return int(self.data["late_policy_minutes"])

    def service(self, service_name: str) -> Dict[str, Any]:
        try:
            return self.data["services"][service_name]
        except KeyError as exc:
            raise ValueError(f"Unknown service: {service_name}") from exc

    def duration_minutes(self, service_name: str) -> int:
        return int(self.service(service_name)["minutes"])

    def hours_for(self, day: date) -> Tuple[datetime, datetime] | None:
        hours = self.data["hours"].get(DAY_KEYS[day.weekday()])
        if not hours:
            return None
        opening = datetime.combine(day, time.fromisoformat(hours[0]), self.timezone)
        closing = datetime.combine(day, time.fromisoformat(hours[1]), self.timezone)
        return opening, closing

    def faq(self, topic: str) -> str | Dict[str, Any] | List[str] | int | None:
        normalized = topic.strip().lower()
        if normalized == "breeds":
            return {
                "breeds_we_groom": self.data.get("breeds_we_groom", []),
                "breeds_need_consult": self.data.get("breeds_need_consult", []),
                "breeds_we_dont": self.data.get("breeds_we_dont", []),
            }
        aliases = {
            "hours": "hours",
            "services": "services",
            "prices": "services",
            "vaccines": "vaccines",
            "late_policy": "late_policy_minutes",
            "name": "name",
        }
        key = aliases.get(normalized)
        return self.data.get(key) if key else None

