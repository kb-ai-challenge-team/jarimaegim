# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

The workspace root (`KB AI Challenge/`) is **not** a git repository — it holds the competition spec documents. All code lives in `ter-doctor-demo/`, which is its own git repo. Run all commands from `ter-doctor-demo/`.

Spec documents at the workspace root are the source of truth for product behavior and must be consulted before changing user-facing contracts:

- `KB_터닥터_실서비스_개발명세서.md` — full service spec: API contracts (§11), Supabase schema/RLS (§12), deployment (§13), AI guardrails (§8), and **부록 A "구현 불변조건"** (the hard invariants below).
- `터닥터_UI_UX_설계명세서.md` — IA/URL map (§3), evidence-grade presentation rules (§8), state design (§11), accessibility (§16).
- `KB부동산_Stitch_리디자인_프롬프트.md` — visual direction for the `components/kb/` KB-styled workspace.

The product is named **자리매김 (Jarimaegim)**; "터닥터 / ter-doctor" is the older name and still appears in directory names, systemd unit names, and spec filenames.

## Commands

```bash
npm run dev            # Next.js (:4173) + FastAPI (:8000) together via concurrently
npm run dev:web        # frontend only
npm run api:dev        # backend only (requires backend/.venv)
npm run build          # next build
npm run lint           # eslint
npm run typecheck      # tsc --noEmit
npm run api:check      # python compileall over backend/app
npm run api:test       # cd backend && .venv/bin/python -m pytest (380 tests, backend/tests/)
npm run test:kakao-tools   # node --test over the two Kakao key/SDK script test files
npm run test:sse           # node --test scripts/sse-parser.test.mjs
npm run test:chat-stream   # node --test scripts/chat-stream-dispatch.test.mjs
```

Run a single Node test file: `node --test scripts/check-kakao-sdk.test.mjs`.

`backend/pytest.ini` registers a `slow` marker for a test that spawns a real `presale-mcp`-shaped
subprocess (`test_mcp_client.py`); exclude it with `.venv/bin/python -m pytest -m "not slow"` when
you want a fast run.

Backend venv is gitignored and must exist at `backend/.venv`:
`python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt`
(requirements pin Python-3.12+ syntax — `StrEnum`, `datetime.UTC` — so the system Python 3.9 will not work.)

End-to-end checks require a running dev server and local Chrome (they use `playwright-core` pointed at `/Applications/Google Chrome.app`):

```bash
node scripts/flow-check.mjs     # onboarding → cost → funding → documents → chat happy path
node scripts/visual-check.mjs   # 5 viewports × public routes, screenshots to artifacts/visual/
```

Both exit non-zero on failure. `flow-check.mjs` asserts the **no-key safe states** (empty candidate list, empty funding list, AI fallback message), so it passes on a machine with no API keys and *fails* if placeholder data is ever introduced.

Kakao map key rotation has dedicated tooling: `npm run config:update-kakao-map-key` (atomic single-assignment `.env` edit that never echoes the value), then `npm run check:kakao-sdk` / `npm run check:kakao-build-assets`. See `.kiro/specs/kakao-map-key-fix/` for the requirements/design/tasks driving them.

The demo listing data (`data/listings.seoul.json`) and the 정책/공고 knowledge index are built offline via
`npm run pipeline:collect` / `pipeline:build` / `pipeline:verify` (Node + `backend/.venv/bin/python`) and
`npm run pipeline:policy-index`; `npm run seed:listings` pushes the built listings to Supabase when configured.
`config/policy-params.json` (loan terms, industry cost ratios) is **not** produced by this pipeline — it is
hand-curated against public sources and edited directly; see its `verified` convention under 부록 A rule 1 below.

## Architecture

Two processes behind one origin. Next.js `rewrites()` in `next.config.ts` proxies `/api/v1/*` to `BACKEND_INTERNAL_URL` (default `http://127.0.0.1:8000`), so the browser only ever talks to port 4173 and cookies stay first-party. In production nginx (`deploy/ter-doctor.conf`) does the same split; two systemd units in `deploy/` run the pair.

### Auth: anonymous sessions only

There are no user accounts. `POST /api/v1/sessions/anonymous` mints a random token, stores only `hmac_sha256(ANON_TOKEN_PEPPER, token)`, and sets an httponly cookie — `td_anon` in dev, `__Host-td_anon` in production. Every protected route resolves the session via the `current_session` dependency and then scopes the query by owner (`owned_case`, `owned_document`). Sessions expire after `ANONYMOUS_SESSION_HOURS` (24). Login/Supabase-auth code was deliberately removed; do not reintroduce a user table.

### Backend (`backend/app/`)

