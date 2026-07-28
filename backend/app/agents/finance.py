"""얼마 — 금융처방 팀.

제안서 04장의 되먹임 방향에서 이 팀이 **선행**한다. 조달 상한을 모르는 상태에서는 감당 불가한
후보를 걸러낼 기준이 없으므로, 이 팀이 기준선을 만들고 입지팀이 그 선을 넘을 수 있는지 증명한다.
그래서 팀 계약이 `blocking=True` 다 — 밴드를 못 그리면 후속 전체가 중단된다.

네 서브에이전트 중 **밴드 산출만이 계산을 한다.** 스트레스는 같은 산출물을 읽고, 지원정책과
KB 상품은 조회한 값을 인용만 한다. 가드 1(숫자는 도구 결과만)을 지키는 가장 단순한 방법은
계산 지점을 하나로 모으는 것이다.
"""
from __future__ import annotations

from typing import Any

from dataclasses import dataclass

from ..funding import compute_bands
from ..models import Provenance
from .contracts import AgentOutcome, AgentStatus, TeamReport
from .registry import spec


@dataclass(frozen=True)
class FinanceReport(TeamReport):
    @property
    def halted(self) -> bool:
        """후속을 멈추는 조건은 "밴드를 그렸는가" 하나다. KB 공시가 붙었다는 사실은
        기준선을 대신하지 못하므로 기본 규칙(`활성 0건`)으로 판정하면 안 된다."""
        band = next((item for item in self.outcomes if item.key == "finance.band"), None)
        return band is None or not band.active

#: 창업 자금 조달에 쓸 수 있는 공시 카테고리. 소비자 대출(주담대·전세·예적금)은 창업자금이
#: 아니므로 여기 들어오지 않는다 — 넣으면 "조달 가능"을 잘못 말하게 된다.
STARTUP_FUNDING_CATEGORIES = frozenset({"BUSINESS_LOAN"})

#: `compute_bands` 가 받는 필드와 없을 때 쓰는 값. 케이스 조건에는 자치구·우선순위처럼 이 팀이
#: 쓰지 않는 항목이 함께 오므로, 통째로 넘기지 않고 여기서 고른다. 통째로 넘기면 조건에 필드가
#: 하나 늘 때마다 계산 함수가 TypeError 로 죽는다.
_BAND_FIELDS: tuple[tuple[str, Any], ...] = (
    ("industry", None), ("area_pyeong", None), ("deposit_krw", None),
    ("monthly_rent_krw", 0), ("monthly_maintenance_krw", 0), ("key_money_krw", 0),
    ("fitout_krw", None), ("equity_krw", 0), ("existing_debt_krw", 0),
    ("other_monthly_fixed_krw", 0),
)

_BAND_PENDING = ("조달 밴드 계산에 필요한 제도·업종 파라미터가 아직 등록되지 않았습니다. "
                 "등록 전에는 추정하지 않습니다.")
_SUBSIDY_PENDING = ("공고 원문에 지원 규모가 구조화된 금액 필드로 들어오지 않아 조달선 상향분을 "
                    "계산하지 않았습니다. 본문에서 금액을 추측해 상한을 올리지 않습니다.")
_KB_PENDING = "창업자금으로 쓸 수 있는 개인사업자대출 공시가 인덱스에 없습니다."
_MIX_NOTE = ("상품 조합 시뮬레이션은 제공하지 않습니다 — 공시의 한도가 문장(예: \"최대 5억원\")으로만 "
             "들어와 수치로 조합할 수 없습니다. 공시 금리를 그대로 인용하기만 합니다.")


