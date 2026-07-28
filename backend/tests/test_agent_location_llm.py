"""입지추천 팀의 추론.

  location.demand       수요의 기준 인구를 고른다 (유동 / 상주 / 직장)
  location.competition  동종 업종의 범위를 판단한다 (카페 = 커피전문점만? 디저트 포함?)
  location.viability    목표매출을 대입할 업종 세분류를 고른다
  location.survival     인허가 업종코드 ↔ 상권분석 업종분류 매핑을 **제안만** 한다

이 파일에서 가장 중요한 두 가지:

  ① 판정하지 못한 축은 후보를 떨어뜨리지 않는다. 모델이 붙어도 이 성질은 그대로다.
  ② location.survival 은 모델이 매핑을 확정하지 못한다. 제안서 15장이 "가장 위험"으로 지목한
     것이 업종코드 매핑 오류이고, 그 오류는 화면에 오류로 나타나지 않고 그럴듯한 생존율로
     나타난다. 그래서 제안은 검증 테이블과 대조되고, 불일치하면 축이 꺼진다.
"""
from app.agents.contracts import AgentStatus
from app.agents.llm import AgentLLM, RunBudget
from app.agents.location import LocationTeam
from app.agents.survival_mapping import VerificationTable

CANDIDATES = [{"id": "l1", "name": "OO동 1층", "district": "강남구", "admin_dong": "역삼1동",
               "monthly_rent_krw": 2_500_000},
              {"id": "l2", "name": "△△동 2층", "district": "강남구", "admin_dong": "삼성2동",
               "monthly_rent_krw": 1_900_000}]
CONDITIONS = {"industry": "카페", "district": "강남구"}

PROFILE = {"demand_index": 1.4, "competition_index": 0.7, "revenue_percentile": 0.45,
           "quarter": "2026Q1",
           "demand_by_basis": {"FLOATING": 1.4, "RESIDENT": 0.6, "WORKING": 2.1}}


class FakeTradeArea:
    """상권 프로파일 어댑터의 최소 대역. 실제 모듈이 머지되면 이 자리에 그것이 들어온다."""

    available = True

    def __init__(self, rows=None, *, options=None, scoped=None):
        self.rows = rows if rows is not None else {("역삼1동", "카페"): PROFILE,
                                                   ("삼성2동", "카페"): PROFILE}
        self.scope_calls = []
        # 선택 계약은 지원할 때만 붙인다 — 팀이 `getattr` 로 지원 여부를 읽으므로,
        # 언제나 붙어 있는 대역은 "원천이 못 주는 경우"를 시험하지 못한다.
        if options is not None:
            self.industry_options = lambda industry: options
        if scoped is not None:
            self.profile_for_scope = self._scoped(scoped)

    def profile(self, admin_dong, industry):
        return self.rows.get((admin_dong, industry))

    def _scoped(self, scoped):
        def read(admin_dong, codes):
            self.scope_calls.append((admin_dong, tuple(codes)))
            return scoped.get(admin_dong)
        return read


OPTIONS = [{"code": "CS100010", "name": "커피-음료"}, {"code": "CS100011", "name": "제과점"},
           {"code": "CS100012", "name": "패스트푸드"}]


class ScriptedResponder:
    def __init__(self, **by_schema):
        self.by_schema, self.calls = by_schema, []

    async def respond(self, messages, tools, **options):
        name = tools[0]["name"]
        self.calls.append(name)
        arguments = self.by_schema.get(name)
        if arguments is None:
            return {"text": "", "tool_calls": []}
        return {"text": "", "tool_calls": [{"id": "c", "name": name, "arguments": arguments}]}


def team(trade_area=None, *, responder=None, **kwargs):
    llm = AgentLLM(responder, budget=RunBudget()) if responder is not None else None
    return LocationTeam(trade_area=trade_area, llm=llm, **kwargs)


def outcome(report, key):
    return next(item for item in report.outcomes if item.key == key)


# ── 팀 계약은 모델이 붙어도 그대로다 ──────────────────────────────────────