`main.py` is a flat FastAPI app wiring module-level singletons — no DI container, no routers. The dependency chain is:

- `config.py` — pydantic-settings `Settings`, all integrations default to empty string; `supabase_configured` is the only derived flag.
- `repository.py` — case/session persistence. **Dual-mode**: uses Supabase REST when `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` are set, otherwise an in-memory dict guarded by an `RLock`. Optimistic concurrency via `If-Match` header → `VersionError` → HTTP 409.
- `services.py` — `LocationService` (Kakao Local keyword search; kept for the legacy candidate-index path, no longer wired to `/locations/search`), `AnalysisService` (produces grade `C` context signals or a `U` block — grades `A`/`B` are modeled but nothing in this codebase populates them yet), `CostService` (pure arithmetic), `AIService` (OpenAI Responses API, `store=False`; owns both `explain()` for chat and `interpret_conditions()` for the condition-interpretation endpoint below).
- `listings.py` — `ListingService`, the demo candidate source behind `/locations/search`, `/listings/summary`, and `/listings`. Dual-mode like `repository.py`: Supabase when configured, otherwise the committed seed `data/listings.seoul.json`. Every candidate carries a fixed grade-`C` `demo-badge` provenance — these are not real listings.
- `funding.py` — pure arithmetic, no I/O. `compute_capacity()` (자기자본선·차입 여력·최대 조달선 from the financial profile alone) is split out from `compute_bands()` (the three funding bands + break-even) because capacity needs only the profile while a band's `RECOMMENDED` ceiling needs a stress test over an industry's cost ratios — `compute_bands()` calls `compute_capacity()` internally so the two screens never disagree on the maximum line.
- `policy_params.py` — `PolicyParams` loads `config/policy-params.json` and refuses to invent a value: `missing()`/`missing_of()` report unset entries (→ `integration_pending`), `unverified()`/`unverified_of()` report entries explicitly marked `verified: false` (→ `parameter_status: "DEMO"`, see 부록 A rule 1 below).
- `condition_parse.py` — the rule-based free-text → condition extractor (a server-side port of the deleted `lib/parse-case.ts`), returning `{value, evidence}` per field so the confirm screen can quote the source span. `amount_from()` is the sole place that turns a matched span into 원 — the AI path reuses it rather than trusting a model-supplied number. `_district()` does first-match-wins scanning over `districts.SEOUL_DISTRICTS`, which is why that tuple's order is load-bearing (see below).
- `condition_interpret.py` — `sanitize()`, the single gate both the AI and rule extraction paths pass through before a proposed condition reaches the client. It never raises — every input shape, valid or not, falls through to an empty/partial proposal — because it is the containment boundary for model output and its caller (`POST /conditions/interpret`) has no other error handling around it. Its core check is that a field's `evidence` must be a literal substring of the user's sentence; a value without a matching span in the original text is dropped, not repaired.
- `districts.py` — the single source for `SEOUL_DISTRICTS`, used by `main.py`, `chat_tools.py`, and `condition_interpret.py` so the three enforce the same Seoul scope. It is an **ordered tuple, not a set, on purpose**: `condition_parse._district()` scans it first-match-wins, and when this was a `frozenset` the same two-district sentence (e.g. "강남구에서 하다가 마포구로 이전") resolved to a different district depending on the process's string-hash seed. Do not "optimize" it back to a set.
- `document_store.py` — PDF bytes + JSON sidecar on disk at `DOCUMENT_STORAGE_DIR`, 0700/0600, atomic tmp-then-rename; `render_case_pdf` builds the PDF with reportlab.
- `models.py` — pydantic request/response models; the analysis discriminated union lives here and mirrors `lib/types.ts`.
- `mcp_client.py` — owns configuration and availability gating for a `presale-mcp` stdio subprocess (npm OSS package: Kakao Local, 청약홈, K-apt, 국토부 실거래가, 네이버 지도). `MCPClient` holds no session; `client.session()` returns a turn-scoped `MCPSession` opened and closed inside one `async with`, in the same task, every turn — there is no `client.call()` and no warm/shared session. This isn't a style choice: `stdio_client`/`ClientSession` each open an anyio cancel scope, and anyio requires the task that opened a scope to close it, so a session shared across turns/tasks raises `RuntimeError` on the first restart under concurrency. Timeouts wrap a **single leaf await** (`initialize()` or `call_tool()`) in `anyio.fail_after`, never `asyncio.wait_for` and never around the whole handshake — both alternatives were tried against a real subprocess and both break (`wait_for` schedules a new asyncio Task and loses cleanup on cancellation; `fail_after` around the multi-step handshake raises the same cross-scope error when the deadline fires mid-handshake). Every startup/call failure collapses to `MCPUnavailable`.
- `chat_tools.py` — `ChatToolset` wraps presale-mcp's raw primitives into 6 product-level tools exposed to the model. The model never supplies a coordinate: `resolve_seoul_place` is the only tool that resolves one, returning an opaque `place_ref` from a turn-scoped `PlaceRegistry`; every other tool takes `place_ref`, not lat/lng. This exists because `get_geocode` is one-way (address → coordinate only), so an arbitrary model-supplied coordinate could never be checked for Seoul-district membership — the guard has to sit before a coordinate is trusted, not after. `ChatToolset.run()` is a total containment boundary: every handler failure (bad place_ref, MCP transport error, unexpected exception) returns a status dict, never raises.
- `chat_stream.py` — `ChatStreamer` drives the function-calling loop behind `POST /cases/{id}/messages/stream` and yields SSE-shaped events (`turn_start`, `tool_start`, `tool_end`, `delta`, `done`, `error`). Bounded at 4 rounds and 12 raw tool calls per turn; exceeding either ends the turn with a partial answer plus citations collected so far, never a hang or a 500.

