import asyncio
import os

import pytest

from app.config import Settings
from app.mcp_client import MCPClient, MCPUnavailable

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


@pytest.mark.asyncio
async def test_call_raises_when_unavailable():
    client = MCPClient(configured_settings(ipzitalk_mcp_enabled=False))
    with pytest.raises(MCPUnavailable):
        await client.call("get_geocode", {"address": "서울 마포구"})


@pytest.mark.asyncio
async def test_call_returns_the_parsed_tool_payload(monkeypatch):
    client = MCPClient(configured_settings())
    calls = []

    async def fake_session_call(name, arguments):
        calls.append((name, arguments))
        return {"documents": [{"x": "126.9", "y": "37.5"}]}

    monkeypatch.setattr(client, "_session_call", fake_session_call)
    result = await client.call("get_geocode", {"address": "서울 마포구"})
    assert result == {"documents": [{"x": "126.9", "y": "37.5"}]}
    assert calls == [("get_geocode", {"address": "서울 마포구"})]


@pytest.mark.asyncio
async def test_a_failed_call_marks_the_client_for_restart(monkeypatch):
    client = MCPClient(configured_settings())

    async def failing_call(name, arguments):
        raise RuntimeError("broken pipe")

    monkeypatch.setattr(client, "_session_call", failing_call)
    with pytest.raises(MCPUnavailable):
        await client.call("get_geocode", {"address": "서울 마포구"})
    assert client.restart_pending is True


@pytest.mark.asyncio
async def test_a_call_that_exceeds_the_timeout_raises(monkeypatch):
    client = MCPClient(configured_settings())
    client.call_timeout_s = 0.01

    async def slow_call(name, arguments):
        await asyncio.sleep(1)
        return {}

    monkeypatch.setattr(client, "_session_call", slow_call)
    with pytest.raises(MCPUnavailable):
        await client.call("get_geocode", {"address": "서울 마포구"})