async def test_a_dead_axis_still_never_drops_a_candidate():
    # 원천이 없으면 모델도 부르지 않고, 후보는 전원 잔존한다.
    responder = ScriptedResponder(select_demand_basis={"basis": "WORKING"})
    report = await team(responder=responder).arun(CANDIDATES, CONDITIONS)
    assert [item["id"] for item in report.surviving] == ["l1", "l2"]
    assert report.dropped == []
    assert responder.calls == []


async def test_without_a_trade_area_no_axis_calls_the_model():
    responder = ScriptedResponder()
    report = await team(responder=responder).arun(CANDIDATES, CONDITIONS)
    for key in ("location.demand", "location.competition", "location.viability"):
        assert outcome(report, key).status is AgentStatus.INTEGRATION_PENDING


# ── location.demand — 어느 인구를 기준으로 볼 것인가 ───────────────────────

async def test_the_model_chooses_which_population_the_demand_index_reads():
    responder = ScriptedResponder(select_demand_basis={"basis": "WORKING"})
    report = await team(FakeTradeArea(), responder=responder).arun(CANDIDATES, CONDITIONS)
    demand = outcome(report, "location.demand")
    assert demand.data["basis"] == "WORKING"
    assert demand.data["by_candidate"]["l1"]["value"] == 2.1


async def test_a_basis_the_profile_does_not_carry_falls_back_to_the_composite_index():
    rows = {("역삼1동", "카페"): {"demand_index": 1.4, "quarter": "2026Q1"}}
    responder = ScriptedResponder(select_demand_basis={"basis": "RESIDENT"})
    report = await team(FakeTradeArea(rows), responder=responder).arun(CANDIDATES, CONDITIONS)
    demand = outcome(report, "location.demand")
    assert demand.data["basis"] == "COMPOSITE"
    assert demand.data["by_candidate"]["l1"]["value"] == 1.4


async def test_widening_to_a_neighbouring_dong_is_declared_unavailable_not_guessed():
    # 경계 원천이 없다. 모델이 넓히자고 해도 넓힐 근거가 없으므로 사유를 남기고 넓히지 않는다.
    responder = ScriptedResponder(select_demand_basis={"basis": "FLOATING", "widen_to_adjacent": True})
    report = await team(FakeTradeArea(), responder=responder).arun(CANDIDATES, CONDITIONS)
    demand = outcome(report, "location.demand")
    assert demand.data["widened"] is False
    assert demand.required_actions


# ── location.competition — 동종의 범위 ────────────────────────────────────

async def test_the_model_widens_the_competing_industry_scope_within_the_offered_codes():
    scoped = {"역삼1동": {"competition_index": 1.6, "quarter": "2026Q1"},
              "삼성2동": {"competition_index": 1.6, "quarter": "2026Q1"}}
    trade_area = FakeTradeArea(options=OPTIONS, scoped=scoped)
    responder = ScriptedResponder(select_competing_scope={"codes": ["CS100010", "CS100011"]})
    report = await team(trade_area, responder=responder).arun(CANDIDATES, CONDITIONS)
    competition = outcome(report, "location.competition")
    assert competition.data["scope"] == ["CS100010", "CS100011"]
    assert competition.data["scope_applied"] is True
    assert competition.data["by_candidate"]["l1"]["value"] == 1.6


async def test_a_code_outside_the_offered_options_never_reaches_the_source():
    trade_area = FakeTradeArea(options=OPTIONS, scoped={"역삼1동": {"competition_index": 1.6}})
    responder = ScriptedResponder(select_competing_scope={"codes": ["CS999999"]})
    report = await team(trade_area, responder=responder).arun(CANDIDATES, CONDITIONS)
    competition = outcome(report, "location.competition")
    assert competition.data["scope"] == []
    assert trade_area.scope_calls == []


async def test_a_source_without_industry_options_keeps_the_exact_match_scope():
    # 원천이 동종 범위를 못 주면 범위 판단 자체를 하지 않는다. 유사 매칭을 만들어 내지 않는다.
    responder = ScriptedResponder(select_competing_scope={"codes": ["CS100011"]})
    report = await team(FakeTradeArea(), responder=responder).arun(CANDIDATES, CONDITIONS)
    competition = outcome(report, "location.competition")
    assert competition.data["scope"] == []
    assert competition.status is AgentStatus.OK
    assert "select_competing_scope" not in responder.calls


