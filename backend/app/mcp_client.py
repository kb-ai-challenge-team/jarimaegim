from __future__ import annotations
import json
import logging
import os
import shlex
from contextlib import AsyncExitStack
from typing import Any
import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .config import Settings

logger = logging.getLogger(__name__)

# The child (launched via npx) needs enough of the parent environment to resolve
# Node and npm, plus proxy settings if the host sits behind one -- but nothing else.
# Never fall back to inheriting the full parent environment; that would hand a
# third-party package every secret this backend holds.
# Note: HTTP_PROXY/HTTPS_PROXY values can themselves embed http://user:pass@host
# credentials. We inherit them anyway (npx needs them to function behind a proxy at
# all), but that's a real, deliberate exception to "never leak secrets" -- not an
# oversight.
_INHERITED_ENV_NAMES = ("PATH", "HOME",
                        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
                        "http_proxy", "https_proxy", "no_proxy")
_INHERITED_ENV_PREFIXES = ("NODE_", "NPM_CONFIG_")


class MCPUnavailable(Exception):
    """Raised when a tool call is attempted while the subprocess cannot serve it."""


class MCPToolError(MCPUnavailable):
    """The session is healthy; the tool itself reported a failure (isError=True), or its
    payload didn't parse into the shape callers rely on. Doesn't imply the session is dead --
    an empty-result lookup is expected behavior for a Korean public-data API, not a transport
    problem. A subclass of MCPUnavailable so callers that only need to know "this call didn't
    produce data" can keep a single `except MCPUnavailable`."""


class MCPClient:
    """Owns presale-mcp's configuration and availability gating. Holds no session of its own:
    `session()` returns an MCPSession scoped to a single turn -- spawn, handshake, every call,
    and teardown all happen inside one `async with` block, in the task that opens it. Nothing
    is held across turns, so there is no restart concept and no cross-task cancel-scope risk
    (see MCPSession for why that matters)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        # Cold `npx <package>@version` has to resolve the version, download and extract the
        # tarball, and start node before it can answer `initialize()` -- that can genuinely take
        # several seconds even on a decent connection. 20s is generous enough to tolerate a real
        # cold start without leaving a chat turn hanging forever against a broken registry. This
        # is a reasoned default, not a measured one: we have no Naver Maps credentials yet, so
        # this client has never run against a real presale-mcp subprocess (Task 17 should revisit
        # once it can).
        self.startup_timeout_s = 20.0
        # A single tool call against an already-initialized session -- a plain HTTP-backed
        # lookup, not a cold start. Kept short since a slow answer here is a data-provider
        # problem the model should hear about promptly, not a startup cost to absorb.
        # 15s, not the 8s this started as. Measured against the live upstreams: get_complex_trades
        # and the Kakao searches answer in ~3s, but get_complex_info (K-apt) takes 4.3s when given
        # bjd_code+name and 7.7s when it has to resolve a complex_query -- from a laptop. Production
        # sits further from the API and regularly crossed 8s, so a tool that works locally reported
        # a timeout to real users. A turn is still bounded overall: 12 raw calls inside a 90s turn.
        self.call_timeout_s = 15.0

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

    def session(self) -> "MCPSession":
        """`async with client.session() as session: await session.call(name, arguments)`.

        Every call site opens its own subprocess and MCP handshake and tears it down on the
        way out of the `async with` block -- success, tool error, timeout, or cancellation
        alike. This costs a fresh cold start per turn (no warm-subprocess reuse), which we
        accept deliberately: a long-lived session shared across concurrent calling tasks would
        need its own restart/locking machinery, and we have no Naver Maps credentials to
        exercise that against a real subprocess before Task 17 at the earliest. Turn-scoped
        ownership is correct by construction instead -- the same task always opens and closes
        the session, so anyio's "a cancel scope must be exited by the task that entered it"
        requirement can't be violated."""
        if not self.available:
            raise MCPUnavailable(self.unavailable_reason or "ipzitalk 도구를 사용할 수 없습니다.")
        return MCPSession(self.settings.ipzitalk_mcp_command, self.command_args, self.subprocess_env(),
                          startup_timeout_s=self.startup_timeout_s, call_timeout_s=self.call_timeout_s)