class FinanceTeam:
    """조회 결과를 생성자로 받는다. 이 클래스는 네트워크를 모른다 — 그래야 팀 계약만 테스트된다."""

    team = "finance"
    name = "금융처방 팀"

    def __init__(self, params, *, kb_products: list[dict[str, Any]],
                 programs: list[dict[str, Any]]):
        self.params = params
        self.kb_products = kb_products
        self.programs = programs

    def run(self, conditions: dict[str, Any]) -> TeamReport:
        band, computed = self._band(conditions)
        outcomes = [band,
                    self._stress(band, computed),
                    self._kb_products(),
                    self._subsidy()]
        return FinanceReport(team=self.team, name=self.name, outcomes=outcomes, blocking=True,
                             message=None if band.active else band.message)

    # ── 서브 1 · 조달 밴드 산출 ────────────────────────────────────────
    def _band(self, conditions: dict[str, Any]) -> tuple[AgentOutcome, dict[str, Any] | None]:
        declaration = spec("finance.band")
        industry = conditions["industry"]
        missing = self.params.missing(industry)
        if missing:
            return declaration.outcome(
                AgentStatus.INTEGRATION_PENDING, message=_BAND_PENDING,
                data={"missing_params": missing},
                required_actions=[f"{name} 을(를) 출처와 함께 등록해 주세요." for name in missing],
            ), None
        inputs = {name: conditions.get(name, fallback) for name, fallback in _BAND_FIELDS}
        try:
            computed = compute_bands(self.params, **inputs)
        except ValueError as error:
            # 공헌이익률이 0 이하인 업종 등 — 계산이 성립하지 않는다. 실패가 아니라 유보다:
            # 파라미터는 등록되어 있고, 이 업종 조합으로는 손익분기가 정의되지 않을 뿐이다.
            return declaration.outcome(
                AgentStatus.WITHHELD,
                message=f"등록된 업종 파라미터로는 손익분기를 계산할 수 없습니다: {error}",
                required_actions=["업종의 원가율·인건비율을 원천과 함께 다시 확인해 주세요."],
            ), None
        return declaration.outcome(
            AgentStatus.OK, data=computed, provenance=self._provenance(industry),
        ), computed

    def _provenance(self, industry: str) -> Provenance:
        sources = ", ".join(self.params.sources(industry)) or "미기재"
        return Provenance(
            source_name=f"자리매김 조달 밴드 계산 (파라미터 출처: {sources})",
            industry_scope=industry, spatial_unit="사용자 입력 조건",
            source_as_of=self.params.updated_at, confidence="LOW",
            limitations=["최대 조달선은 신용평가·보증 심사 전 추정치이며 확정 한도가 아닙니다.",
                         "지원사업 반영분은 조달선에 반영되지 않았습니다."],
        )

    # ── 서브 2 · 창업 금융 스트레스 테스트 ──────────────────────────────
    def _stress(self, band: AgentOutcome, computed: dict[str, Any] | None) -> AgentOutcome:
        declaration = spec("finance.stress")
        if computed is None:
            # 밴드가 못 나온 이유를 그대로 물려받는다. 여기서 따로 진단하지 않는다.
            return declaration.outcome(band.status, message=band.message)
        recommended = next(line for line in computed["bands"] if line["band"] == "RECOMMENDED")
        maximum = next(line for line in computed["bands"] if line["band"] == "MAXIMUM")
        return declaration.outcome(AgentStatus.OK, data={
            "revenue_drop_ratio": self.params.value("stress.revenue_drop_ratio"),
            "repayment_burden_cap_ratio": self.params.value("stress.repayment_burden_cap_ratio"),
            "recommended_passes_stress": recommended["stress_pass"],
            "maximum_passes_stress": maximum["stress_pass"],
            "recommended_burden_ratio": recommended["repayment_burden_ratio"],
            "maximum_burden_ratio": maximum["repayment_burden_ratio"],
            "recommended_runway_months": recommended["runway_months"],
            "maximum_runway_months": maximum["runway_months"],
        })

    # ── 서브 3 · KB 상품 조합 ─────────────────────────────────────────
    def _kb_products(self) -> AgentOutcome:
        declaration = spec("finance.kb_products")
        usable = [item for item in self.kb_products
                  if item.get("category") in STARTUP_FUNDING_CATEGORIES]
        if not usable:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=_KB_PENDING,
                                       data={"disclosed": [], "mix_simulated": False})
        try:
            policy_rate = self.params.value("loan.annual_rate_percent")
        except KeyError:
            policy_rate = None
        return declaration.outcome(AgentStatus.OK, message=_MIX_NOTE, data={
            "disclosed": [{"id": item.get("id"), "name": item.get("name"),
                           "rate_min": item.get("rate_min"), "rate_max": item.get("rate_max"),
                           "rate_avg": item.get("rate_avg"),
                           "loan_limit": item.get("loan_limit"),
                           "official_url": item.get("official_url")} for item in usable],
            "policy_rate_percent": policy_rate,
            "mix_simulated": False,
        })

    # ── 서브 4 · 정부·지자체 지원정책 ──────────────────────────────────
    def _subsidy(self) -> AgentOutcome:
        declaration = spec("finance.subsidy")
        # 공고 목록은 실제로 있다. 없는 것은 "얼마를 지원하는가"의 구조화 필드뿐이다.
        # 그래서 목록은 그대로 전달하고 상향분만 0 으로 못박는다.
        return declaration.outcome(
            AgentStatus.INTEGRATION_PENDING, message=_SUBSIDY_PENDING,
            data={"notice_count": len(self.programs), "uplift_krw": 0,
                  "notices": [{"id": item.get("id"), "title": item.get("title"),
                               "organization": item.get("organization"),
                               "official_url": item.get("official_url")}
                              for item in self.programs]},
            required_actions=["공고 원천에서 지원 규모를 구조화 필드로 수집해야 조달선에 반영할 수 있습니다."],
        )