# ── location.viability — 목표매출을 대입할 세분류 ──────────────────────────

async def test_the_model_picks_the_sub_industry_the_target_revenue_is_placed_in():
    trade_area = FakeTradeArea(options=OPTIONS,
                               scoped={"역삼1동": {"revenue_percentile": 0.95, "quarter": "2026Q1"},
                                       "삼성2동": {"revenue_percentile": 0.4, "quarter": "2026Q1"}})
    responder = ScriptedResponder(select_revenue_industry={"code": "CS100011"})
    report = await team(trade_area, responder=responder).arun(CANDIDATES, CONDITIONS)
    viability = outcome(report, "location.viability")
    assert viability.data["industry_code"] == "CS100011"
    # 상위 10% 경계를 넘는 후보는 분기점 미달로 탈락한다 — 이 규칙은 그대로다.
    assert [item["id"] for item in report.dropped] == ["l1"]


# ── location.survival — 매핑은 제안이고, 확정은 검증 테이블이 한다 ──────────

TABLE = VerificationTable({("I21201", "CS100010")})


async def test_a_mapping_the_verification_table_does_not_confirm_disables_the_axis():
    trade_area = FakeTradeArea(options=OPTIONS)
    responder = ScriptedResponder(propose_survival_mapping={
        "pairs": [{"licence_code": "I21201", "trade_area_code": "CS100011"}]})
    report = await team(trade_area, responder=responder, survival_table=TABLE,
                        licence_codes=["I21201"]).arun(CANDIDATES, CONDITIONS)
    survival = outcome(report, "location.survival")
    assert survival.status is AgentStatus.INTEGRATION_PENDING
    assert survival.data["mapping_confirmed"] is False
    assert survival.data["rejected_pairs"] == [["I21201", "CS100011"]]
    assert "생존" not in str(survival.data.get("by_candidate", ""))


async def test_a_confirmed_mapping_still_does_not_produce_a_survival_rate():
    # 매핑이 맞아도 인허가 코호트가 없으면 A등급 주장은 성립하지 않는다.
    trade_area = FakeTradeArea(options=OPTIONS)
    responder = ScriptedResponder(propose_survival_mapping={
        "pairs": [{"licence_code": "I21201", "trade_area_code": "CS100010"}]})
    report = await team(trade_area, responder=responder, survival_table=TABLE,
                        licence_codes=["I21201"]).arun(CANDIDATES, CONDITIONS)
    survival = outcome(report, "location.survival")
    assert survival.data["mapping_confirmed"] is True
    assert survival.status is AgentStatus.INTEGRATION_PENDING
    assert "인허가" in (survival.message or "")
    assert "survival_rate" not in survival.data


async def test_the_default_verification_table_confirms_nothing():
    # 저장소에 등록된 대조 결과가 없다. 비어 있는 것이 옳은 상태이며, 그동안 축은 꺼져 있다.
    trade_area = FakeTradeArea(options=OPTIONS)
    responder = ScriptedResponder(propose_survival_mapping={
        "pairs": [{"licence_code": "I21201", "trade_area_code": "CS100010"}]})
    report = await team(trade_area, responder=responder, licence_codes=["I21201"]).arun(
        CANDIDATES, CONDITIONS)
    survival = outcome(report, "location.survival")
    assert survival.data["mapping_confirmed"] is False


async def test_without_licence_codes_the_model_is_not_asked_to_map_anything():
    trade_area = FakeTradeArea(options=OPTIONS)
    responder = ScriptedResponder()
    await team(trade_area, responder=responder).arun(CANDIDATES, CONDITIONS)
    assert "propose_survival_mapping" not in responder.calls


# ── 결정론 경로 ──────────────────────────────────────────────────────────

def test_the_synchronous_path_is_unchanged():
    report = LocationTeam(trade_area=FakeTradeArea()).run(CANDIDATES, CONDITIONS)
    assert outcome(report, "location.demand").data["by_candidate"]["l1"]["value"] == 1.4
    assert [item["id"] for item in report.surviving] == ["l1", "l2"]
