from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from .industry import display_name
from .industry import resolve as resolve_industry

REQUIRED_ENTRIES = ("loan.annual_rate_percent", "loan.term_months", "loan.guarantee_ceiling_krw",
                    "loan.policy_fund_ceiling_krw", "stress.revenue_drop_ratio",
                    "stress.repayment_burden_cap_ratio", "working_capital.months")
REQUIRED_INDUSTRY_FIELDS = ("cogs_ratio", "labor_ratio", "fitout_krw_per_pyeong", "operating_days_per_month")

# 값의 성격. config/policy-params.json 의 basis 와 같은 어휘를 쓴다.
DEMO_ASSUMPTION = "DEMO_ASSUMPTION"


class PolicyParams:
    """제도·업종 파라미터. 등록되지 않은 값은 절대 추정하지 않고 누락으로 보고한다.

    등록된 값에도 성격이 있다. `basis` 가 DEMO_ASSUMPTION 인 항목은 실측·공시 출처가 없는
    시연용 가정값이다. 값이 있다는 것과 근거가 있다는 것은 다르므로, 어떤 항목이 가정인지를
    `assumed()` 로 밖에 알려 준다 — 호출자는 그것을 응답의 고지와 confidence 에 반영한다.
    """

    def __init__(self, raw: dict[str, Any]):
        self._entries = raw.get("entries") or {}
        self._industries = raw.get("industries") or {}
        self.updated_at = raw.get("updated_at")

    @classmethod
    def load(cls, path: str | Path) -> PolicyParams:
        target = Path(path)
        if not target.is_absolute() and not target.exists():
            # uvicorn은 저장소 루트에서, pytest는 backend/에서 실행되므로 루트 기준으로도 찾는다.
            target = Path(__file__).resolve().parents[2] / target
        if not target.exists():
            return cls({})
        return cls(json.loads(target.read_text(encoding="utf-8")))

    def _lookup(self, industry: str) -> tuple[str, dict[str, Any] | None]:
        """업종 문자열 → (실제로 찾은 키, 프로파일).

        두 가지 키를 모두 받는다. 이름을 그대로 적은 프로파일(`"카페": {...}`)이 있으면
        그것이 이기고, 없으면 서울시 상권분석서비스 업종 코드(`"CS100010"`)로 찾는다.
        코드 키가 있어야 '카페'·'커피'·'cafe' 가 같은 업종으로 모이고, 이름 키를 남겨 두면
        특정 업종만 따로 값을 주고 싶을 때 코드를 몰라도 된다.

        찾지 못하면 사용자가 쓴 문자열을 그대로 돌려준다 — 누락 보고에 코드가 아니라
        입력한 말이 찍혀야 무엇을 등록해야 하는지 알아볼 수 있다.
        """
        direct = self._industries.get(industry)
        if direct is not None:
            return industry, direct
        code = resolve_industry(industry)
        if code and code in self._industries:
            return code, self._industries[code]
        return industry, None

    def _profile(self, industry: str) -> dict[str, Any] | None:
        return self._lookup(industry)[1]

    def missing_of(self, keys: tuple[str, ...]) -> list[str]:
        """주어진 키 중 값이 없는 것. 산출마다 필요한 키가 다르므로 목록을 받는다 —
        조달 여력은 보증·정책자금 한도만 있으면 나오고, 밴드는 그보다 많이 요구한다."""
        return [key for key in keys if (self._entries.get(key) or {}).get("value") is None]

    def missing(self, industry: str) -> list[str]:
        gaps = self.missing_of(REQUIRED_ENTRIES)
        key, profile = self._lookup(industry)
        if not profile:
            gaps.append(f"industries.{key}")
            return gaps
        gaps.extend(f"industries.{key}.{field}" for field in REQUIRED_INDUSTRY_FIELDS
                    if profile.get(field) is None)
        return gaps

    def value(self, key: str) -> float:
        entry = self._entries.get(key) or {}
        if entry.get("value") is None:
            raise KeyError(key)
        return float(entry["value"])

    def industry(self, name: str) -> dict[str, Any]:
        key, profile = self._lookup(name)
        if not profile:
            raise KeyError(f"industries.{key}")
        return profile

    def assumed_of(self, keys: tuple[str, ...]) -> list[str]:
        """주어진 키 중 시연용 가정인 것. 산출마다 쓰는 값이 다르므로 범위를 받는다 —
        조달 여력은 보증·정책자금 한도만 쓰고, 밴드는 그보다 많이 쓴다. 실제로 쓰지 않은
        값까지 '시연용'이라 말하면 고지가 넓어져 어느 수치가 가정인지 알 수 없게 된다."""
        return [key for key in keys if (self._entries.get(key) or {}).get("basis") == DEMO_ASSUMPTION]

    def assumed(self, industry: str) -> list[str]:
        """이번 계산에 쓰이는 값 중 시연용 가정인 항목들. 없으면 빈 목록."""
        names = self.assumed_of(REQUIRED_ENTRIES)
        key, profile = self._lookup(industry)
        if profile and profile.get("basis") == DEMO_ASSUMPTION:
            names.append(f"industries.{key}")
        return names

    def industry_label(self, industry: str) -> str:
        """화면에 쓰는 업종명. 매핑됐으면 상권분석서비스의 정식 업종명을 쓴다."""
        code = resolve_industry(industry)
        return display_name(code) if code else industry

    def sources(self, industry: str) -> list[str]:
        """화면에 실을 짧은 출처 이름들.

        `source` 는 왜 그 값인지를 적어 둔 문단이라 좁은 패널에 그대로 실으면 700자가
        넘는다. 그러면 정작 읽어야 할 '시연용 가정값' 경고가 그 안에 묻힌다. 그래서
        화면에는 `label` 을 쓰고, 문단은 config 파일에 남겨 둔다.
        """
        def name(entry: dict[str, Any]) -> str | None:
            return entry.get("label") or entry.get("source")

        labels = {name(self._entries.get(key) or {}) for key in REQUIRED_ENTRIES}
        labels.add(name(self._profile(industry) or {}))
        return sorted(label for label in labels if label)
