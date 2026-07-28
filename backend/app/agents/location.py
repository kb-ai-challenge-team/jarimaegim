"""어디 — 입지추천 팀.

금융처방 팀이 만든 기준선 안에서 후보를 판정한다. 팀 계약상 **후속을 막지 않는다**:
축 하나가 죽어도 나머지 축으로 계속 가고, 죽은 축은 탈락 근거로 쓰이지 않는다.

`trade_area` 어댑터로 상권 프로파일을 받는다. 없으면 세 축이 스스로 `integration_pending` 을
선언하고, 그 상태에서 후보는 **전원 잔존한다**. 데이터가 없다는 사실이 "이 자리는 나쁘다"로
둔갑하지 않게 하는 것이 이 파일에서 가장 중요한 성질이다.

생존시기 축은 유일한 A등급 경로이고 인허가 이력 코호트를 요구한다. 코호트가 없는 동안
상권 집계로 대신 채우지 않는다 — 상권 폐업률은 '상권 안 동종 점포 중 이번 분기에 폐업한 비율'
이지 '이 매물이 폐업할 확률'이 아니며, 후자를 말하는 순간 B등급 데이터로 A등급 주장을 하게 된다.

── 상권 어댑터 계약 ───────────────────────────────────────────────────────

필수:  `available: bool` · `profile(joiner, industry) -> dict | None`
선택:  `keyed_by: str` — 후보의 어느 필드로 결합하는가. 기본은 `admin_dong` 이고, 실제 상권
         원천은 `admin_dong_code` 를 선언한다. 선언한 필드가 비어 있는 후보는 조회하지 않는다.
       `reason_for(axis) -> str | None` — "이 축은 판정할 수 없다"는 선언과 그 사유.
         사유가 있으면 그 축은 `integration_pending` 이 되고 모델도 부르지 않는다.
       `industry_options(industry) -> [{code, name}]`  — 동종 범위 후보. 없으면 범위 판단을
         하지 않고 정확 일치로만 본다(유사 매칭을 이 팀이 만들어 내지 않는다).
       `profile_for_scope(joiner, codes) -> dict | None` — 고른 범위로 다시 집계.
         없으면 범위는 고르되 적용되지 않았음을 `scope_applied: False` 로 밝힌다.

프로파일이 `signals: {축: {score_band, direction, label, explanation}}` 을 담고 있으면 그것이
결론이다. 이 팀은 **다시 등급을 매기지 않는다** — 원천은 중앙값 대비 비교와 표본 보정을 이미
끝내고 판정을 주므로, 원시 비율을 받아 여기서 재판정하면 그 보정이 사라진다. `signals` 가 없는
어댑터에 한해 숫자 지수(`demand_index` 등)를 이 파일의 기준으로 등급화한다.

선택 계약이 없을 때 **추정으로 메우지 않는다**는 것이 이 설계의 요점이다. 원천이 못 주는
것을 팀이 만들어 내면 그 값은 출처가 없다.

── 이 팀에서 LLM 이 하는 일 ────────────────────────────────────────────────

demand       수요를 어느 인구로 볼 것인가(유동 / 상주 / 직장). 프로파일이 그 인구를 담고 있지
             않으면 종합 지수로 되돌아가고, 그 사실을 `basis` 로 밝힌다.
competition  동종의 범위. "카페"가 커피전문점만인지 제과점까지인지는 데이터가 답하지 않는다.
             단, 원천이 제시한 코드 중에서만 고를 수 있다.
viability    목표매출을 대입할 업종 세분류.
survival     인허가 코드 ↔ 상권분석 코드 매핑을 **제안만** 한다. 확정은 `survival_mapping` 의
             대조 결과가 하고, 확인되지 않은 쌍이 하나라도 있으면 축은 켜지지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .contracts import AgentOutcome, AgentStatus, TeamReport
from .llm import AgentLLM, ChoiceSchema, Decision, Flag, Pick, Records
from .registry import spec
from .survival_mapping import VerificationTable

#: 서울 중앙값 대비 어느 비율부터 높다/낮다로 부를지. 데이터가 아니라 선언한 분류 기준이다.
HIGH_RATIO = 1.2
LOW_RATIO = 0.8

#: 목표매출이 상권 동종 분포에서 이 분위를 넘으면 "그 상권 상위 10%만큼 팔아야 성립"이라는 뜻이다.
#: 제안서 04장의 하드 탈락 규칙 — 분기점 미달.
TOP_DECILE = 0.9

#: 수요를 읽을 수 있는 인구. 프로파일의 `demand_by_basis` 키와 같은 이름이어야 한다.
DEMAND_BASES = ("FLOATING", "RESIDENT", "WORKING")

_TRADE_AREA_PENDING = ("서울시 상권분석 프로파일이 없어 이 축을 판정하지 않았습니다. "
                       "판정하지 않은 축은 후보 탈락 근거로 쓰이지 않습니다.")
_SURVIVAL_PENDING = ("행정안전부 인허가 이력 코호트가 구축되지 않아 영업유지율을 판정하지 않았습니다. "
                     "상권 집계로 개별 점포의 생존을 대신 말하지 않습니다.")
_ADJACENT_PENDING = ("행정동 경계 인접 관계 원천이 없어 인접 동까지 넓히지 않았습니다. "
                     "경계에 걸친 후보라도 추정으로 넓히지 않습니다.")

DEMAND_SCHEMA = ChoiceSchema(
    name="select_demand_basis",
    description="이 업종의 수요를 어느 인구로 볼지 고른다.",
    fields={"basis": Pick(DEMAND_BASES, description="유동 / 상주 / 직장 인구"),
            "widen_to_adjacent": Flag(description="후보가 동 경계에 있어 인접 동까지 봐야 하는가")})

SURVIVAL_SCHEMA_NAME = "propose_survival_mapping"


@dataclass(frozen=True)
class LocationReport(TeamReport):
    """팀 보고 + 축소 결과. 탈락은 언제나 사유와 함께 나간다."""

    surviving: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)


def _band_of(value: float) -> str:
    if value >= HIGH_RATIO:
        return "HIGH"
    return "LOW" if value <= LOW_RATIO else "MID"


def _optional(source: Any, name: str):
    """어댑터의 선택 계약을 읽는다. 없으면 None — 없는 계약을 흉내 내지 않는다.

    존재 확인은 `getattr` 뿐이다. 시험 삼아 호출해 보는 방식은 원천에 실제 조회를 한 번 더
    거는 셈이라 쓰지 않는다."""
    return getattr(source, name, None)


class LocationTeam:
    team = "location"
    name = "입지추천 팀"

    def __init__(self, *, trade_area: Any | None = None,
                 stress_check: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
                 llm: AgentLLM | None = None,
                 survival_table: VerificationTable | None = None,
                 licence_codes: list[str] | None = None):
        self.trade_area = trade_area
        self.stress_check = stress_check
        self.llm = llm
        self.survival_table = survival_table or VerificationTable()
        self.licence_codes = licence_codes or []

    @property
    def profiles_available(self) -> bool:
        return bool(self.trade_area is not None and getattr(self.trade_area, "available", False))

    def run(self, candidates: list[dict[str, Any]], conditions: dict[str, Any],
            decisions: dict[str, Decision] | None = None) -> LocationReport:
        chosen = decisions or {}
        industry = conditions.get("industry", "")
        profiles = self._profiles(candidates, industry)
        demand = chosen.get("location.demand") or Decision.deterministic(
            "location.demand", schema=DEMAND_SCHEMA.name)
        competition = chosen.get("location.competition") or Decision.deterministic(
            "location.competition", schema="select_competing_scope")
        viability = chosen.get("location.viability") or Decision.deterministic(
            "location.viability", schema="select_revenue_industry")
        outcomes = [
            self._demand(profiles, demand),
            # 경쟁은 방향이 반대다 — 지수가 높을수록 불리하므로 등급을 뒤집는다.
            self._scoped_axis("location.competition", candidates, profiles, competition,
                              "competition_index", "codes",
                              lambda value: {"HIGH": "LOW", "LOW": "HIGH"}.get(_band_of(value), "MID")),
            self._viability(candidates, profiles, viability),
            self._survival(chosen.get("location.survival")),
        ]
        surviving, dropped = self._narrow(candidates, profiles, outcomes)
        return LocationReport(team=self.team, name=self.name, outcomes=outcomes, blocking=False,
                              surviving=surviving, dropped=dropped)

    async def arun(self, candidates: list[dict[str, Any]],
                   conditions: dict[str, Any]) -> LocationReport:
        return self.run(candidates, conditions, await self.decide(candidates, conditions))

    async def decide(self, candidates: list[dict[str, Any]],
                     conditions: dict[str, Any]) -> dict[str, Decision]:
        """원천이 없으면 어떤 축도 모델을 부르지 않는다(가드 3). 축이 꺼진 이유는 원천이지 모델이 아니다."""
        if self.llm is None or not self.profiles_available:
            return {}
        industry = conditions.get("industry", "")
        options = self._industry_options(industry)
        return {"location.demand": await self._select_basis(candidates, conditions),
                "location.competition": await self._select_scope(industry, options),
                "location.viability": await self._select_revenue_industry(industry, options),
                "location.survival": await self._propose_mapping(industry, options)}

    def _judged(self, profile: dict[str, Any], axis: str) -> dict[str, Any] | None:
        """원천이 이미 내린 판정. 있으면 그것이 결론이고, 이 팀은 다시 등급을 매기지 않는다.

        원천은 서울 동종 중앙값 대비 비교와 표본 보정을 이미 끝내고 판정을 준다. 여기서 원시
        비율을 받아 다시 등급을 매기면 그 보정이 사라진다 — 점포 6곳짜리 행정동이 '중앙값의
        617%'로 1순위를 차지하던 문제가 정확히 그것이다(제안서 06장 JUDGEMENT 02)."""
        signals = profile.get("signals")
        return signals.get(axis) if isinstance(signals, dict) else None

    def _pending_reason(self, axis: str) -> str | None:
        """원천이 "이 축은 판정할 수 없다"고 선언했는가. 선언하지 않았으면 None."""
        declare = getattr(self.trade_area, "reason_for", None)
        return declare(axis) if callable(declare) else None

    def _industry_options(self, industry: str) -> list[dict[str, Any]]:
        reader = _optional(self.trade_area, "industry_options")
        if reader is None:
            return []
        try:
            return list(reader(industry) or [])
        except Exception:  # noqa: BLE001 — 원천 조회 실패는 "범위를 못 넓혔다"로 끝난다
            return []

    def _profiles(self, candidates: list[dict[str, Any]],
                  industry: str) -> dict[str, dict[str, Any]]:
        """판정할 수 있는 후보만 담는다. 프로파일이 없는 후보는 여기 들어오지 않는다."""
        if not self.profiles_available:
            return {}
        # 어댑터가 어떤 키로 결합하는지는 어댑터가 선언한다. 실제 상권 원천은 행정동 **코드**로
        # 결합하고, 코드가 없는 후보는 조회하지 않는다 — 이름으로 대신 맞추면 코드 결합의
        # 정확성이 조용히 사라지고, 같은 이름의 다른 행정동 통계가 붙을 수 있다.
        key = getattr(self.trade_area, "keyed_by", "admin_dong")
        found: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            joiner = candidate.get(key)
            if not joiner:
                continue
            profile = self.trade_area.profile(joiner, industry)
            if profile:
                found[candidate["id"]] = profile
        return found

    # ── 수요 ───────────────────────────────────────────────────────────
    def _demand(self, profiles: dict[str, dict[str, Any]], decision: Decision) -> AgentOutcome:
        declaration = spec("location.demand")
        if not self.profiles_available:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=_TRADE_AREA_PENDING)
        reason = self._pending_reason("demand")
        if reason:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=reason)
        basis = decision.chosen.get("basis")
        by_candidate: dict[str, Any] = {}
        applied = "COMPOSITE"
        for candidate_id, profile in profiles.items():
            judged = self._judged(profile, "demand")
            if judged is not None:
                by_candidate[candidate_id] = {**judged, "sample_n": profile.get("sample_n"),
                                              "evidence_grade": declaration.evidence_grade,
                                              "quarter": profile.get("quarter")}
                continue
            value = self._demand_value(profile, basis)
            if value is None:
                continue
            applied = value[1]
            by_candidate[candidate_id] = {
                "value": value[0], "band": _band_of(value[0]),
                "evidence_grade": declaration.evidence_grade, "basis": value[1],
                "quarter": profile.get("quarter")}
        widen = bool(decision.chosen.get("widen_to_adjacent"))
        return declaration.outcome(
            AgentStatus.OK,
            data={"by_candidate": by_candidate, "basis": applied, "widened": False,
                  "decision": decision.as_data()},
            required_actions=[_ADJACENT_PENDING] if widen else [])

    @staticmethod
    def _demand_value(profile: dict[str, Any], basis: str | None) -> tuple[float, str] | None:
        """고른 인구가 프로파일에 있으면 그것을, 없으면 종합 지수를 읽는다. 없는 값을 만들지 않는다."""
        by_basis = profile.get("demand_by_basis") or {}
        if basis and isinstance(by_basis.get(basis), (int, float)):
            return float(by_basis[basis]), basis
        composite = profile.get("demand_index")
        if isinstance(composite, (int, float)):
            return float(composite), "COMPOSITE"
        return None

    # ── 경쟁 · 범위를 고를 수 있는 축 ────────────────────────────────────
    def _scoped_axis(self, key: str, candidates: list[dict[str, Any]],
                     profiles: dict[str, dict[str, Any]], decision: Decision,
                     field_name: str, choice_field: str,
                     grade_of: Callable[[float], str]) -> AgentOutcome:
        declaration = spec(key)
        if not self.profiles_available:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=_TRADE_AREA_PENDING)
        axis = key.split(".", 1)[1]
        reason = self._pending_reason(axis)
        if reason:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=reason)
        scope = decision.chosen.get(choice_field) or []
        scope = [scope] if isinstance(scope, str) else list(scope)
        scoped, applied = self._scoped_profiles(candidates, scope)
        readings = scoped if applied else profiles
        by_candidate = {}
        for candidate_id, profile in readings.items():
            judged = self._judged(profile, axis)
            if judged is not None:
                # 원천이 이미 방향까지 반영해 판정했다. 여기서 또 뒤집으면 불리한 상권이 유리해진다.
                by_candidate[candidate_id] = {**judged, "sample_n": profile.get("sample_n"),
                                              "evidence_grade": declaration.evidence_grade,
                                              "quarter": profile.get("quarter")}
                continue
            value = profile.get(field_name)
            if not isinstance(value, (int, float)):
                continue
            by_candidate[candidate_id] = {
                "value": float(value), "band": grade_of(float(value)),
                "evidence_grade": declaration.evidence_grade,
                "quarter": profile.get("quarter")}
        return declaration.outcome(AgentStatus.OK, data={
            "by_candidate": by_candidate, "scope": scope, "scope_applied": applied,
            "decision": decision.as_data()})

    def _scoped_profiles(self, candidates: list[dict[str, Any]],
                         scope: list[str]) -> tuple[dict[str, dict[str, Any]], bool]:
        """고른 범위로 다시 집계할 수 있으면 그렇게 한다. 못 하면 적용하지 않았다고 말한다."""
        reader = _optional(self.trade_area, "profile_for_scope")
        if not scope or reader is None:
            return {}, False
        found: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            try:
                profile = reader(candidate.get("admin_dong", ""), scope)
            except Exception:  # noqa: BLE001
                continue
            if profile:
                found[candidate["id"]] = profile
        return found, True

    # ── 달성 가능성 ────────────────────────────────────────────────────
    def _viability(self, candidates: list[dict[str, Any]], profiles: dict[str, dict[str, Any]],
                   decision: Decision) -> AgentOutcome:
        declaration = spec("location.viability")
        if not self.profiles_available:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=_TRADE_AREA_PENDING)
        # 후보를 떨어뜨릴 수 있는 유일한 축이다. 원천이 판정 기준을 줄 수 없다고 선언하면
        # 여기서 대신 만들어 내지 않는다 — 정의되지 않은 기준으로 후보가 사라지면 안 된다.
        reason = self._pending_reason("viability")
        if reason:
            return declaration.outcome(AgentStatus.INTEGRATION_PENDING, message=reason)
        code = decision.chosen.get("code")
        scoped, applied = self._scoped_profiles(candidates, [code] if code else [])
        readings = scoped if applied else profiles
        by_candidate = {}
        for candidate_id, profile in readings.items():
            percentile = profile.get("revenue_percentile")
            if not isinstance(percentile, (int, float)):
                continue
            by_candidate[candidate_id] = {
                "value": float(percentile),
                "band": "LOW" if float(percentile) > TOP_DECILE else _band_of(1.0 - float(percentile) + 0.5),
                "above_top_decile": float(percentile) > TOP_DECILE,
                "evidence_grade": declaration.evidence_grade,
                "quarter": profile.get("quarter")}
        return declaration.outcome(AgentStatus.OK, data={
            "by_candidate": by_candidate, "industry_code": code if applied else None,
            "decision": decision.as_data()})

    # ── 생존시기 · 제안과 확정을 분리한다 ────────────────────────────────
    def _survival(self, decision: Decision | None) -> AgentOutcome:
        declaration = spec("location.survival")
        decision = decision or Decision.deterministic("location.survival",
                                                       schema=SURVIVAL_SCHEMA_NAME)
        proposed = [(row.get("licence_code", ""), row.get("trade_area_code", ""))
                    for row in decision.chosen.get("pairs", [])]
        confirmed, rejected = self.survival_table.split(proposed)
        actions = ["행정안전부 지방행정 인허가데이터로 개업·폐업 코호트를 구축해야 합니다."]
        if rejected:
            actions.append("제안된 업종코드 매핑이 대조 결과에 없습니다. 두 코드 체계의 원문 대조를 먼저 등록해 주세요.")
        # 매핑이 확인되어도 축은 켜지지 않는다. 코호트가 없으면 A등급 주장이 성립하지 않고,
        # 상권 집계로 대신 채우면 그것이 곧 B등급 데이터로 A등급을 말하는 것이다.
        return declaration.outcome(
            AgentStatus.INTEGRATION_PENDING, message=_SURVIVAL_PENDING,
            data={"mapping_confirmed": bool(confirmed) and not rejected,
                  "confirmed_pairs": [list(pair) for pair in confirmed],
                  "rejected_pairs": [list(pair) for pair in rejected],
                  "decision": decision.as_data()},
            required_actions=actions)

    # ── 선택 요청 ──────────────────────────────────────────────────────
    async def _select_basis(self, candidates: list[dict[str, Any]],
                            conditions: dict[str, Any]) -> Decision:
        return await self.llm.choose(
            agent_key="location.demand", schema=DEMAND_SCHEMA,
            instruction=("이 업종의 손님이 어느 인구에서 오는지 고르세요. "
                         "인구 수를 추정하지 말고 기준만 고르면 됩니다."),
            context={"업종": conditions.get("industry"), "자치구": conditions.get("district"),
                     "후보 행정동": sorted({str(item.get("admin_dong") or "") for item in candidates})})

    async def _select_scope(self, industry: str, options: list[dict[str, Any]]) -> Decision:
        if not options:
            # 원천이 동종 범위 후보를 주지 않으면 범위 판단을 하지 않는다 — 유사 매칭 금지.
            return Decision.deterministic("location.competition", schema="select_competing_scope")
        schema = ChoiceSchema(
            name="select_competing_scope",
            description="이 업종과 실제로 손님을 나눠 갖는 업종의 범위를 고른다.",
            fields={"codes": Pick(tuple(str(item["code"]) for item in options), multi=True,
                                  description="원천이 제시한 코드만")})
        return await self.llm.choose(
            agent_key="location.competition", schema=schema,
            instruction="같은 손님을 두고 경쟁하는 업종만 고르세요. 목록에 없는 업종을 만들지 마세요.",
            context={"기준 업종": industry, "고를 수 있는 업종": options})

    async def _select_revenue_industry(self, industry: str,
                                       options: list[dict[str, Any]]) -> Decision:
        if not options:
            return Decision.deterministic("location.viability", schema="select_revenue_industry")
        schema = ChoiceSchema(
            name="select_revenue_industry",
            description="목표매출을 어느 업종 세분류의 분포에 대입할지 고른다.",
            fields={"code": Pick(tuple(str(item["code"]) for item in options),
                                 description="원천이 제시한 코드 하나")})
        return await self.llm.choose(
            agent_key="location.viability", schema=schema,
            instruction="이 사업의 매출이 어느 업종 분포에 속하는지 하나만 고르세요.",
            context={"기준 업종": industry, "고를 수 있는 업종": options})

    async def _propose_mapping(self, industry: str, options: list[dict[str, Any]]) -> Decision:
        if not self.licence_codes or not options:
            return Decision.deterministic("location.survival", schema=SURVIVAL_SCHEMA_NAME)
        schema = ChoiceSchema(
            name=SURVIVAL_SCHEMA_NAME,
            description="인허가 업종코드와 상권분석 업종코드의 대응 후보를 제안한다. 확정이 아니다.",
            fields={"pairs": Records(
                description="대응한다고 볼 만한 쌍만. 확신이 없으면 비워 두세요.",
                fields={"licence_code": Pick(tuple(self.licence_codes)),
                        "trade_area_code": Pick(tuple(str(item["code"]) for item in options))})})
        return await self.llm.choose(
            agent_key="location.survival", schema=schema,
            instruction=("두 코드 체계에서 같은 업종을 가리키는 쌍을 제안하세요. "
                         "제안은 대조 결과와 다시 맞춰 보며, 확인되지 않은 쌍은 사용되지 않습니다."),
            context={"기준 업종": industry, "인허가 업종코드": self.licence_codes,
                     "상권분석 업종": options})

    # ── 축소 ───────────────────────────────────────────────────────────
    def _narrow(self, candidates: list[dict[str, Any]], profiles: dict[str, dict[str, Any]],
                outcomes: list[AgentOutcome]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """사유가 있는 것만 탈락시킨다. 개수는 고정하지 않는다.

        판정하지 못한 축(`active` 가 아닌 것)은 이 함수가 아예 읽지 않는다."""
        viability = next(item for item in outcomes if item.key == "location.viability")
        viable = viability.data.get("by_candidate", {}) if viability.active else {}

        surviving, dropped = [], []
        for candidate in candidates:
            reason = self._hard_drop_reason(candidate, viable.get(candidate["id"]))
            if reason:
                dropped.append({**candidate, "reason": reason})
            else:
                surviving.append(candidate)
        return surviving, dropped

    def _hard_drop_reason(self, candidate: dict[str, Any],
                          viability: dict[str, Any] | None) -> str | None:
        if viability and viability.get("above_top_decile"):
            return ("목표매출이 상권 동종 상위 10% 경계를 넘어 분기점 미달입니다 "
                    f"(분포 위치 {viability['value']:.0%}).")
        if self.stress_check is not None:
            verdict = self.stress_check(candidate)
            if verdict is not None and not verdict.get("passes", True):
                months = verdict.get("runway_months")
                tail = f" ({months}개월 내 소진)" if months is not None else ""
                return f"매출 −20% 스트레스에서 현금이 버티지 못합니다{tail}."
        return None
