from __future__ import annotations
import asyncio
import json
import os
import shlex
from contextlib import AsyncExitStack
from typing import Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .config import Settings

# The child (launched via npx) needs enough of the parent environment to resolve
# Node and npm, plus proxy settings if the host sits behind one -- but nothing else.
# Never fall back to inheriting the full parent environment; that would hand a
# third-party package every secret this backend holds.
_INHERITED_ENV_NAMES = ("PATH", "HOME",
                        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
                        "http_proxy", "https_proxy", "no_proxy")
_INHERITED_ENV_PREFIXES = ("NODE_", "NPM_CONFIG_")


class MCPUnavailable(Exception):
    """Raised when a tool call is attempted while the subprocess cannot serve it."""


class MCPClient:
    """Owns the presale-mcp subprocess. Knows nothing about Jarimaegim's domain."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.call_timeout_s = 8.0
        self.restart_pending = False
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()

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
        """Explicit allowlist only: Node/npm resolution variables and proxy settings actually
        present in the parent environment, plus the four upstream keys. Never the full parent
        environment -- presale-mcp is a third-party package and must not see OPENAI_API_KEY,
        Supabase credentials, or anything else this backend holds."""
        inherited = {name: value for name, value in os.environ.items()
                     if name in _INHERITED_ENV_NAMES or name.upper().startswith(_INHERITED_ENV_PREFIXES)}
        # Spawning the bare command name (e.g. "npx") depends on PATH to resolve; fall back to
        # the OS default search path rather than leaving the child with none at all.
        inherited.setdefault("PATH", os.defpath)
        return {**inherited,
                "KAKAO_REST_API_KEY": self.settings.kakao_rest_api_key,
                "DATA_GO_KR_SERVICE_KEY": self.settings.data_go_kr_service_key,
                "NAVER_MAPS_CLIENT_ID": self.settings.naver_maps_client_id,
                "NAVER_MAPS_CLIENT_SECRET": self.settings.naver_maps_client_secret}

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            raise MCPUnavailable(self.unavailable_reason or "ipzitalk 도구를 사용할 수 없습니다.")
        try:
            return await asyncio.wait_for(self._session_call(tool_name, arguments), timeout=self.call_timeout_s)
        except asyncio.TimeoutError as exc:
            self.restart_pending = True
            raise MCPUnavailable(f"{tool_name} 조회가 {int(self.call_timeout_s)}초 안에 끝나지 않았습니다.") from exc
        except MCPUnavailable:
            raise
        except Exception as exc:
            # The subprocess may have died mid-call; force a restart before the next one.
            self.restart_pending = True
            raise MCPUnavailable(f"{tool_name} 조회에 실패했습니다.") from exc

    async def _session_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session = await self._ensure_session()
        result = await session.call_tool(tool_name, arguments)
        if result.isError:
            raise RuntimeError(f"{tool_name} tool call returned isError=True")
        return self._unwrap(result)

    async def _ensure_session(self) -> ClientSession:
        async with self._lock:
            if self.restart_pending:
                await self._close_locked()
                self.restart_pending = False
            if self._session is not None:
                return self._session
            stack = AsyncExitStack()
            try:
                params = StdioServerParameters(command=self.settings.ipzitalk_mcp_command,
                                               args=self.command_args, env=self.subprocess_env())
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
            except Exception:
                # Never leak a half-started subprocess if the handshake fails partway.
                await stack.aclose()
                raise
            self._stack, self._session = stack, session
            return session

    @staticmethod
    def _unwrap(result: Any) -> dict[str, Any]:
        """Modern MCP tools may return structuredContent directly; text-only servers like
        presale-mcp put their JSON payload in the first text content block instead."""
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured
        blocks = getattr(result, "content", None) or []
        for block in blocks:
            text = getattr(block, "text", None)
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                return {"text": text}
            return parsed if isinstance(parsed, dict) else {"items": parsed}
        return {}

    async def _close_locked(self) -> None:
        stack, self._stack, self._session = self._stack, None, None
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:
                pass

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()
