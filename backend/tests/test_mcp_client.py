import asyncio
import os

import pytest

import app.mcp_client as mcp_client
from app.config import Settings
from app.mcp_client import MCPClient, MCPSession, MCPToolError, MCPUnavailable

SECRETS = {"kakao_rest_api_key": "KAKAO-SECRET-a1b2c3d4e5",
           "data_go_kr_service_key": "DATAGO-SECRET-f6g7h8i9j0",
           "naver_maps_client_id": "NAVERID-SECRET-k1l2m3n4o5",
           "naver_maps_client_secret": "NAVERSECRET-p6q7r8s9t0"}


def configured_settings(**overrides) -> Settings:
    base = dict(ipzitalk_mcp_enabled=True, ipzitalk_mcp_command="npx", ipzitalk_mcp_args="-y presale-mcp@0.1.0",
                kakao_rest_api_key="k", data_go_kr_service_key="d",
                naver_maps_client_id="n", naver_maps_client_secret="s")
    base.update(overrides)
    return Settings(**base)


def test_client_is_available_when_every_key_is_present():
    assert MCPClient(configured_settings()).available is True


def test_client_is_unavailable_when_the_flag_is_off():
    assert MCPClient(configured_settings(ipzitalk_mcp_enabled=False)).available is False


def test_client_is_unavailable_when_a_single_key_is_missing():
    for missing in ("kakao_rest_api_key", "data_go_kr_service_key", "naver_maps_client_id", "naver_maps_client_secret"):
        client = MCPClient(configured_settings(**{missing: ""}))
        assert client.available is False, f"{missing} 없이 available 이면 안 된다"


@pytest.mark.parametrize("branch,overrides", [
    ("flag_off", {"ipzitalk_mcp_enabled": False}),
    ("command_missing", {"ipzitalk_mcp_command": ""}),
    ("keys_missing", {"kakao_rest_api_key": ""}),
])
def test_unavailable_client_reports_a_korean_reason(branch, overrides):
    reason = MCPClient(configured_settings(**overrides)).unavailable_reason
    assert reason and reason.strip(), f"{branch}: 이유 문자열이 비어 있다"
    assert any("가" <= char <= "힣" for char in reason), f"{branch}: 한글이 하나도 없다"
    assert all(ord(char) < 128 or "가" <= char <= "힣" for char in reason), f"{branch}: 한글/ASCII 이외 문자가 섞여 있다"


def test_secrets_never_appear_in_the_unavailable_reason():
    """The reason names which variable is missing. It must never echo a value."""
    for missing in SECRETS:
        client = MCPClient(configured_settings(**{**SECRETS, missing: ""}))
        reason = client.unavailable_reason or ""
        assert missing.upper() in reason, f"{missing} 이 빠졌는데 이유에 이름이 없다"
        for name, value in SECRETS.items():
            if name != missing:
                assert value not in reason, f"{name} 값이 이유 문자열에 노출됐다"


def test_available_client_has_no_unavailable_reason():
    assert MCPClient(configured_settings()).unavailable_reason is None


def test_subprocess_env_carries_every_upstream_key():
    env = MCPClient(configured_settings()).subprocess_env()
    assert env["KAKAO_REST_API_KEY"] == "k"
    assert env["DATA_GO_KR_SERVICE_KEY"] == "d"
    assert env["NAVER_MAPS_CLIENT_ID"] == "n"
    assert env["NAVER_MAPS_CLIENT_SECRET"] == "s"


