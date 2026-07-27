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
    assert repository().consume_daily_turn(uuid4(), limit=0) is False


def test_the_counter_resets_on_a_new_day(monkeypatch):
    import app.repository as repository_module
    repo, session = repository(), uuid4()
    for _ in range(3):
        repo.consume_daily_turn(session, limit=3)
    assert repo.consume_daily_turn(session, limit=3) is False
    monkeypatch.setattr(repository_module, "_today", lambda: "2099-01-01")
    assert repo.consume_daily_turn(session, limit=3) is True
