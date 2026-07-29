"""어디 — 입지추천 팀. 제안서 04장의 팀 계약을 고정한다.

  산출물   후보 · 축별 등급 · 탈락 사유
  실패 시  실패한 축만 제외 — 탈락 근거로 쓰지 않는다

가장 중요한 성질은 마지막 줄이다. 가동하지 못한 축이 후보를 떨어뜨리면, 데이터가 없다는
사실이 "이 자리는 나쁘다"로 둔갑한다.
"""
from app.agents.contracts import AgentStatus
from app.agents.location import LocationTeam

CANDIDATES = [
    {"id": "l1", "name": "OO동 1층", "district": "강남구", "admin_dong": "역삼1동",
     "monthly_rent_krw": 2_500_000},
    {"id": "l2", "name": "△△동 2층", "district": "강남구", "admin_dong": "삼성2동",
     "monthly_rent_krw": 1_900_000},
]
CONDITIONS = {"industry": "카페", "district": "강남구"}


class FakeTradeArea:
    """상권 프로파일이 붙었을 때의 최소 대역. 실제 모듈이 머지되면 이 자리에 그것이 들어온다."""

    available = True

    def __init__(self, rows=None):
        self.rows = rows or {}

    def profile(self, admin_dong: str, industry: str):
        return self.rows.get((admin_dong, industry))


PROFILE_STRONG = {"demand_index": 1.4, "competition_index": 0.7, "revenue_percentile": 0.45,
                  "quarter": "2026Q1"}
PROFILE_WEAK = {"demand_index": 0.6, "competition_index": 1.5, "revenue_percentile": 0.95,
                "quarter": "2026Q1"}


def test_the_team_runs_all_five_of_its_axes():
    report = LocationTeam().run(CANDIDATES, CONDITIONS)
    assert [item.key for item in report.outcomes] == [
        "location.demand", "location.competition", "location.viability",
        "location.survival", "location.access"]


def test_without_a_trade_area_profile_every_axis_is_pending():
    report = LocationTeam().run(CANDIDATES, CONDITIONS)
    for item in report.outcomes[:3]:
        assert item.status is AgentStatus.INTEGRATION_PENDING, item.key


def test_survival_is_pending_because_the_licence_cohort_is_not_built():
    report = LocationTeam().run(CANDIDATES, CONDITIONS)
    survival = next(item for item in report.outcomes if item.key == "location.survival")
    assert survival.status is AgentStatus.INTEGRATION_PENDING
    assert "인허가" in (survival.message or "")


def test_a_dead_axis_never_drops_a_candidate():
    # 팀 계약의 핵심. 축이 전부 꺼져 있어도 후보는 전원 잔존한다.
    report = LocationTeam().run(CANDIDATES, CONDITIONS)
    assert [item["id"] for item in report.surviving] == ["l1", "l2"]
    assert report.dropped == []


def test_a_location_failure_never_stops_the_run():
    """입지 축은 중단 규칙에 들어 있지 않다 — 축 하나가 죽어도 나머지로 계속 간다.
    중단은 조건 미확정과 여력 커널 실패 둘뿐이고, 그 판정은 orchestrator 가 한다."""
    from app.agents.orchestrator import capacity_failed, conditions_unsettled
    report = LocationTeam().run(CANDIDATES, CONDITIONS)
    assert not hasattr(report, "halted")
    assert not hasattr(report, "blocking")


def test_axes_turn_on_when_a_profile_is_available():
    trade = FakeTradeArea({("역삼1동", "카페"): PROFILE_STRONG, ("삼성2동", "카페"): PROFILE_STRONG})
    report = LocationTeam(trade_area=trade).run(CANDIDATES, CONDITIONS)
    for item in report.outcomes[:3]:
        assert item.status is AgentStatus.OK, item.key


def test_a_judged_axis_carries_grade_b_because_it_is_an_area_aggregate():
    trade = FakeTradeArea({("역삼1동", "카페"): PROFILE_STRONG})
    report = LocationTeam(trade_area=trade).run(CANDIDATES, CONDITIONS)
    demand = next(item for item in report.outcomes if item.key == "location.demand")
    assert demand.data["by_candidate"]["l1"]["evidence_grade"] == "B"


def test_a_candidate_without_a_profile_is_unjudged_not_failed():
    # 한 후보만 프로파일이 있는 경우 — 나머지는 판정 없음이지 탈락이 아니다.
    trade = FakeTradeArea({("역삼1동", "카페"): PROFILE_STRONG})
    report = LocationTeam(trade_area=trade).run(CANDIDATES, CONDITIONS)
    demand = next(item for item in report.outcomes if item.key == "location.demand")
    assert "l2" not in demand.data["by_candidate"]
    assert [item["id"] for item in report.surviving] == ["l1", "l2"]


def test_a_candidate_above_the_top_decile_boundary_is_hard_dropped_with_a_reason():
    # 제안서 04장 하드 탈락 — 목표매출이 상권 동종 상위 10% 경계를 넘으면 분기점 미달이다.
    trade = FakeTradeArea({("역삼1동", "카페"): PROFILE_STRONG, ("삼성2동", "카페"): PROFILE_WEAK})
    report = LocationTeam(trade_area=trade).run(CANDIDATES, CONDITIONS)
    assert [item["id"] for item in report.surviving] == ["l1"]
    assert report.dropped[0]["id"] == "l2"
    assert "분기점" in report.dropped[0]["reason"]


def test_only_the_sales_axis_may_drop_a_candidate():
    """탈락 권한은 매출 축 하나뿐이다. 축이 여덟으로 늘었다고 탈락 사유가 여덟이 되면 안 된다 —
    축을 늘린 목적은 "무엇을 아는가"를 넓히는 것이지 "무엇을 떨어뜨리는가"를 넓히는 것이 아니다.

    예전에는 스트레스 검사도 후보를 떨어뜨릴 수 있었다(`stress_check`). 운영 배선에는 한 번도
    연결된 적이 없어 죽은 경로였고, 살아 있었다면 불변조건 3을 어겼을 것이다."""
    from app.agents.narrowing import DROP_AUTHORITY, UnauthorisedDrop, drop_reason
    import pytest as _pytest
    assert DROP_AUTHORITY == frozenset({"location.viability"})
    with _pytest.raises(UnauthorisedDrop):
        drop_reason("location.demand", {"above_top_decile": True, "value": 0.95})

def test_the_drop_count_is_not_fixed():
    # "8 → 4 고정"이 아니라 사유가 있는 것만 탈락한다.
    trade = FakeTradeArea({("역삼1동", "카페"): PROFILE_WEAK, ("삼성2동", "카페"): PROFILE_WEAK})
    report = LocationTeam(trade_area=trade).run(CANDIDATES, CONDITIONS)
    assert report.surviving == []
    assert len(report.dropped) == 2