class MCPSession:
    """One presale-mcp subprocess + MCP session, owned entirely by the task that opens it via
    `async with`.

    Timeout design note: `session.initialize()` and `session.call_tool()` are each individually
    wrapped in `anyio.fail_after`, never `asyncio.wait_for`. `wait_for` schedules the wrapped
    awaitable as a *new* asyncio Task; since `stdio_client`/`ClientSession` open anyio cancel
    scopes as part of their own `async with`, running them under a different task than the one
    that will eventually close them raises "Attempted to exit cancel scope in a different task
    than it was entered in" on the very first restart under concurrency. `anyio.fail_after`
    instead scopes the cancellation to the *current* task, so it composes safely with those
    nested scopes.

    A second, less obvious rule follows from the same fact: the timeout must wrap only a single
    leaf await (`initialize()`, `call_tool()`), never the `stack.enter_async_context(...)` calls
    that open `stdio_client`/`ClientSession` themselves. Wrapping the whole multi-step handshake
    in one `fail_after` block was tried and reproducibly raises the same cross-scope RuntimeError
    when the deadline fires mid-handshake -- a cancel scope opened by a not-yet-returned
    `@asynccontextmanager` generator can't be safely unwound by an outer scope's cancellation.
    Spawning the process (entering `stdio_client`) is a fast, effectively non-blocking syscall;
    the actual cold-start delay of a `npx` install surfaces inside `initialize()`'s wait for the
    handshake response, which is exactly where the budget is applied. See
    test_a_real_startup_timeout_reaps_the_child_process for the regression check against a real
    subprocess.

    Caller contract: `call()` must not be awaited after the `async with` block that produced this
    session has exited, and must not be handed to a detached task spawned from inside that block
    and awaited from there concurrently with the block's own exit -- either way reintroduces a
    second task touching the same cancel scopes this class exists to keep single-task, and
    `__aexit__`/`_stack.aclose()` racing a still-in-flight `call()` is exactly the failure mode
    turn-scoping was meant to rule out.
    """

    def __init__(self, command: str, args: list[str], env: dict[str, str], *,
                 startup_timeout_s: float, call_timeout_s: float):
        self._command = command
        self._args = args
        self._env = env
        self._startup_timeout_s = startup_timeout_s
        self._call_timeout_s = call_timeout_s
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def _open(self, stack: AsyncExitStack) -> ClientSession:
        params = StdioServerParameters(command=self._command, args=self._args, env=self._env)
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        with anyio.fail_after(self._startup_timeout_s):
            await session.initialize()
        return session

    async def __aenter__(self) -> "MCPSession":
        stack = AsyncExitStack()
        started = False
        try:
            self._session = await self._open(stack)
            started = True
        except TimeoutError as exc:
            logger.warning("ipzitalk MCP 세션 시작 타임아웃: timeout_s=%.1f", self._startup_timeout_s)
            raise MCPUnavailable(f"ipzitalk 도구 시작이 {round(self._startup_timeout_s)}초 안에 끝나지 않았습니다.") from exc
        except Exception as exc:
            # Any ordinary failure during spawn/handshake -- npx missing from PATH
            # (FileNotFoundError), a malformed InitializeResult from a misbehaving server
            # (pydantic.ValidationError), a pipe breaking mid-handshake (ConnectionResetError)
            # -- must degrade to the same explicit, catchable MCPUnavailable that call() already
            # raises for its failures. Letting any of these escape as their raw type would sail
            # past every `except MCPUnavailable` Tasks 4-6 write their handlers around and surface
            # as an unhandled 500, which is exactly the crash this project's first hard rule
            # (§ Appendix A) forbids. The exception type is logged, never put in the user-facing
            # message.
            logger.warning("ipzitalk MCP 세션 시작 실패: %s", type(exc).__name__)
            raise MCPUnavailable("ipzitalk 도구를 시작하지 못했습니다.") from exc
        except BaseException as exc:
            # Catch everything else -- i.e. genuine cancellation -- purely to log that a startup
            # attempt failed before it leaves no trace. Never converted: re-raised unchanged so
            # cancellation semantics reach the caller intact.
            logger.warning("ipzitalk MCP 세션 시작 실패: %s", type(exc).__name__)
            raise
        finally:
            # `finally`, not `except Exception`: a timeout or external cancellation delivers
            # CancelledError (BaseException, not Exception) into whichever await was suspended
            # inside `_open`. `except Exception` would skip straight past it and leave the
            # partially-started subprocess and pipes referenced only by this now-discarded
            # local `stack` -- orphaned with nothing left to close them. `finally` runs
            # regardless of exception type, so cleanup happens whether `_open` failed with an
            # ordinary exception, our own startup timeout, or a genuine external cancellation.
            if not started:
                try:
                    await stack.aclose()
                except BaseException as close_exc:
                    logger.warning("ipzitalk MCP 세션 정리 중 오류: %s", type(close_exc).__name__)
        self._stack = stack
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        stack, self._stack, self._session = self._stack, None, None
        if stack is None:
            return
        try:
            await stack.aclose()
        except Exception as close_exc:
            # Logged, not re-raised: a teardown hiccup must not shadow whatever exception (or
            # lack of one) is already propagating out of the `async with` body. A genuine
            # CancelledError here (BaseException, not Exception) is not caught by this clause
            # and propagates normally.
            logger.warning("ipzitalk MCP 세션 종료 중 오류: %s", type(close_exc).__name__)

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._session is None:
            raise MCPUnavailable("ipzitalk MCP 세션이 아직 시작되지 않았습니다.")
        try:
            with anyio.fail_after(self._call_timeout_s):
                result = await self._session.call_tool(tool_name, arguments)
        except TimeoutError as exc:
            logger.warning("ipzitalk MCP 호출 타임아웃: tool=%s timeout_s=%.1f", tool_name, self._call_timeout_s)
            raise MCPUnavailable(f"{tool_name} 조회가 {round(self._call_timeout_s)}초 안에 끝나지 않았습니다.") from exc
        except Exception as exc:
            # Plain Exception, not BaseException: a genuine CancelledError must propagate
            # untouched, not be relabeled as a data-layer failure.
            logger.warning("ipzitalk MCP 호출 실패: tool=%s error=%s", tool_name, type(exc).__name__)
            raise MCPUnavailable(f"{tool_name} 조회에 실패했습니다.") from exc
        # A tool-level failure leaves the session alone -- only the try/except above (transport
        # or timeout) is a reason to consider the subprocess unhealthy.
        if result.isError:
            raise MCPToolError(_tool_error_message(tool_name, result))
        return _unwrap(tool_name, result)


