from __future__ import annotations
import json
from pathlib import Path
from typing import Any

REQUIRED_ENTRIES = ("loan.annual_rate_percent", "loan.term_months", "loan.guarantee_ceiling_krw",
                    "loan.policy_fund_ceiling_krw", "stress.revenue_drop_ratio",
                    "stress.repayment_burden_cap_ratio", "working_capital.months")
REQUIRED_INDUSTRY_FIELDS = ("cogs_ratio", "labor_ratio", "fitout_krw_per_pyeong", "operating_days_per_month")


class PolicyParams:
    """제도·업종 파라미터. 등록되지 않은 값은 절대 추정하지 않고 누락으로 보고한다."""

    def __init__(self, raw: dict[str, Any]):
        self._entries = raw.get("entries") or {}
        self._industries = raw.get("industries") or {}
        self.updated_at = raw.get("updated_at")

    @classmethod
    def load(cls, path: str | Path) -> PolicyParams:
        target = Path(path)
        if not target.exists():
            return cls({})
        return cls(json.loads(target.read_text(encoding="utf-8")))

    def missing(self, industry: str) -> list[str]:
        gaps = [key for key in REQUIRED_ENTRIES
                if (self._entries.get(key) or {}).get("value") is None]
        profile = self._industries.get(industry)
        if not profile:
            gaps.append(f"industries.{industry}")
            return gaps
        gaps.extend(f"industries.{industry}.{field}" for field in REQUIRED_INDUSTRY_FIELDS
                    if profile.get(field) is None)
        return gaps

    def value(self, key: str) -> float:
        entry = self._entries.get(key) or {}
        if entry.get("value") is None:
            raise KeyError(key)
        return float(entry["value"])

    def industry(self, name: str) -> dict[str, Any]:
        profile = self._industries.get(name)
        if not profile:
            raise KeyError(f"industries.{name}")
        return profile

    def sources(self, industry: str) -> list[str]:
        labels = {str((self._entries.get(key) or {}).get("source")) for key in REQUIRED_ENTRIES}
        profile = self._industries.get(industry) or {}
        if profile.get("source"):
            labels.add(str(profile["source"]))
        return sorted(label for label in labels if label and label != "None")
