from app.districts import SEOUL_DISTRICTS


def test_holds_all_twenty_five_districts():
    assert len(SEOUL_DISTRICTS) == 25


def test_main_and_chat_tools_share_the_same_source():
    """같은 판단을 하는 세 모듈이 서로 다른 목록을 들면 스코프 게이트가 갈라진다."""
    from app.main import SEOUL_DISTRICTS as from_main
    from app.chat_tools import SEOUL_DISTRICTS as from_tools
    assert from_main is SEOUL_DISTRICTS
    assert from_tools is SEOUL_DISTRICTS