`store.py`, `security.py`, `errors.py`, and `integrations.py` are a **disconnected legacy cluster** — nothing in `main.py` imports them. They contain a richer Supabase store (idempotency keys, kill switches, SSE stream events) written against the older spec. Don't extend them without first deciding to wire them in; don't assume they run.

`GET /api/v1/analyses/{id}` is intentionally a 404 stub — analyses are addressed through the candidate/case pair, not fetched standalone.

### Frontend (`app/`, `components/`, `lib/`)

App Router, all pages thin. Two parallel client experiences share the same backend: `components/Workspace.tsx`, mounted from the catch-all route `app/cases/[caseId]/[[...section]]/page.tsx` with stage switching (`explore` / `analysis` / `cost` / `funding` / `documents` / `execution`) pushed to the URL via `history.pushState`; and the KB-redesigned workspace under `components/kb/`, mounted from `app/kb/page.tsx` → `KbShell.tsx`, described below.

`components/kb/` is driven entirely by `lib/use-jarimaegim.ts`'s `useJarimaegim()` hook, which owns all state so `JarimaegimPanel.tsx` (the step UI), `KbMap.tsx`, and the map/chat views render off one source. Its `FlowStep` union is `"profile" | "capacity" | "ask" | "confirm" | "recommend" | "prescribe"`, but `JarimaegimPanel.tsx`'s stepper shows only four positions — 자금 · 조건 · 입지 · 처방 — via the `STEP_OF` map that folds `profile`+`capacity` into ① and `ask`+`confirm` into ②. 금융 프로필 is step ①, not a gate outside the stepper: confirming it (`confirmProfile`) calls `POST /funding-capacity` and lands on the `capacity` screen, which shows 자기자본선·차입 여력·최대 조달선 and explains that 권장 조달선 needs 업종 and 희망 월세 (`recommended_line_pending`) rather than leaving it blank. `lib/profile-storage.ts` persists the confirmed profile in `localStorage` so a returning visit skips straight to `capacity`. Step ② (`ask`/`confirm`) takes no financial input at all — `interpret()` calls `POST /conditions/interpret` and the `confirm` screen shows each proposed field's value next to its evidence quote and source label (AI 추론 / 규칙 추출 / 직접 입력).

`lib/api.ts` is the only fetch layer: `credentials: "include"`, JSON bodies, `Idempotency-Key` on every mutation, and errors normalized into `ApiError { code, message, status, retryable }` from the backend's `{ error: {...} }` envelope. Never call `fetch` against `/api/v1` directly from a component. `chatStream()` in this file drives the SSE chat endpoint via `fetch` + `response.body.getReader()` — `EventSource` is unusable there since it supports neither POST nor custom headers. `lib/sse.ts` is the pure SSE frame parser it calls into, unit-tested standalone the same way `scripts/*.test.mjs` tests the Kakao scripts.

`lib/types.ts` is the live type surface, snake_case and aligned field-for-field with `backend/app/models.py`. **`lib/domain.ts` is stale** — camelCase, Zod-based, uses `PREPARING` where the live enum is `PRE_OPEN`, and is imported by nothing. Ignore it or delete it; do not use it as a reference.

Styling is plain CSS in `app/globals.css` (CSS custom properties at `:root`). Icons are `lucide-react`. No Tailwind, no CSS modules.

`index.html`, `app.js`, and `styles.css` at the repo root are the original **vanilla-JS prototype** with hardcoded demo candidates. They are not served by Next.js and are not part of the build. Never copy their fixture data into the app.

## Non-negotiable product rules

These come from 부록 A of the dev spec and are enforced throughout the code. Violating them is a correctness bug, not a style preference.