def _tool_error_message(tool_name: str, result: Any) -> str:
    """The MCP SDK's own server-side convention (see mcp.server.lowlevel.server
    Server._make_error_result) is to put a human-readable explanation in the first text
    content block when isError is set. Surface that to the model rather than a generic
    message, so it can read why presale-mcp couldn't answer.

    presale-mcp itself, though, puts the *whole JSON result* (e.g.
    '{"error":"NOT_FOUND","message":"[NOT_FOUND] ...","metadata":{...}}') in that text block --
    confirmed by reading its source (src/tool-result.ts's jsonToolResult, used for every isError
    response it produces). Handing the raw JSON blob to the model as "the reason" would be
    technically true but unreadable, so this prefers the embedded `message` field when the text
    parses as a JSON object with one, falling back to the raw text for any other tool (or MCP
    server) that follows the SDK's plain-text convention instead."""
    blocks = getattr(result, "content", None) or []
    for block in blocks:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return text
        if isinstance(parsed, dict) and isinstance(parsed.get("message"), str) and parsed["message"]:
            return parsed["message"]
        return text
    return f"{tool_name} 조회 결과가 없습니다."


def _unwrap(tool_name: str, result: Any) -> dict[str, Any]:
    """The shape contract every chat_tools.py handler relies on: a JSON *object* -- either
    `structuredContent` verbatim, the parsed JSON object from the first text content block, or
    {"items": [...]} when that JSON was an array. A payload that isn't valid JSON, or that
    parses to a JSON scalar (string/number/bool/null), can't satisfy that contract; rather than
    hand handlers an ad hoc {"text": ...} shape they'd have to reverse-engineer and would
    KeyError on, we raise MCPToolError so the failure is catchable the same way an isError
    response is. An empty content list (no blocks at all) is a legitimate degenerate case and
    returns {} -- a valid, if empty, flat dict.

    get_static_map is the one tool that returns an *image*, not just JSON: it emits an MCP
    ImageContent block (type="image", data=<base64>, mimeType=<string>) alongside its
    structuredContent (confirmed by reading presale-mcp's own source, src/tool-result.ts's
    imageToolResult). Before this fix, the `structuredContent`-first branch below returned that
    metadata dict and silently discarded the image block entirely -- there is no path by which
    get_location_map_image could ever have produced an image. Any image block found is folded
    into the returned dict under image_base64/image_mime_type so chat_tools.py's handler can read
    it; this is additive and does not change the shape returned for any of the other nine tools,
    none of which emit an image block."""
    structured = getattr(result, "structuredContent", None)
    payload = dict(structured) if isinstance(structured, dict) else None
    blocks = getattr(result, "content", None) or []
    image_block = next((block for block in blocks if getattr(block, "type", None) == "image"), None)
    if image_block is not None:
        payload = payload if payload is not None else {}
        payload["image_base64"] = getattr(image_block, "data", None)
        payload["image_mime_type"] = getattr(image_block, "mimeType", None)
    if payload is not None:
        return payload
    for block in blocks:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise MCPToolError(f"{tool_name} 응답을 해석할 수 없습니다.") from exc
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        raise MCPToolError(f"{tool_name} 응답 형식이 예상과 다릅니다.")
    return {}
