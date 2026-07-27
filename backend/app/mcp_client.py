from __future__ import annotations
import os
import shlex
from typing import Any
from .config import Settings

# The child (launched via npx) needs enough of the parent environment to resolve
# Node and npm -- but nothing else. Never fall back to inheriting the full parent
# environment; that would hand a third-party package every secret this backend holds.
_INHERITED_ENV_NAMES = ("PATH", "HOME")
_INHERITED_ENV_PREFIXES = ("NODE_", "NPM_CONFIG_")


class MCPUnavailable(Exception):
    """Raised when a tool call is attempted while the subprocess cannot serve it."""


class MCPClient:
    """Owns the presale-mcp subprocess. Knows nothing about Jarimaegim's domain."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def available(self) -> bool:
        return self.settings.ipzitalk_configured

    @property
    def unavailable_reason(self) -> str | None:
        if self.available:
            return None
        if not self.settings.ipzitalk_mcp_enabled:
            return "ipzitalk 도구 연동이 꺼져 있습니다."
        if not self.settings.ipzitalk_mcp_command:
            return "ipzitalk MCP 실행 명령이 설정되지 않았습니다."
        # Name the variables, never their values.
        missing = [name for name, value in (
            ("KAKAO_REST_API_KEY", self.settings.kakao_rest_api_key),
            ("DATA_GO_KR_SERVICE_KEY", self.settings.data_go_kr_service_key),
            ("NAVER_MAPS_CLIENT_ID", self.settings.naver_maps_client_id),
            ("NAVER_MAPS_CLIENT_SECRET", self.settings.naver_maps_client_secret),
        ) if not value]
        return f"필수 API 키가 설정되지 않았습니다: {', '.join(missing)}"

    @property
    def command_args(self) -> list[str]:
        return shlex.split(self.settings.ipzitalk_mcp_args)

    def subprocess_env(self) -> dict[str, str]:
        """Explicit allowlist only: Node/npm resolution variables actually present in the
        parent environment, plus the four upstream keys. Never the full parent environment --
        presale-mcp is a third-party package and must not see OPENAI_API_KEY, Supabase
        credentials, or anything else this backend holds."""
        inherited = {name: value for name, value in os.environ.items()
                     if name in _INHERITED_ENV_NAMES or name.startswith(_INHERITED_ENV_PREFIXES)}
        return {**inherited,
                "KAKAO_REST_API_KEY": self.settings.kakao_rest_api_key,
                "DATA_GO_KR_SERVICE_KEY": self.settings.data_go_kr_service_key,
                "NAVER_MAPS_CLIENT_ID": self.settings.naver_maps_client_id,
                "NAVER_MAPS_CLIENT_SECRET": self.settings.naver_maps_client_secret}

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise MCPUnavailable(self.unavailable_reason or "MCP 세션이 아직 구현되지 않았습니다.")