def test_subprocess_env_keeps_path_so_npx_resolves(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    env = MCPClient(configured_settings()).subprocess_env()
    assert env["PATH"] == "/usr/bin:/bin"


def test_subprocess_env_does_not_leak_the_parent_environment(monkeypatch):
    """subprocess_env() must be an explicit allowlist, never {**os.environ, ...} --
    presale-mcp is a third-party package and must never see this backend's own secrets."""
    monkeypatch.setenv("OPENAI_API_KEY", "OPENAI-DECOY-9f8e7d")
    env = MCPClient(configured_settings()).subprocess_env()
    assert "OPENAI_API_KEY" not in env
    assert "OPENAI-DECOY-9f8e7d" not in env.values()


def test_args_are_split_on_whitespace():
    assert MCPClient(configured_settings()).command_args == ["-y", "presale-mcp@0.1.0"]


def test_empty_args_produce_an_empty_list():
    assert MCPClient(configured_settings(ipzitalk_mcp_args="")).command_args == []


def test_args_respect_quoted_paths_with_spaces():
    client = MCPClient(configured_settings(ipzitalk_mcp_args='"/opt/my tools/presale-mcp" --flag'))
    assert client.command_args == ["/opt/my tools/presale-mcp", "--flag"]


def test_subprocess_env_inherits_proxy_variables(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:8443")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setenv("http_proxy", "http://proxy.internal:8080")
    monkeypatch.setenv("https_proxy", "http://proxy.internal:8443")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    env = MCPClient(configured_settings()).subprocess_env()
    assert env["HTTP_PROXY"] == "http://proxy.internal:8080"
    assert env["HTTPS_PROXY"] == "http://proxy.internal:8443"
    assert env["NO_PROXY"] == "localhost,127.0.0.1"
    assert env["http_proxy"] == "http://proxy.internal:8080"
    assert env["https_proxy"] == "http://proxy.internal:8443"
    assert env["no_proxy"] == "localhost,127.0.0.1"


def test_subprocess_env_falls_back_to_os_defpath_when_path_is_absent(monkeypatch):
    monkeypatch.delenv("PATH", raising=False)
    env = MCPClient(configured_settings()).subprocess_env()
    assert env["PATH"] == os.defpath


def test_subprocess_env_accepts_lowercase_npm_config_prefix(monkeypatch):
    monkeypatch.setenv("npm_config_registry", "https://registry.npmjs.org/")
    env = MCPClient(configured_settings()).subprocess_env()
    assert env["npm_config_registry"] == "https://registry.npmjs.org/"


def test_subprocess_env_still_does_not_leak_the_parent_environment(monkeypatch):
    """The proxy/case-insensitivity fixes must not widen the allowlist beyond what was asked."""
    monkeypatch.setenv("OPENAI_API_KEY", "OPENAI-DECOY-9f8e7d")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE-DECOY-1a2b3c")
    env = MCPClient(configured_settings()).subprocess_env()
    assert "OPENAI_API_KEY" not in env
    assert "SUPABASE_SERVICE_ROLE_KEY" not in env
    assert "OPENAI-DECOY-9f8e7d" not in env.values()
    assert "SUPABASE-DECOY-1a2b3c" not in env.values()


def test_session_raises_when_unavailable():
    client = MCPClient(configured_settings(ipzitalk_mcp_enabled=False))
    with pytest.raises(MCPUnavailable):
        client.session()


def test_session_returns_a_configured_mcp_session():
    client = MCPClient(configured_settings())
    client.startup_timeout_s = 12.5
    client.call_timeout_s = 3.5
    session = client.session()
    assert isinstance(session, MCPSession)
    assert session._command == "npx"
    assert session._args == ["-y", "presale-mcp@0.1.0"]
    assert session._startup_timeout_s == 12.5
    assert session._call_timeout_s == 3.5


def test_mcp_tool_error_is_caught_by_except_mcp_unavailable():
    """Tasks 4-6 keep a single `except MCPUnavailable` in chat_tools.py; MCPToolError must be
    a subclass so a tool-level failure doesn't need a second except-clause everywhere."""
    assert issubclass(MCPToolError, MCPUnavailable)
    try:
        raise MCPToolError("해당 주소는 데이터에 없습니다.")
    except MCPUnavailable as exc:
        assert isinstance(exc, MCPToolError)
    else:
        pytest.fail("MCPToolError was not caught by except MCPUnavailable")


class _FakeStack:
    """Stands in for AsyncExitStack in teardown tests -- records whether it was closed instead
    of requiring a real subprocess to spawn and die."""

    def __init__(self):
        self.close_count = 0

    async def aclose(self):
        self.close_count += 1


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeResult:
    def __init__(self, *, isError=False, content=None, structuredContent=None):
        self.isError = isError
        self.content = content or []
        self.structuredContent = structuredContent


class _FakeClientSession:
    def __init__(self, *, result=None, sleep_s=None, raise_exc=None):
        self._result = result if result is not None else _FakeResult()
        self._sleep_s = sleep_s
        self._raise_exc = raise_exc

    async def call_tool(self, name, arguments):
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._sleep_s is not None:
            await asyncio.sleep(self._sleep_s)
        return self._result


def _bare_session(**timeouts) -> MCPSession:
    timeouts.setdefault("startup_timeout_s", 20.0)
    timeouts.setdefault("call_timeout_s", 8.0)
    return MCPSession("npx", ["-y", "presale-mcp@0.1.0"], {}, **timeouts)


@pytest.mark.asyncio
async def test_a_startup_timeout_tears_down_cleanly_and_leaves_nothing_behind(monkeypatch):
    fake_stack = _FakeStack()
    monkeypatch.setattr(mcp_client, "AsyncExitStack", lambda: fake_stack)
    session = _bare_session(startup_timeout_s=0.01)

    async def timing_out_open(stack):
        raise TimeoutError("startup budget exceeded")

    monkeypatch.setattr(session, "_open", timing_out_open)
    with pytest.raises(MCPUnavailable):
        async with session:
            pass
    assert fake_stack.close_count == 1
    assert session._stack is None
    assert session._session is None


@pytest.mark.asyncio
async def test_a_per_call_timeout_does_not_kill_the_whole_session():
    """A single slow tool call must not tear down the session -- only the try/except inside
    call() reacts to it; there is no restart flag to flip anymore."""
    session = _bare_session(call_timeout_s=0.01)
    session._session = _FakeClientSession(sleep_s=1)
    with pytest.raises(MCPUnavailable):
        await session.call("get_geocode", {"address": "서울 마포구"})
    assert session._session is not None  # the session object itself is untouched

    # A further call against the same (still-open) session works normally.
    session._session = _FakeClientSession(result=_FakeResult(structuredContent={"documents": []}))
    result = await session.call("get_geocode", {"address": "서울 마포구"})
    assert result == {"documents": []}


@pytest.mark.asyncio
async def test_an_ordinary_call_failure_translates_to_mcp_unavailable():
    session = _bare_session()
    session._session = _FakeClientSession(raise_exc=RuntimeError("broken pipe"))
    with pytest.raises(MCPUnavailable):
        await session.call("get_geocode", {"address": "서울 마포구"})


@pytest.mark.asyncio
async def test_cancellation_mid_handshake_still_runs_teardown(monkeypatch):
    fake_stack = _FakeStack()
    monkeypatch.setattr(mcp_client, "AsyncExitStack", lambda: fake_stack)
    session = _bare_session()

    async def cancelled_open(stack):
        raise asyncio.CancelledError()

    monkeypatch.setattr(session, "_open", cancelled_open)
    with pytest.raises(asyncio.CancelledError):
        async with session:
            pass
    assert fake_stack.close_count == 1


@pytest.mark.asyncio
async def test_session_context_manager_closes_the_stack_on_success(monkeypatch):
    fake_stack = _FakeStack()
    monkeypatch.setattr(mcp_client, "AsyncExitStack", lambda: fake_stack)
    session = _bare_session()

    async def fake_open(stack):
        return _FakeClientSession(result=_FakeResult(structuredContent={"documents": []}))

    monkeypatch.setattr(session, "_open", fake_open)
    async with session as s:
        result = await s.call("get_geocode", {"address": "서울 마포구"})
        assert result == {"documents": []}
    assert fake_stack.close_count == 1


@pytest.mark.asyncio
async def test_session_context_manager_closes_the_stack_on_exception(monkeypatch):
    fake_stack = _FakeStack()
    monkeypatch.setattr(mcp_client, "AsyncExitStack", lambda: fake_stack)
    session = _bare_session()

    async def fake_open(stack):
        return _FakeClientSession(result=_FakeResult(isError=True, content=[_FakeBlock("문제가 발생했습니다.")]))

    monkeypatch.setattr(session, "_open", fake_open)
    with pytest.raises(MCPToolError):
        async with session as s:
            await s.call("get_geocode", {"address": "서울 마포구"})
    assert fake_stack.close_count == 1


@pytest.mark.asyncio
async def test_call_surfaces_the_tool_provided_error_message():
    """isError content blocks carry a human-readable explanation (this is the MCP SDK's own
    server-side convention, see Server._make_error_result) -- surface it instead of a generic
    Korean string so the model downstream gets to read why the lookup failed."""
    session = _bare_session()
    session._session = _FakeClientSession(result=_FakeResult(isError=True, content=[_FakeBlock("해당 자치구는 서울이 아닙니다.")]))
    with pytest.raises(MCPToolError) as exc_info:
        await session.call("get_geocode", {"address": "부산 해운대구"})
    assert str(exc_info.value) == "해당 자치구는 서울이 아닙니다."


@pytest.mark.asyncio
async def test_call_falls_back_to_a_generic_message_when_iserror_has_no_text():
    session = _bare_session()
    session._session = _FakeClientSession(result=_FakeResult(isError=True, content=[]))
    with pytest.raises(MCPToolError, match="조회 결과가 없습니다"):
        await session.call("get_geocode", {"address": "부산 해운대구"})


@pytest.mark.asyncio
async def test_unwrap_prefers_structured_content():
    session = _bare_session()
    session._session = _FakeClientSession(result=_FakeResult(
        structuredContent={"documents": [{"x": "126.9"}]},
        content=[_FakeBlock('{"documents": "should not be used"}')]))
    result = await session.call("get_geocode", {"address": "서울 마포구"})
    assert result == {"documents": [{"x": "126.9"}]}


@pytest.mark.asyncio
async def test_unwrap_parses_a_json_array_text_block_into_items():
    session = _bare_session()
    session._session = _FakeClientSession(result=_FakeResult(content=[_FakeBlock('[{"name": "a"}, {"name": "b"}]')]))
    result = await session.call("search_announcements", {"district": "강남구"})
    assert result == {"items": [{"name": "a"}, {"name": "b"}]}


@pytest.mark.asyncio
async def test_unwrap_raises_mcp_tool_error_on_unparseable_text():
    session = _bare_session()
    session._session = _FakeClientSession(result=_FakeResult(content=[_FakeBlock("이것은 JSON이 아닙니다")]))
    with pytest.raises(MCPToolError):
        await session.call("get_geocode", {"address": "서울 마포구"})


@pytest.mark.asyncio
async def test_unwrap_raises_mcp_tool_error_on_a_json_scalar():
    """A bare JSON string/number/bool doesn't satisfy the 'JSON object or array' contract Tasks
    4-6's handlers expect; raising here beats handing them a shape they'd KeyError on."""
    session = _bare_session()
    session._session = _FakeClientSession(result=_FakeResult(content=[_FakeBlock("42")]))
    with pytest.raises(MCPToolError):
        await session.call("get_geocode", {"address": "서울 마포구"})


@pytest.mark.asyncio
async def test_unwrap_returns_an_empty_dict_when_there_are_no_content_blocks_at_all():
    session = _bare_session()
    session._session = _FakeClientSession(result=_FakeResult(content=[]))
    result = await session.call("get_geocode", {"address": "서울 마포구"})
    assert result == {}
