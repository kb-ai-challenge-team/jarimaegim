from app.districts import SEOUL_DISTRICTS


def test_holds_all_twenty_five_districts():
    assert len(SEOUL_DISTRICTS) == 25


def test_main_and_chat_tools_share_the_same_source():
    """같은 판단을 하는 세 모듈이 서로 다른 목록을 들면 스코프 게이트가 갈라진다."""
    from app.main import SEOUL_DISTRICTS as from_main
    from app.chat_tools import SEOUL_DISTRICTS as from_tools
    assert from_main is SEOUL_DISTRICTS
    assert from_tools is SEOUL_DISTRICTS


def test_order_is_stable_and_duplicate_free():
    """_district 의 first-match-wins 가 프로세스마다 달라지지 않으려면 순서가 고정이어야 한다.
    frozenset 은 해시 순서로 순회하므로 두 자치구가 언급된 문장에서 결과가 흔들렸다."""
    assert isinstance(SEOUL_DISTRICTS, tuple)
    assert len(set(SEOUL_DISTRICTS)) == len(SEOUL_DISTRICTS)
    assert SEOUL_DISTRICTS[0] == "종로구"
    assert SEOUL_DISTRICTS[-1] == "강동구"
