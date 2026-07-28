from uuid import uuid4
from app.config import Settings
from app.repository import Repository


def repository():
    return Repository(Settings(supabase_url="", supabase_service_role_key=""))


def test_the_first_turn_is_allowed():
    assert repository().consume_daily_turn(uuid4(), limit=3) is True


def test_turns_are_allowed_up_to_the_limit():
    repo, session = repository(), uuid4()
    assert [repo.consume_daily_turn(session, limit=3) for _ in range(3)] == [True, True, True]


def test_the_turn_after_the_limit_is_refused():
    repo, session = repository(), uuid4()
    for _ in range(3):
        repo.consume_daily_turn(session, limit=3)
    assert repo.consume_daily_turn(session, limit=3) is False


def test_sessions_do_not_share_a_counter():
    repo, first, second = repository(), uuid4(), uuid4()
    for _ in range(3):
        repo.consume_daily_turn(first, limit=3)
    assert repo.consume_daily_turn(second, limit=3) is True


def test_a_zero_limit_refuses_everything():
    """0 은 '설정하지 않음'과 구분되지 않는다. 미설정으로 AI 호출이 새어 나가면 안 되므로 닫는다."""
    assert repository().consume_daily_turn(uuid4(), limit=0) is False


def test_a_negative_limit_means_unlimited():
    """음수는 실수로 나올 수 없는 값이다 — 일부러 적은 '한도 없음' 선언으로 읽는다.

    0 과 달리 음수는 미설정과 헷갈리지 않으므로 열어 준다. 이 구분이 없으면 무제한을
    의도한 설정이 오히려 모든 턴을 막는다.
    """
    repo, session = repository(), uuid4()
    assert [repo.consume_daily_turn(session, limit=-1) for _ in range(50)] == [True] * 50


def test_an_unlimited_session_does_not_fill_the_counter():
    """무제한이면 셀 이유가 없다. 세어 두면 한도를 다시 켰을 때 이미 소진된 상태가 된다."""
    repo, session = repository(), uuid4()
    for _ in range(10):
        repo.consume_daily_turn(session, limit=-1)
    assert repo.consume_daily_turn(session, limit=3) is True


def test_the_counter_resets_on_a_new_day(monkeypatch):
    import app.repository as repository_module
    repo, session = repository(), uuid4()
    for _ in range(3):
        repo.consume_daily_turn(session, limit=3)
    assert repo.consume_daily_turn(session, limit=3) is False
    monkeypatch.setattr(repository_module, "_today", lambda: "2099-01-01")
    assert repo.consume_daily_turn(session, limit=3) is True
