"""얼마 — 금융처방 팀.

제안서 04장의 되먹임 방향에서 이 팀이 **선행**한다. 조달 상한을 모르는 상태에서는 감당 불가한
후보를 걸러낼 기준이 없으므로, 이 팀이 기준선을 만들고 입지팀이 그 선을 넘을 수 있는지 증명한다.
그래서 팀 계약이 `blocking=True` 다 — 밴드를 못 그리면 후속 전체가 중단된다.

네 서브에이전트 중 **밴드 산출만이 계산을 한다.** 스트레스는 같은 산출물을 읽고, 지원정책과
KB 상품은 조회한 값을 인용만 한다. 가드 1(숫자는 도구 결과만)을 지키는 가장 단순한 방법은
계산 지점을 하나로 모으는 것이다.

── 이 팀에서 LLM 이 하는 일과 하지 않는 일 ──────────────────────────────────

finance.band 는 **이상치를 지목하고 유보 여부를 판단**한다. 모델이 고를 수 있는 이상치는
`ANOMALY_PREDICATES` 에 열거된 것뿐이고, 고른 뒤에도 코드가 술어를 직접 확인한다. 확인되지
않은 지목은 `rejected` 로 기록만 되고 판정에 쓰이지 않는다. 유보 사유 문장도 코드가 가진
고정 문장이다 — 모델 문장을 실으면 그 문장이 곧 근거가 되어 버린다.

**모델이 업종 프로필을 고르지는 않는다.** 등록된 프로필 중 "비슷한 것"을 붙이는 것이 곧
유사 매칭이고, 제안서 06장 JUDGEMENT 01 이 전면 금지한 바로 그 동작이다("스터디카페"를
"커피-음료"에 붙이면 전혀 다른 업종의 원가율로 손익분기를 계산하게 된다). 업종 프로필은
정확 일치로만 붙고, 없으면 등록 대기다.

finance.stress 는 `STRESS_SCENARIOS` 에서 이 케이스에 유의미한 것을 고른다. 계산은 고른
시나리오마다 `compute_bands` 를 파라미터만 갈아 끼워 다시 부르는 것이고, 기준 시나리오
결과는 모델이 무엇을 고르든 그대로 남는다 — 권장 조달선의 정의 자체가 그 통과이기 때문이다.

finance.kb_products · finance.subsidy 는 **id 만 고른다.** 공시의 한도·가입방법과 공고 본문이
문장이라 구조화 비교가 안 되므로 읽는 일은 모델이 하되, 결과로 나가는 행은 원천의 값 그대로다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..funding import ScenarioParams, compute_bands
from ..models import Provenance
from .contracts import AgentOutcome, AgentStatus, TeamReport
from .llm import AgentLLM, ChoiceSchema, Decision, Pick
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


# ── 이상치 카탈로그. 술어는 코드가 갖는다 ──────────────────────────────────

def _deposit_exceeds_equity(conditions: dict[str, Any], computed: dict[str, Any]) -> bool:
    deposit = conditions.get("deposit_krw")
    return deposit is not None and int(deposit) > int(conditions.get("equity_krw") or 0)


def _required_capital_out_of_range(conditions: dict[str, Any], computed: dict[str, Any]) -> bool:
    return computed.get("required_capital_band") == "OUT_OF_RANGE"


def _maximum_fails_stress(conditions: dict[str, Any], computed: dict[str, Any]) -> bool:
    return not next(line for line in computed["bands"] if line["band"] == "MAXIMUM")["stress_pass"]


def _no_borrowing_headroom(conditions: dict[str, Any], computed: dict[str, Any]) -> bool:
    lines = {line["band"]: line for line in computed["bands"]}
    return lines["MAXIMUM"]["ceiling_krw"] <= lines["EQUITY_ONLY"]["ceiling_krw"]


def _rent_without_deposit(conditions: dict[str, Any], computed: dict[str, Any]) -> bool:
    return bool(conditions.get("monthly_rent_krw")) and conditions.get("deposit_krw") in (None, 0)


#: 모델이 지목할 수 있는 이상치의 전부. 각 항목은 코드가 직접 확인할 수 있는 술어를 갖는다 —
#: 확인할 수 없는 이상치를 넣으면 그 순간 모델의 인상이 유보 근거가 된다.
ANOMALY_PREDICATES = {
    "DEPOSIT_EXCEEDS_EQUITY": _deposit_exceeds_equity,
    "REQUIRED_CAPITAL_OUT_OF_RANGE": _required_capital_out_of_range,
    "MAXIMUM_FAILS_STRESS": _maximum_fails_stress,
    "NO_BORROWING_HEADROOM": _no_borrowing_headroom,
    "RENT_WITHOUT_DEPOSIT": _rent_without_deposit,
}

#: 이 중에서만 판정을 멈출 수 있다.
#:
#: 나머지는 **화면이 그리도록 설계된 상태**다. 최대 조달선이 스트레스를 통과하지 못하는 것은
#: 정상이고 밴드 표가 '스트레스 실패'를 그 줄에 붙여 보여 주며, 필요자금이 최대 조달선을 넘는
#: 것도 `OUT_OF_RANGE` 로 표시하기로 한 상태다(제안서 12장). 그런 상태를 유보로 바꾸면 제품이
#: 보여 주기로 한 것을 모델의 그날 판단이 덮어쓰게 되고, 사용자는 아무 표도 못 본 채 멈춘다.
#: 그래서 모델이 유보를 골라도 여기 없는 이상치는 표시까지만 하고 판정을 계속한다.
WITHHOLDABLE = frozenset({"DEPOSIT_EXCEEDS_EQUITY", "RENT_WITHOUT_DEPOSIT"})

ANOMALY_MESSAGES = {
    "DEPOSIT_EXCEEDS_EQUITY": "희망 보증금이 자기자본을 넘어 조달 구조를 판정하지 않았습니다. 보증금이나 자기자본을 확인해 주세요.",
    "REQUIRED_CAPITAL_OUT_OF_RANGE": "필요자금이 최대 조달선을 넘어 조달 구조를 판정하지 않았습니다. 조건을 줄이거나 자기자본을 확인해 주세요.",
    "MAXIMUM_FAILS_STRESS": "최대 조달선이 스트레스 기준을 통과하지 못해 조달 구조를 판정하지 않았습니다.",
    "NO_BORROWING_HEADROOM": "기존 부채로 차입 여지가 남지 않아 조달 구조를 판정하지 않았습니다.",
    "RENT_WITHOUT_DEPOSIT": "월세는 있는데 보증금이 없어 입력을 확인하기 전에는 판정하지 않았습니다.",
}

BAND_REVIEW_SCHEMA = ChoiceSchema(
    name="review_band_inputs",
    description="조달 밴드 입력에서 확인이 필요한 이상치를 지목하고, 판정을 유보할지 정한다.",
    fields={"anomalies": Pick(tuple(ANOMALY_PREDICATES), multi=True,
                              description="입력에서 실제로 관찰되는 이상치만"),
            "verdict": Pick(("proceed", "withhold"),
                            description="withhold 는 확인 전에는 밴드를 제시하지 않겠다는 뜻이다")})

#: 스트레스 시나리오 카탈로그. 제안서 03장의 매출 −20% / −30% / 금리 +1%p 다.
#: `overrides` 는 제도 파라미터를 갈아 끼우는 값이고, `rate_delta_pp` 는 등록된 공시 금리에
#: 더할 값이다. 모두 선언된 상수이며 모델이 만든 수치가 아니다.
STRESS_SCENARIOS: dict[str, dict[str, Any]] = {
    "REVENUE_DROP_20": {"label": "매출 −20%", "overrides": {"stress.revenue_drop_ratio": 0.2}},
    "REVENUE_DROP_30": {"label": "매출 −30%", "overrides": {"stress.revenue_drop_ratio": 0.3}},
    "RATE_PLUS_1PP": {"label": "금리 +1%p", "rate_delta_pp": 1.0},
}

STRESS_SCHEMA = ChoiceSchema(
    name="select_stress_scenarios",
    description="이 케이스에서 확인할 가치가 있는 시나리오를 고른다.",
    fields={"scenarios": Pick(tuple(STRESS_SCENARIOS), multi=True,
                              description="카탈로그에 있는 시나리오만")})


class FinanceTeam:
    """조회 결과를 생성자로 받는다. 이 클래스는 네트워크를 모른다 — 그래야 팀 계약만 테스트된다."""

    team = "finance"
    name = "금융처방 팀"

    def __init__(self, params, *, kb_products: list[dict[str, Any]],
                 programs: list[dict[str, Any]], llm: AgentLLM | None = None):
        self.params = params
        self.kb_products = kb_products
        self.programs = programs
        self.llm = llm

    def run(self, conditions: dict[str, Any],
            decisions: dict[str, Decision] | None = None) -> TeamReport:
        chosen = decisions or {}
        band, computed = self._band(conditions, chosen.get("finance.band"))
        outcomes = [band,
                    self._stress(band, computed, chosen.get("finance.stress"), conditions),
                    self._kb_products(chosen.get("finance.kb_products")),
                    self._subsidy(chosen.get("finance.subsidy"))]
        return FinanceReport(team=self.team, name=self.name, outcomes=outcomes, blocking=True,
                             message=None if band.active else band.message)

    async def arun(self, conditions: dict[str, Any]) -> TeamReport:
        return self.run(conditions, await self.decide(conditions))

    async def decide(self, conditions: dict[str, Any]) -> dict[str, Decision]:
        """네 에이전트의 선택을 모은다. 원천이 없는 에이전트는 모델을 부르지 않는다(가드 3)."""
        if self.llm is None:
            return {}
        return {"finance.band": await self._review_band(conditions),
                "finance.stress": await self._select_scenarios(conditions),
                "finance.kb_products": await self._select_products(),
                "finance.subsidy": await self._select_notices(conditions)}

    # ── 서브 1 · 조달 밴드 산출 ────────────────────────────────────────
    def _band(self, conditions: dict[str, Any],
              review: Decision | None) -> tuple[AgentOutcome, dict[str, Any] | None]:
        declaration = spec("finance.band")
        industry = conditions["industry"]
        missing = self.params.missing(industry)
        if missing:
            return declaration.outcome(
                AgentStatus.INTEGRATION_PENDING, message=_BAND_PENDING,
                data={"missing_params": missing},
                required_actions=[f"{name} 을(를) 출처와 함께 등록해 주세요." for name in missing],
            ), None
        inputs = self._inputs(conditions)
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

        review = review or Decision.deterministic("finance.band", schema=BAND_REVIEW_SCHEMA.name)
        confirmed, rejected = self._confirm_anomalies(review, conditions, computed)
        audit = {**review.as_data(),
                 "rejected": review.rejected + rejected}
        # 유보는 확인된 이상치 중 **유보 가능한 것**이 있을 때만 성립한다. 화면이 그리기로 한
        # 상태는 표시만 하고 지나간다 — 그렇지 않으면 모델의 판단 하나가 밴드 표 전체를 지운다.
        blocking = [code for code in confirmed if code in WITHHOLDABLE]
        if blocking and review.chosen.get("verdict") == "withhold":
            # 유보해도 수치를 내지 않을 뿐, 이 판단이 후보를 떨어뜨리는 근거가 되지는 않는다 —
            # 밴드가 없으면 실행 전체가 조건 확인으로 되돌아간다(팀 계약).
            return declaration.outcome(
                AgentStatus.WITHHELD, message=ANOMALY_MESSAGES[blocking[0]],
                data={"anomalies": confirmed, "decision": audit},
                required_actions=[ANOMALY_MESSAGES[code] for code in blocking],
            ), None
        return declaration.outcome(
            AgentStatus.OK, data={**computed, "anomalies": confirmed, "decision": audit},
            provenance=self._provenance(industry),
        ), computed

    @staticmethod
    def _inputs(conditions: dict[str, Any]) -> dict[str, Any]:
        return {name: conditions.get(name, fallback) for name, fallback in _BAND_FIELDS}

    @staticmethod
    def _confirm_anomalies(review: Decision, conditions: dict[str, Any],
                           computed: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
        """모델이 지목한 이상치를 코드가 다시 확인한다. 확인되지 않은 것은 기록만 남는다."""
        confirmed, rejected = [], []
        for code in review.chosen.get("anomalies", []):
            predicate = ANOMALY_PREDICATES.get(code)
            if predicate is not None and predicate(conditions, computed):
                confirmed.append(code)
            else:
                rejected.append({"field": "anomalies", "value": code, "reason": "predicate_false"})
        return confirmed, rejected

    async def _review_band(self, conditions: dict[str, Any]) -> Decision:
        industry = conditions.get("industry", "")
        if self.params.missing(industry):
            # 원천이 없으면 판정 자체를 하지 않으므로 물어볼 것도 없다.
            return Decision.deterministic("finance.band", schema=BAND_REVIEW_SCHEMA.name)
        try:
            computed = compute_bands(self.params, **self._inputs(conditions))
        except ValueError:
            return Decision.deterministic("finance.band", schema=BAND_REVIEW_SCHEMA.name)
        lines = {line["band"]: line for line in computed["bands"]}
        return await self.llm.choose(
            agent_key="finance.band", schema=BAND_REVIEW_SCHEMA,
            instruction=("입력과 산출을 보고 확인이 필요한 이상치만 지목하세요. "
                         "관찰되지 않는 이상치를 고르면 버려집니다. 수치를 다시 계산하지 마세요."),
            context={"입력": {key: conditions.get(key) for key, _ in _BAND_FIELDS},
                     "필요자금 위치": computed.get("required_capital_band"),
                     "밴드": {name: {"ceiling_krw": line["ceiling_krw"],
                                   "stress_pass": line["stress_pass"]}
                            for name, line in lines.items()}})

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
    def _stress(self, band: AgentOutcome, computed: dict[str, Any] | None,
                selection: Decision | None, conditions: dict[str, Any]) -> AgentOutcome:
        declaration = spec("finance.stress")
        if computed is None:
            # 밴드가 못 나온 이유를 그대로 물려받는다. 여기서 따로 진단하지 않는다.
            return declaration.outcome(band.status, message=band.message)
        selection = selection or Decision.deterministic("finance.stress", schema=STRESS_SCHEMA.name)
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
            "scenarios": self._scenarios(self._inputs(conditions), selection),
            "decision": selection.as_data(),
        })

    def _scenarios(self, inputs: dict[str, Any], selection: Decision) -> list[dict[str, Any]]:
        """고른 시나리오마다 같은 산식을 파라미터만 갈아 끼워 다시 돌린다."""
        rows = []
        for key in selection.chosen.get("scenarios", []):
            scenario = STRESS_SCENARIOS[key]
            overrides = dict(scenario.get("overrides") or {})
            if "rate_delta_pp" in scenario:
                overrides["loan.annual_rate_percent"] = (
                    self.params.value("loan.annual_rate_percent") + scenario["rate_delta_pp"])
            try:
                computed = compute_bands(ScenarioParams(self.params, overrides), **inputs)
            except (ValueError, KeyError):
                continue
            lines = {line["band"]: line for line in computed["bands"]}
            rows.append({"key": key, "label": scenario["label"],
                         "recommended_ceiling_krw": lines["RECOMMENDED"]["ceiling_krw"],
                         "recommended_passes_stress": lines["RECOMMENDED"]["stress_pass"],
                         "maximum_passes_stress": lines["MAXIMUM"]["stress_pass"],
                         "target_daily_revenue_krw": lines["RECOMMENDED"]["target_daily_revenue_krw"],
                         "runway_months": lines["RECOMMENDED"]["runway_months"]})
        return rows

    async def _select_scenarios(self, conditions: dict[str, Any]) -> Decision:
        if self.params.missing(conditions.get("industry", "")):
            return Decision.deterministic("finance.stress", schema=STRESS_SCHEMA.name)
        return await self.llm.choose(
            agent_key="finance.stress", schema=STRESS_SCHEMA,
            instruction="이 케이스에서 확인할 가치가 있는 시나리오만 고르세요. 결과는 코드가 계산합니다.",
            context={"업종": conditions.get("industry"),
                     "월세": conditions.get("monthly_rent_krw"),
                     "기존부채": conditions.get("existing_debt_krw"),
                     "자기자본": conditions.get("equity_krw"),
                     "고를 수 있는 시나리오": {key: item["label"]
                                      for key, item in STRESS_SCENARIOS.items()}})

    # ── 서브 3 · KB 상품 조합 ─────────────────────────────────────────
    def _kb_products(self, selection: Decision | None) -> AgentOutcome:
        declaration = spec("finance.kb_products")
        usable = [item for item in self.kb_products
                  if item.get("category") in STARTUP_FUNDING_CATEGORIES]
        if not usable:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=_KB_PENDING,
                                       data={"disclosed": [], "mix_simulated": False})
        selection = selection or Decision.deterministic("finance.kb_products",
                                                        schema="select_kb_products")
        picked = [str(item) for item in selection.chosen.get("selected", [])]
        narrowed = [item for item in usable if str(item.get("id")) in picked] or usable
        try:
            policy_rate = self.params.value("loan.annual_rate_percent")
        except KeyError:
            policy_rate = None
        return declaration.outcome(AgentStatus.OK, message=_MIX_NOTE, data={
            "disclosed": [{"id": item.get("id"), "name": item.get("name"),
                           "rate_min": item.get("rate_min"), "rate_max": item.get("rate_max"),
                           "rate_avg": item.get("rate_avg"),
                           "loan_limit": item.get("loan_limit"),
                           "official_url": item.get("official_url")} for item in narrowed],
            "policy_rate_percent": policy_rate,
            "mix_simulated": False,
            "decision": selection.as_data(),
        })

    async def _select_products(self) -> Decision:
        usable = [item for item in self.kb_products
                  if item.get("category") in STARTUP_FUNDING_CATEGORIES]
        if not usable:
            # 인덱스가 비어 있으면 고를 것이 없다. 원천 없이 부르지 않는다(가드 3).
            return Decision.deterministic("finance.kb_products", schema="select_kb_products")
        schema = ChoiceSchema(
            name="select_kb_products",
            description="창업 자금 조달에 관련된 공시 상품만 고른다.",
            fields={"selected": Pick(tuple(str(item.get("id")) for item in usable), multi=True,
                                     description="공시 목록에 있는 id 만")})
        return await self.llm.choose(
            agent_key="finance.kb_products", schema=schema,
            instruction=("한도·가입방법 문구를 읽고 창업 자금 조달에 쓸 수 있는 상품만 고르세요. "
                         "금리를 비교해 순위를 매기지 말고, 한도를 수치로 바꾸지 마세요."),
            context={"공시": [{"id": item.get("id"), "name": item.get("name"),
                             "loan_limit": item.get("loan_limit"),
                             "join_way": item.get("join_way")} for item in usable]})

    # ── 서브 4 · 정부·지자체 지원정책 ──────────────────────────────────
    def _subsidy(self, selection: Decision | None) -> AgentOutcome:
        declaration = spec("finance.subsidy")
        selection = selection or Decision.deterministic("finance.subsidy",
                                                        schema="select_subsidy_notices")
        relevant = {str(item) for item in selection.chosen.get("relevant", [])}
        # 공고 목록은 실제로 있다. 없는 것은 "얼마를 지원하는가"의 구조화 필드뿐이다.
        # 그래서 목록은 그대로 전달하고 상향분만 0 으로 못박는다.
        return declaration.outcome(
            AgentStatus.INTEGRATION_PENDING, message=_SUBSIDY_PENDING,
            data={"notice_count": len(self.programs), "uplift_krw": 0,
                  "decision": selection.as_data(),
                  "notices": [{"id": item.get("id"), "title": item.get("title"),
                               "organization": item.get("organization"),
                               "relevant": str(item.get("id")) in relevant,
                               "official_url": item.get("official_url")}
                              for item in self.programs]},
            required_actions=["공고 원천에서 지원 규모를 구조화 필드로 수집해야 조달선에 반영할 수 있습니다."],
        )

    async def _select_notices(self, conditions: dict[str, Any]) -> Decision:
        if not self.programs:
            return Decision.deterministic("finance.subsidy", schema="select_subsidy_notices")
        schema = ChoiceSchema(
            name="select_subsidy_notices",
            description="조건과 겹치는 공고만 고른다. 자격 판정이 아니다.",
            fields={"relevant": Pick(tuple(str(item.get("id")) for item in self.programs),
                                     multi=True, description="목록에 있는 공고 id 만")})
        return await self.llm.choose(
            agent_key="finance.subsidy", schema=schema,
            instruction=("공고 본문에서 지원 지역·대상이 이 조건과 겹치는 것만 고르세요. "
                         "자격을 판정하지 말고, 지원 금액을 본문에서 읽어 내지 마세요."),
            context={"조건": {"업종": conditions.get("industry"), "자치구": conditions.get("district")},
                     "공고": [{"id": item.get("id"), "title": item.get("title"),
                             "organization": item.get("organization"),
                             "regions": item.get("regions"),
                             # 본문은 길 수 있다. 지역·대상 표기는 앞부분에 오므로 잘라 보낸다.
                             "match_text": (item.get("match_text") or "")[:600]}
                            for item in self.programs]})
