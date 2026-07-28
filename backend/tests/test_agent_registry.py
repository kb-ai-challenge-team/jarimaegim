"""제안서 03장의 12개 에이전트가 코드에 그대로 선언되어 있는지 고정한다.

구성은 메인 1 · 조건 2 · 서브 9 다. 서브 9는 얼마 4 · 어디 4 · 언제 1.
이 숫자가 바뀌면 제품 정의가 바뀐 것이므로 여기서 먼저 걸린다.

근거 등급 A/B/C/U 는 제안서 06장에서 **입지 판정**에 대한 계약이다. 금융·타이밍·조건·메인은
입지 주장을 하지 않으므로 등급을 선언하지 않는다 — 등급이 없다는 것과 U 는 다른 말이다.
"""
import pytest
from app.agents.registry import AGENT_SPECS, spec


def test_the_proposal_s_twelve_agents_are_declared():
    assert len(AGENT_SPECS) == 12


def test_team_composition_is_one_main_two_conditions_and_nine_subs():
    counts: dict[str, int] = {}
    for item in AGENT_SPECS:
        counts[item.team] = counts.get(item.team, 0) + 1
    assert counts == {"main": 1, "condition": 2, "finance": 4, "location": 4, "timing": 1}


def test_every_agent_declares_where_its_answer_would_come_from():
    # 가드 3 — 원천 선언은 12개 전부의 의무다.
    for item in AGENT_SPECS:
        assert item.source_name, f"{item.key} 에 원천 선언이 없습니다"


def test_only_the_location_team_carries_an_evidence_grade():
    graded = {item.key: item.evidence_grade for item in AGENT_SPECS if item.evidence_grade}
    assert set(graded) == {"location.demand", "location.competition",
                           "location.viability", "location.survival"}


def test_the_survival_agent_is_the_only_grade_a_path():
    # 제안서 06장 — 생존확률·개별 생존등급은 A등급에서만 나올 수 있다.
    grade_a = [item.key for item in AGENT_SPECS if item.evidence_grade == "A"]
    assert grade_a == ["location.survival"]


def test_trade_area_axes_are_grade_b_because_they_are_area_aggregates():
    for key in ("location.demand", "location.competition", "location.viability"):
        assert spec(key).evidence_grade == "B"


def test_keys_are_unique():
    keys = [item.key for item in AGENT_SPECS]
    assert len(keys) == len(set(keys))


def test_spec_looks_up_by_key():
    assert spec("finance.band").name == "조달 밴드 산출"


def test_spec_rejects_an_unknown_key():
    with pytest.raises(KeyError):
        spec("finance.nope")