1. **Never fabricate data.** If an API key or a verified endpoint URL is missing, return an explicit `integration_pending` / empty state with an explanatory message. `ListingService` falls back to the committed seed file rather than fabricating listings, and every candidate it returns is tagged as demo data. The empty-state UI is the deliverable, not a placeholder.

   `config/policy-params.json`의 각 항목은 `verified: true | false`를 명시한다. `false`인 값으로
   계산한 결과는 `parameter_status: "DEMO"`와 `unverified_params`를 응답에 실어 보내고, UI가
   `시연용` 배지를 끌 수 없게 붙인다. 값을 숨기는 대신 값의 성격을 밝히는 방식이며, 시연용 매물
   데이터(`data/listings.seoul.json`)가 `demo-badge`를 다는 것과 같은 취급이다. 새 파라미터를
   등록할 때 `verified`를 빠뜨리면 `test_shipped_entries_state_verification_explicitly`가 막는다.
2. **Evidence grades A/B/C/U are a contract.** `A` = individual-history survival estimate (probability range + horizon), `B` = trade-area risk grade, `C` = context signals only, `U` = blocked with `blocked_reason` + `required_actions`. Individual survival grades and survival/closure probabilities may appear **only** under `A` — never in API, UI, or PDF for B/C/U. The union is enforced at three layers: `models.py`, `lib/types.ts`, and the `switch` in `EvidenceContract`/`AnalysisContract` (which ends in `assertNever`). Nothing in this codebase currently produces `A` or `B` — `AnalysisService` and `ListingService` only ever emit `C` (or `U` when a candidate can't be confirmed) — but the contract still gates every surface so adding a real `A`/`B` source later can't leak survival numbers into `C`.
3. **Every data surface shows provenance.** `Provenance` carries source name, as-of date, industry scope, spatial unit, confidence, and limitations; `components/ProvenanceBar.tsx` renders it. A new result type needs a provenance object.
4. **AI explains, code calculates.** `AIService.explain` is prompted to invent no numbers, scores, costs, or eligibility. `POST /cases/{id}/messages` (and the streaming `/messages/stream`) reject `confirmed_case_patch` with 422 — the chat can never mutate case conditions. Cost math lives in `CostService` and is a plain sum of user-entered values. The same rule binds the chat's MCP tools in `chat_tools.py`: they are read-only lookups against Kakao/청약홈/K-apt/국토부/네이버, and the model may quote what a tool returned verbatim but must not compute sums, unit conversions, per-pyeong prices, or rates of change from them — that arithmetic, if ever needed, belongs in code, not the prompt.

   `POST /api/v1/conditions/interpret`도 같은 규칙 아래 있다. 모델은 사용자 발화의 어느 구간이
   어떤 조건을 말하는지 지목할 뿐이고, 금액 환산을 포함한 모든 산술은 `condition_parse.amount_from`이
   한다. `condition_interpret.sanitize`가 evidence를 사용자 원문의 부분문자열로 검증해 통과하지
   못한 필드를 버리므로, 프롬프트를 어긴 값은 응답에 남지 않는다.
5. **Gated features stay off.** `FINANCIAL_APPLICATION_ENABLED`, `CONSULTATION_TRANSFER_ENABLED`, `MYDATA_ENABLED` default to `false` and are surfaced through `GET /api/v1/status`. Real applications, MyData, and consultation hand-off are not implemented.
6. Scope is **Seoul's 25 자치구 only** — validated server-side in `main.py`, `condition_interpret.py`, and `chat_tools.py` against `districts.SEOUL_DISTRICTS`, and client-side from `lib/constants.ts`. The chat's `resolve_seoul_place` tool enforces the same scope before any other tool call runs.

The daily AI-turn limit (`ai_daily_request_limit`, `repository.consume_daily_turn`) is enforced for `/messages/stream`, but the counter is process-local even when `repository.py` is in Supabase mode — it does not hold across multiple workers or survive a restart. `GET /api/v1/status` surfaces this under `limits.chat_daily_turns` (`scope: "process_local"`) rather than presenting the limit as a real cross-worker guarantee.

## Conventions

- All user-facing strings are Korean; keep the existing plain, non-promissory register ("확인 필요", "보장하지 않습니다"). Code identifiers and comments are English.
- The codebase is written in a deliberately dense style — multiple statements per line, single-line components. Match it in the file you're editing rather than reformatting.
- Supabase migrations in `supabase/migrations/` are applied in filename order; `supabase/archive/` is history and must not be applied.
- `.env` is gitignored; `.env.example` documents every key. Endpoint URL variables are intentionally blank — leave them blank unless the provider contract has actually been verified.
