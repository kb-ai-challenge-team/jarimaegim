import pytest

from app.config import Settings
from app.mcp_client import MCPClient

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


def test_subprocess_env_carries_every_upstream_key():
    env = MCPClient(configured_settings()).subprocess_env()
    assert env["KAKAO_REST_API_KEY"] == "k"
    assert env["DATA_GO_KR_SERVICE_KEY"] == "d"
    assert env["NAVER_MAPS_CLIENT_ID"] == "n"
    assert env["NAVER_MAPS_CLIENT_SECRET"] == "s"


def test_args_are_split_on_whitespace():
    assert MCPClient(configured_settings()).command_args == ["-y", "presale-mcp@0.1.0"]


def test_empty_args_produce_an_empty_list():
    assert MCPClient(configured_settings(ipzitalk_mcp_args="")).command_args == []
