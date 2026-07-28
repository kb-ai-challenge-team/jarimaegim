from __future__ import annotations
import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from .chat_stream import ChatStreamer, StreamLimits
from .chat_tools import ChatToolset, PlaceRegistry
from .config import get_settings
from .document_store import DocumentStore, render_case_pdf, selection_note
from .funding import compute_bands
from .knowledge import EMPTY_PRODUCTS, EMPTY_PROGRAMS, KnowledgeReader
from .listings import ListingService
from .mcp_client import MCPClient, MCPUnavailable
from .models import (AnalysisCreate, BandLine, BreakEven, CaseCreate, CasePatch, CaseRecord, CostPlanCreate,
                     DocumentCreate, FundingBandInput, FundingBandResult, FundingFacts, LocationSearch, MessageCreate,
                     PrivacyRequestCreate, Provenance, RetrievalResponse, SessionCreate)
from .policy_params import PolicyParams
from .repository import Repository, VersionError
from .retrieval import RetrievalService
from .industry import resolve as resolve_industry
from .services import AIService, AnalysisService, CostService, LocationService
from .trade_area import TradeAreaService, TradeAreaUnavailable

logger = logging.getLogger(__name__)

settings = get_settings()
repository = Repository(settings)
locations = LocationService(settings)
trade_areas = TradeAreaService()
listings_service = ListingService(settings, trade_areas=trade_areas)
analyses = AnalysisService(listings_service, trade_areas)
knowledge = KnowledgeReader(settings)
retrieval = RetrievalService(settings)
ai = AIService(settings)
mcp_client = MCPClient(settings)
document_store = DocumentStore(settings.document_storage_dir)
policy_params = PolicyParams.load(settings.policy_params_path)

app = FastAPI(title="자리매김 API", version="1.0.0", docs_url="/api/v1/docs" if settings.app_env != "production" else None, redoc_url=None, openapi_url="/api/v1/openapi.json" if settings.app_env != "production" else None)
app.add_middleware(CORSMiddleware, allow_origins=[settings.app_origin], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Idempotency-Key", "If-Match", "Last-Event-ID"])

SEOUL_DISTRICTS = {"종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구", "서초구", "강남구", "송파구", "강동구"}


def error_payload(code: str, message: str, request_id: str, retryable: bool = False, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "request_id": request_id, "retryable": retryable, "details": details or {}}}


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    details = {"fields": [{"path": ".".join(str(part) for part in error["loc"]), "message": error["msg"]} for error in exc.errors()]}
    return JSONResponse(status_code=400, content=error_payload("VALIDATION_ERROR", "입력값을 확인해 주세요.", request.state.request_id, details=details))


@app.exception_handler(HTTPException)
async def http_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        detail = exc.detail
        content = error_payload(detail["code"], detail["message"], request.state.request_id, detail.get("retryable", False), detail.get("details"))
    else:
        content = error_payload("REQUEST_FAILED", str(exc.detail), request.state.request_id)
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


def token_hash(token: str) -> str:
    return hmac.new(settings.anon_token_pepper.encode(), token.encode(), hashlib.sha256).hexdigest()


def cookie_name() -> str:
    return "__Host-td_anon" if settings.app_env == "production" else "td_anon"


async def current_session(request: Request, td_anon: str | None = Cookie(default=None), host_anon: str | None = Cookie(default=None, alias="__Host-td_anon")) -> UUID:
    token = host_anon or td_anon
    if not token:
        raise HTTPException(401, {"code": "AUTH_REQUIRED", "message": "익명 세션을 먼저 시작해 주세요."})
    session_id = repository.verify_session(token_hash(token))
    if not session_id:
        raise HTTPException(401, {"code": "AUTH_REQUIRED", "message": "세션이 만료되었습니다. 다시 시작해 주세요."})
    return session_id


def owned_case(session_id: UUID, case_id: UUID) -> CaseRecord:
    case = repository.get_case(session_id, case_id)
    if not case:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "케이스를 찾을 수 없습니다."})
    return case


def owned_document(session_id: UUID, document_id: UUID) -> dict[str, Any]:
    document = document_store.get(document_id)
    if not document or document.get("owner_session_id") != str(session_id):
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "문서를 찾을 수 없습니다."})
    return document


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}


def analysis_axes() -> dict[str, dict[str, Any]]:
    """각 분석 축의 가동 여부 (설계 스펙 §7 가드 3).

    축이 켜지려면 원천이 설정되어 있고 **그 축을 계산하는 코드가 존재해야** 한다.
    설정만 있고 구현이 없는 축을 켜면 화면이 "판정했다"고 말하게 되므로 켜지 않는다.
    """
    finlife = bool(settings.finlife_api_key and (settings.finlife_api_url or settings.finlife_api_base_url))
    subsidy = bool((settings.bizinfo_api_key and settings.bizinfo_api_url)
                   or (settings.kstartup_api_key and settings.kstartup_api_url))
    # 상권 축은 프로파일 파일이 실제로 읽혔을 때만 켠다. 키 설정 여부가 아니라
    # 판정에 쓸 집계가 메모리에 있느냐가 기준이다.
    trade_area = trade_areas.available
    trade_area_pending = "서울 상권분석 프로파일 미생성 — `npm run pipeline:trade-area` 실행 전에는 판정하지 않습니다"
    trade_area_note = f"{trade_areas.quarter} 기준 행정동 {trade_areas.dong_count}개" if trade_area else None
    return {
        "finance.band": {"enabled": True, "disabled_reason": None,
                         # 축이 켜져 있다는 것과 근거가 실측이라는 것은 다르다. 지금 등록된
                         # 제도 파라미터에는 시연용 가정값이 섞여 있고, 그 사실을 여기서도 밝힌다.
                         "note": ("대출 만기·보증한도·정책자금 한도와 업종 원가 구조가 시연용 가정값입니다 — 실제 심사 결과와 다릅니다"
                                  if policy_params.assumed("카페") else "제도 파라미터 미등록 시 integration_pending을 반환합니다")},
        "finance.stress": {"enabled": True, "disabled_reason": None, "note": None},
        "finance.kb_products": {"enabled": finlife,
                                "disabled_reason": None if finlife else "금융상품 공시 endpoint 미검증",
                                "note": "finlife는 소비자 대출만 공시합니다. 창업자금 상품 정보는 연동 대기입니다"},
        "finance.subsidy": {"enabled": subsidy,
                            "disabled_reason": None if subsidy else "지원사업 endpoint 미검증",
                            "note": "조달선 상향분 반영은 미구현입니다"},
        "location.demand": {"enabled": trade_area, "disabled_reason": None if trade_area else trade_area_pending,
                            "note": trade_area_note},
        "location.competition": {"enabled": trade_area, "disabled_reason": None if trade_area else trade_area_pending,
                                 "note": trade_area_note},
        "location.viability": {"enabled": trade_area, "disabled_reason": None if trade_area else trade_area_pending,
                               "note": "추정매출은 상권·업종 조합의 일부에만 제공되어 후보마다 판정 여부가 다릅니다" if trade_area else None},
        "location.survival": {"enabled": False, "disabled_reason": "인허가 이력 코호트 미구축", "note": "유일한 A등급 경로입니다"},
        "timing.policy": {"enabled": False, "disabled_reason": "개발·정책 일정 원천 미확보 — 일정 확인 전 판단 유보", "note": None},
    }


@app.get("/api/v1/status")
async def integration_status():
    return {"mode": settings.app_env, "integrations": {
        "supabase": settings.supabase_configured,
        "kakao_map": bool(settings.next_public_kakao_map_js_key),
        "kakao_local": bool(settings.kakao_rest_api_key),
        "openai": bool(settings.openai_api_key and settings.ai_chat_model and settings.ai_explanation_enabled),
        "retrieval": settings.retrieval_configured,
        "seoul_data": bool(settings.seoul_open_data_key and settings.seoul_commercial_api_url),
        "bizinfo": bool(settings.bizinfo_api_key and settings.bizinfo_api_url),
        "kstartup": bool(settings.kstartup_api_key and settings.kstartup_api_url),
        "finlife": bool(settings.finlife_api_key and settings.finlife_api_url),
        "ipzitalk": mcp_client.available,
    }, "feature_flags": {"financial_application": settings.financial_application_enabled, "consultation_transfer": settings.consultation_transfer_enabled, "mydata": settings.mydata_enabled},
        "knowledge_index": await knowledge.freshness(),
        "axes": analysis_axes(),
        "limits": {"chat_daily_turns": {
            # 음수는 '한도 없음'이다. 그대로 -1 을 내보내면 읽는 쪽이 한도로 오해하므로 null 로 낸다.
            "per_session": None if settings.ai_daily_request_limit < 0 else settings.ai_daily_request_limit,
            "unlimited": settings.ai_daily_request_limit < 0,
            "scope": "process_local",
            "note": "다중 워커·재시작 환경에서는 이 한도가 실제로 적용되지 않는 알려진 한계입니다 (세션별 카운터가 프로세스 메모리에만 있습니다).",
        }}}


@app.post("/api/v1/sessions/anonymous", status_code=201)
async def create_anonymous_session(payload: SessionCreate, response: Response, td_anon: str | None = Cookie(default=None), host_anon: str | None = Cookie(default=None, alias="__Host-td_anon")):
    if not payload.retention_notice_accepted:
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "유한 보유기간 고지를 확인해야 합니다."})
    existing_token = host_anon or td_anon
    if existing_token and repository.verify_session(token_hash(existing_token)):
        raise HTTPException(409, {"code": "SESSION_EXISTS", "message": "현재 익명 세션을 계속 사용합니다."})
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.anonymous_session_hours)
    session_id = repository.create_session(token_hash(token), expires_at)
    response.set_cookie(cookie_name(), token, max_age=settings.anonymous_session_hours * 3600, expires=expires_at, httponly=True, secure=settings.app_env == "production", samesite="lax", path="/")
    return {"session_id": str(session_id), "expires_at": expires_at.isoformat(), "retention_hours": settings.anonymous_session_hours}


@app.delete("/api/v1/sessions/current", status_code=202)
async def delete_current_session(response: Response, session_id: UUID = Depends(current_session)):
    response.delete_cookie(cookie_name(), path="/")
    return {"status": "queued", "deletion_job_id": str(uuid4()), "session_id": str(session_id)}


@app.post("/api/v1/cases", response_model=CaseRecord, status_code=201)
async def create_case(payload: CaseCreate, session_id: UUID = Depends(current_session)):
    if payload.inputs.district not in SEOUL_DISTRICTS:
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "현재 서울 25개 자치구만 지원합니다."})
    return repository.create_case(session_id, payload)


@app.get("/api/v1/cases/{case_id}", response_model=CaseRecord)
async def get_case(case_id: UUID, session_id: UUID = Depends(current_session)):
    return owned_case(session_id, case_id)


@app.patch("/api/v1/cases/{case_id}", response_model=CaseRecord)
async def patch_case(case_id: UUID, payload: CasePatch, if_match: int = Header(alias="If-Match"), session_id: UUID = Depends(current_session)):
    try:
        result = repository.update_case(session_id, case_id, if_match, payload)
    except VersionError as exc:
        raise HTTPException(409, {"code": "VERSION_CONFLICT", "message": "다른 변경이 먼저 저장되었습니다.", "details": {"current_version": exc.current}}) from exc
    if not result:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "케이스를 찾을 수 없습니다."})
    return result


@app.delete("/api/v1/cases/{case_id}", status_code=202)
async def delete_case(case_id: UUID, session_id: UUID = Depends(current_session)):
    if not repository.delete_case(session_id, case_id):
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "케이스를 찾을 수 없습니다."})
    return {"status": "deleting", "deletion_job_id": str(uuid4())}


@app.post("/api/v1/locations/search")
async def search_locations(payload: LocationSearch, session_id: UUID = Depends(current_session)):
    case = owned_case(session_id, payload.case_id)
    if payload.district != case.inputs.district or payload.industry != case.inputs.industry:
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "확정된 케이스 조건과 검색 조건이 다릅니다."})
    candidates, status, message = listings_service.search(
        payload.district, case.inputs.budget_krw, payload.limit,
        industry=case.inputs.industry, priority=case.inputs.priority,
    )
    return {"candidates": [candidate.model_dump(mode="json") for candidate in candidates], "status": status, "message": message}


@app.get("/api/v1/listings/summary")
async def listing_summary():
    """Public: per-district aggregate for the landing map. No session — listings are
    reference data, and browsing must not mint an anonymous cookie."""
    return {"districts": [entry.model_dump(mode="json") for entry in listings_service.summary()]}


@app.get("/api/v1/listings")
async def public_listings(district: str = Query(min_length=1, max_length=20), limit: int = Query(default=15, ge=1, le=55),
                          industry: str = Query(default="", max_length=120)):
    """Public: one district's demo listings. No session, for the same reason as the summary.

    업종은 선택이다. 랜딩 지도에서 조건 없이 둘러볼 때는 비어 있고, 그 경우 상권 판정 없이
    월세 순으로만 나간다.
    """
    if district not in SEOUL_DISTRICTS:
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "서울 25개 자치구 중에서 선택해 주세요."})
    candidates, status, message = listings_service.search(district, None, limit, industry=industry)
    return {"candidates": [candidate.model_dump(mode="json") for candidate in candidates], "status": status, "message": message}


@app.post("/api/v1/analyses")
async def create_analysis(payload: AnalysisCreate, session_id: UUID = Depends(current_session)):
    case = owned_case(session_id, payload.case_id)
    # 업종은 케이스에서 읽는다. 요청 본문으로 받으면 확정된 조건과 다른 업종의 상권 통계를
    # 붙일 수 있고, 그건 사용자가 확인한 조건이 아니다.
    return analyses.analyze(payload.candidate_id, case.inputs.industry).model_dump(mode="json")


@app.get("/api/v1/analyses/{analysis_id}")
async def get_analysis(analysis_id: UUID, session_id: UUID = Depends(current_session)):
    raise HTTPException(404, {"code": "NOT_FOUND", "message": "분석 결과 저장소 연결 전입니다."})


@app.post("/api/v1/cost-plans")
async def create_cost_plan(payload: CostPlanCreate, session_id: UUID = Depends(current_session)):
    case = owned_case(session_id, payload.case_id)
    return CostService.calculate(payload, case.inputs.equity_krw)


@app.post("/api/v1/funding-bands", response_model=FundingBandResult)
async def create_funding_bands(payload: FundingBandInput, session_id: UUID = Depends(current_session)):
    owned_case(session_id, payload.case_id)
    missing = policy_params.missing(payload.industry)
    if missing:
        return FundingBandResult(status="integration_pending", missing_params=missing,
                                 message="조달 밴드 계산에 필요한 제도·업종 파라미터가 아직 등록되지 않았습니다. 등록 전에는 추정하지 않습니다.")
    fields = payload.model_dump(exclude={"case_id"})
    try:
        computed = compute_bands(policy_params, **fields)
    except ValueError as error:
        raise HTTPException(422, {"code": "VALIDATION_FAILED", "message": f"업종 파라미터로는 손익분기를 계산할 수 없습니다: {error}"})
    first = computed["bands"][0]
    partial = computed["required_capital_krw"] is None
    missing_capital = [name for name, value in (("희망 평수", payload.area_pyeong), ("희망 보증금", payload.deposit_krw))
                       if value is None]
    # 값이 등록돼 있다는 것과 근거가 있다는 것은 다르다. 시연용 가정값이 하나라도 계산에
    # 들어갔으면 그 사실이 화면까지 따라가야 한다 — 조달선과 목표 일매출은 사용자가 가장
    # 구체적인 숫자로 받아들이는 값이라, 근거의 성격을 감추면 가장 크게 오해된다.
    assumed = policy_params.assumed(payload.industry)
    assumptions = [f"원가율·인건비율·평당 인테리어 단가는 등록된 업종 파라미터를 사용했습니다 (출처: {', '.join(policy_params.sources(payload.industry)) or '미기재'})",
                   f"운전자금 {int(policy_params.value('working_capital.months'))}개월분을 필요자금에 포함했습니다"
                   if not partial else f"{' · '.join(missing_capital)}을 입력하지 않아 필요자금과 현금소진은 계산하지 않았습니다",
                   ("인테리어비는 평수 기준 추정값입니다" if computed["fitout_is_estimate"] else "인테리어비는 사용자 입력값입니다")
                   if computed["fitout_krw"] is not None else "인테리어비는 평수를 입력해야 추정합니다",
                   "최대 조달선은 신용평가·보증 심사 전 추정치이며 확정 한도가 아닙니다"]
    limitations = ["상권별 임대 수준 데이터가 없어 밴드별 진입 가능 상권 수는 제공하지 않습니다",
                   "지원사업·창업자금 상품 반영분은 연동 대기 상태입니다"]
    if assumed:
        warning = (f"대출 만기·보증한도·정책자금 한도와 업종 원가 구조는 시연용 가정값입니다({len(assumed)}개 항목). "
                   "공고 원문으로 확인한 값이 아니므로 아래 조달선·목표매출은 실제 심사 결과와 다릅니다.")
        assumptions.insert(0, warning)
        limitations.insert(0, warning)
    else:
        limitations.append("제도 파라미터는 실측 검증 전 등록값입니다")
    if partial:
        limitations.insert(0, f"{' · '.join(missing_capital)}을 입력해야 필요자금과 현금소진을 계산합니다. 추정하지 않습니다")
    provenance = Provenance(source_name="자리매김 조달 밴드 계산",
                            industry_scope=policy_params.industry_label(payload.industry),
                            spatial_unit="사용자 입력 조건", source_as_of=policy_params.updated_at,
                            # 가정값이 섞이면 LOW 로도 부족하다. 값이 있다는 이유로 신뢰도가
                            # 올라가 보이면 안 되므로 근거 없음에 해당하는 등급으로 내린다.
                            confidence="INSUFFICIENT" if assumed else "LOW", limitations=limitations)
    return FundingBandResult(status="partial" if partial else "computed",
                             required_capital_krw=computed["required_capital_krw"],
                             required_capital_band=computed["required_capital_band"],
                             missing_params=missing_capital if partial else [],
                             message=f"{' · '.join(missing_capital)}을 입력하면 현금소진까지 계산합니다." if partial else None,
                             bands=[BandLine(**band) for band in computed["bands"]],
                             break_even=BreakEven(monthly_fixed_cost_krw=first["monthly_fixed_cost_krw"],
                                                  target_monthly_revenue_krw=first["target_monthly_revenue_krw"],
                                                  target_daily_revenue_krw=first["target_daily_revenue_krw"],
                                                  contribution_margin_ratio=computed["contribution_margin_ratio"],
                                                  assumptions=assumptions),
                             provenance=provenance)


@app.get("/api/v1/programs")
async def list_programs(case_id: UUID = Query(), session_id: UUID = Depends(current_session)):
    owned_case(session_id, case_id)
    items = await knowledge.programs()
    return {"items": items, "status": "success" if items else "integration_pending",
            "message": None if items else EMPTY_PROGRAMS}


@app.get("/api/v1/programs/catalog")
async def list_program_catalog(session_id: UUID = Depends(current_session)):
    """Case-independent view of the same official notices — the 정책 tab browses them without a case."""
    items = await knowledge.programs()
    return {"items": items, "status": "success" if items else "integration_pending",
            "message": None if items else EMPTY_PROGRAMS}


@app.get("/api/v1/products/kb")
async def list_kb_products(session_id: UUID = Depends(current_session)):
    items = await knowledge.kb_products()
    return {"items": items, "status": "success" if items else "integration_pending",
            "message": None if items else EMPTY_PRODUCTS}


@app.get("/api/v1/products")
async def list_products(case_id: UUID = Query(), session_id: UUID = Depends(current_session)):
    owned_case(session_id, case_id)
    items = await knowledge.kb_products()
    return {"items": items, "status": "success" if items else "integration_pending"}


@app.get("/api/v1/knowledge/search", response_model=RetrievalResponse)
async def search_knowledge_documents(q: str = Query(min_length=1, max_length=300),
                                     kind: str | None = Query(default=None),
                                     district: str | None = Query(default=None),
                                     limit: int = Query(default=8, ge=1, le=20),
                                     session_id: UUID = Depends(current_session)):
    """의미 검색. 유사도는 순서에만 관여하고 자격 판정은 구조화 필드 비교로만 한다."""
    if kind and kind not in ("PROGRAM", "KB_PRODUCT"):
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "알 수 없는 문서 종류입니다."})
    if district and district not in SEOUL_DISTRICTS:
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "서울 25개 자치구만 지원합니다."})
    # 서울 스코프. 전국 공고는 서울 창업자에게도 유효하므로 함께 본다.
    regions = ["서울", "전국"] if district else None
    return await retrieval.search(q, kinds=[kind] if kind else None, regions=regions, limit=limit)


def case_summary(case: CaseRecord) -> str:
    """AI에게 넘길 케이스 요약.

    확정한 후보가 있고 그 후보의 상권 집계를 확인했다면 그 **수치까지** 넣는다. 넣지 않으면
    모델이 아는 것이 업종·지역뿐이라 상권 이야기를 하려 할 때 지어낼 수밖에 없다.
    수치는 전부 코드가 계산해 여기에 문자열로 박히고, 모델은 그것을 설명만 한다
    (부록 A 불변조건 4).
    """
    parts = [f"업종 {case.inputs.industry}", f"지역 {case.inputs.district}",
             f"사업단계 {case.inputs.business_stage.value}"]
    listing_id = case.inputs.committed_listing_id
    candidate = listings_service.get(listing_id) if listing_id else None
    if candidate:
        found = trade_areas.lookup(candidate.admin_dong_code, resolve_industry(case.inputs.industry))
        if not isinstance(found, TradeAreaUnavailable):
            signals = trade_areas.signals(found)
            parts.append(
                f"확정 후보 {candidate.name}({found['admin_dong']}) — 서울시 상권분석서비스 {trade_areas.quarter} 기준, "
                f"{found['industry_name']} 점포 {found['store_count']}곳, 상권 위험 수준 {trade_areas.risk_grade(signals)}"
            )
            parts.extend(f"{signal.label}: {signal.explanation}" for signal in signals if signal.score_band != "UNKNOWN")
        else:
            parts.append(f"확정 후보 {candidate.name}의 상권 통계는 확인하지 못했습니다({found.reason})")
    return ". ".join(parts) + ". 위 수치는 상권·업종 집계이며 개별 점포의 생존·폐업 확률이 아닙니다. 현재 화면의 공식 출처와 수치 외에는 생성 금지."


@app.post("/api/v1/cases/{case_id}/messages")
async def create_message(case_id: UUID, payload: MessageCreate, session_id: UUID = Depends(current_session)):
    case = owned_case(session_id, case_id)
    if payload.confirmed_case_patch:
        raise HTTPException(422, {"code": "CONSENT_REQUIRED", "message": "이 화면에서는 대화의 조건 변경을 자동 적용하지 않습니다."})
    return await ai.explain(payload.content, case_summary(case))


def sse_frame(event: dict[str, Any]) -> str:
    # default=str: a tool result payload originates from an upstream MCP server this backend does
    # not control, so it is never guaranteed to be built only from JSON-native types. Coercing
    # anything json.dumps would otherwise reject (e.g. a stray Decimal) to its str() representation
    # keeps this frame emittable instead of raising mid-stream, after headers are already sent and
    # an HTTPException can no longer do anything useful.
    return f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False, default=str)}\n\n"


_HEARTBEAT_DONE = object()


async def heartbeat_frames(source, interval_s: float = 15.0):
    """Keeps idle proxies (nginx, browser) from dropping a long tool-calling turn: `create_message_
    stream`'s `frames()` can sit silent for up to 8s per tool call across 4 rounds between a
    `tool_start` and its `tool_end`, and a comment line (`: ping`, ignored by every SSE client) is
    enough to keep the socket warm.

    Deliberately NOT the naive `asyncio.ensure_future(iterator.__anext__())`-per-item shape: that
    calls `source.__anext__()` from inside a *freshly created task* every single time, and
    `source` here is `frames()`, which holds `async with mcp_client.session()` open across many
    `yield`s. anyio's cancel scopes (opened inside `MCPSession.__aenter__`, closed inside
    `MCPSession.__aexit__`) require the exact same asyncio task to enter and exit them -- see
    mcp_client.MCPSession's own docstring on this. Advancing `frames()` from a different task each
    time reproduces exactly that "Attempted to exit cancel scope in a different task than it was
    entered in" RuntimeError (confirmed with a standalone repro against a real anyio.CancelScope
    before writing this). Driving `source` from one single long-lived `pump` task instead -- and
    funneling its output through a queue that this generator's own task reads with a timeout --
    keeps `source` single-task for its whole lifetime, heartbeats or not.

    Cancellation/cleanup: if the consumer stops early (client disconnect cancels the request task,
    which reaches this generator via `aclose()`/an injected exception), `finally` cancels `pump`
    and *awaits* it -- not fire-and-forget -- so `source`'s own cleanup (tearing down the MCP
    subprocess) has actually run by the time this generator finishes unwinding. An un-awaited
    `.cancel()` only schedules cancellation; it does not guarantee delivery before the caller
    moves on, which is exactly how an abandoned request would leak an `npx` subprocess. See
    test_a_disconnected_consumer_still_lets_the_source_clean_up for the regression check, and the
    scratch repro referenced in the Task 11 report showing the un-awaited variant leaves
    `cleanup_ran` False even one event-loop tick after `aclose()` returns.

    No frame is ever dropped mid-flight: `pump` puts every item from `source` onto the queue as
    soon as it is produced, and a heartbeat timeout only ever races a `queue.get()`, never
    `source.__anext__()` itself -- so an item already sitting in the queue is never in danger of
    being lost to a timeout-driven cancellation the way a bare `pending` task's result would be.

    `pump` only catches `Exception`, never `BaseException`: a genuine `CancelledError` must
    propagate out of `pump`'s task untouched so `task.cancel()` composes correctly, matching the
    same rule `MCPSession.call()` applies for the same reason. In practice `frames()` already
    catches every `Exception` itself and always yields a well-formed `error`/`done` frame before
    returning (see its own `except Exception` clause) -- so the `except Exception` branch below is
    a defensive fallback for a bug that slipped past that boundary, not the expected path. If it
    ever fires, it re-raises here rather than fabricating a synthetic SSE frame of its own: this
    generic wrapper doesn't know the app's frame shape and must not guess at one."""
    queue: asyncio.Queue = asyncio.Queue()

    async def pump() -> None:
        try:
            async for item in source:
                await queue.put(item)
        except Exception as exc:  # noqa: BLE001 -- see docstring: re-raised verbatim below, never fabricated.
            await queue.put(("__heartbeat_error__", exc))
        else:
            await queue.put(_HEARTBEAT_DONE)

    task = asyncio.ensure_future(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval_s)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if item is _HEARTBEAT_DONE:
                return
            if isinstance(item, tuple) and len(item) == 2 and item[0] == "__heartbeat_error__":
                raise item[1]
            yield item
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@app.post("/api/v1/cases/{case_id}/messages/stream")
async def create_message_stream(case_id: UUID, payload: MessageCreate, session_id: UUID = Depends(current_session)):
    # Ownership, then consent, then the metered daily-turn consumption -- in that order, so a
    # request that was always going to be refused (unknown/foreign case, or an attempted case-patch)
    # never spends a turn out of the session's daily budget first.
    case = owned_case(session_id, case_id)
    if payload.confirmed_case_patch:
        raise HTTPException(422, {"code": "CONSENT_REQUIRED", "message": "이 화면에서는 대화의 조건 변경을 자동 적용하지 않습니다."})
    if not repository.consume_daily_turn(session_id, settings.ai_daily_request_limit):
        raise HTTPException(429, {"code": "RATE_LIMITED", "message": "오늘 사용할 수 있는 AI 대화 횟수를 모두 사용했습니다."})

    summary = case_summary(case)
    responder = ai.responder()

    async def frames():
        # Everything below runs after the 200 + SSE headers are already on the wire, so an
        # HTTPException here would do nothing useful -- every failure path (including a bug we
        # didn't anticipate) must end in an `error` SSE event instead of an unhandled exception
        # that would just truncate the stream.
        try:
            if responder is None:
                yield sse_frame({"event": "turn_start", "data": {"tools_available": False}})
                yield sse_frame({"event": "done", "data": {
                    "message": "AI 설명 키가 아직 설정되지 않았습니다. 후보와 분석 화면의 저장된 공식 근거는 계속 확인할 수 있습니다.",
                    "citations": [], "integration_status": "not_configured"}})
                return

            if mcp_client.available:
                # The MCP session is turn-scoped by design (see MCPSession's docstring): it must be
                # opened, used for every tool call, and closed inside one `async with` in the same
                # task -- this generator's task -- never handed out to live across turns. So the
                # toolset can only be constructed here, wrapping the whole streamer.run() loop,
                # rather than once at module scope alongside `mcp_client` itself.
                try:
                    async with mcp_client.session() as mcp_session:
                        toolset = ChatToolset(mcp_session, PlaceRegistry())
                        streamer = ChatStreamer(responder, toolset, StreamLimits())
                        async for event in streamer.run(payload.content, summary):
                            yield sse_frame(event)
                        return
                except MCPUnavailable as exc:
                    # Spawn/handshake failed (e.g. npx missing, presale-mcp misbehaving). The turn
                    # must still produce a complete, valid stream -- degrade to a tools-free turn
                    # rather than a 500 or a stream that stops mid-way.
                    logger.warning("ipzitalk MCP 세션을 열지 못해 도구 없이 진행합니다: %s", type(exc).__name__)

            streamer = ChatStreamer(responder, None, StreamLimits())
            async for event in streamer.run(payload.content, summary):
                yield sse_frame(event)
        except Exception as exc:
            # Containment boundary of last resort, mirroring chat_tools.ChatToolset.run(): log only
            # the exception type, never its message or any request content, and never let it escape
            # as a raw, stream-truncating crash.
            logger.warning("채팅 스트림 처리 중 예기치 않은 오류: %s", type(exc).__name__)
            yield sse_frame({"event": "error", "data": {"code": "UPSTREAM_UNAVAILABLE",
                             "message": "요청을 처리하는 중 문제가 발생했습니다.", "retryable": True}})

    # No `Connection: keep-alive` header: Starlette/uvicorn already keep an HTTP/1.1 connection
    # alive by default, and the `Connection` header has no meaning on HTTP/2 (RFC 7540 forbids it
    # as a connection-specific header) -- setting it here would be a no-op at best. The `: ping`
    # comment frames from heartbeat_frames are what actually keeps idle proxies from dropping the
    # connection; a `Connection` header was never doing that job.
    return StreamingResponse(heartbeat_frames(frames(), interval_s=15.0), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def catalog_selection(payload: DocumentCreate) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, bool]:
    """고른 id 를 서버 카탈로그에서 되찾는다. 화면이 보낸 이름·금리·URL 은 쓰지 않는다.

    조회되지 않는 id 는 422 로 막지 않고 제외한 뒤 건수를 알린다 — 카탈로그가 갱신된 사이
    사용자가 갇히지 않게 하되, 조용히 자르지도 않기 위해서다.

    다만 조회 실패도 빈 목록으로 내려오므로(knowledge.py:34-40) 두 경우를 구분해서 돌려준다.
    되찾을 것이 있는데 카탈로그가 통째로 비어 왔다면 그건 'id 가 목록에 없다'가 아니라
    '목록을 못 읽었다'이고, 네 번째 값이 그 사실을 나른다.

    같은 id 를 두 번 보내도 한 번만 싣는다. 중복을 제외 건수로 세면 없는 누락을 알리게 된다.
    고르지 않은 쪽 카탈로그는 조회하지 않는다."""
    product_ids = list(dict.fromkeys(payload.selected_product_ids))
    program_ids = list(dict.fromkeys(payload.selected_program_ids))
    if not product_ids and not program_ids:
        return [], [], 0, False
    products = {item["id"]: item for item in (await knowledge.kb_products() if product_ids else []) if item.get("id")}
    programs = {item["id"]: item for item in (await knowledge.programs() if program_ids else []) if item.get("id")}
    chosen_products = [products[key] for key in product_ids if key in products]
    chosen_programs = [programs[key] for key in program_ids if key in programs]
    dropped = (len(product_ids) - len(chosen_products)) + (len(program_ids) - len(chosen_programs))
    unavailable = (bool(product_ids) and not products) or (bool(program_ids) and not programs)
    return chosen_products, chosen_programs, dropped, unavailable


FUNDING_NO_INPUT = "조달 입력이 없어 조달 요약은 넣지 않았습니다."
FUNDING_UNREGISTERED = "업종 파라미터가 등록되지 않아 조달 요약을 계산하지 못했습니다."
FUNDING_UNCOMPUTABLE = "등록된 업종 파라미터로는 손익분기를 계산할 수 없어 조달 요약을 넣지 않았습니다."


def document_funding(case: CaseRecord, facts: FundingFacts | None) -> tuple[dict[str, Any] | None, str | None]:
    """문서에 실을 조달 요약과, 없다면 그 이유. 화면이 계산한 숫자를 받지 않고 같은 산식을
    다시 돌린다 — /funding-bands 와 문서가 갈라지지 않는 유일한 방법이다.

    업종과 자기자본만은 요청이 아니라 케이스에서 가져온다. 평수·월세처럼 화면에만 있는 값과
    달리 이 둘은 케이스에 이미 확정값이 있고, 요청 값을 그대로 쓰면 문서의 '사용자 확인값'
    블록과 바로 아래 조달 요약이 서로 다른 조건 위에서 계산될 수 있다."""
    if facts is None:
        return None, FUNDING_NO_INPUT
    fields = {**facts.model_dump(), "industry": case.inputs.industry, "equity_krw": case.inputs.equity_krw}
    if policy_params.missing(fields["industry"]):
        return None, FUNDING_UNREGISTERED
    try:
        computed = compute_bands(policy_params, **fields)
    except ValueError:
        return None, FUNDING_UNCOMPUTABLE
    return {**computed, "assumed": policy_params.assumed(fields["industry"]),
            "as_of": policy_params.updated_at}, None


@app.post("/api/v1/documents", status_code=201)
async def create_document(payload: DocumentCreate, session_id: UUID = Depends(current_session)):
    case = owned_case(session_id, payload.case_id)
    if not payload.confirmed:
        raise HTTPException(422, {"code": "CONSENT_REQUIRED", "message": "포함 정보를 확인한 뒤 문서를 생성해 주세요."})
    document_id = uuid4()
    descriptor = {"document_id": str(document_id), "created_at": datetime.now(UTC).isoformat(), "template": payload.template}
    funding, funding_reason = document_funding(case, payload.funding_input)
    products, programs, dropped, unavailable = await catalog_selection(payload)
    try:
        pdf = await asyncio.to_thread(render_case_pdf, case.model_dump(mode="json"), descriptor,
                                      funding=funding, products=products, programs=programs,
                                      dropped=dropped, unavailable=unavailable)
        document = document_store.save(owner_session_id=session_id, case_id=payload.case_id, template=payload.template, pdf=pdf, document_id=document_id)
    except OSError as exc:
        raise HTTPException(500, {"code": "DOCUMENT_STORAGE_FAILED", "message": "PDF를 안전하게 저장하지 못했습니다."}) from exc
    # 문서에 적힌 사실은 응답에도 같은 문장으로 나간다 — 화면이 문서를 열지 않고도
    # 무엇이 빠졌는지 그대로 말할 수 있어야 하기 때문이다.
    parts = ["PDF가 준비되었습니다. 현재 익명 세션에서 다운로드할 수 있습니다.", funding_reason,
             selection_note(dropped, unavailable)]
    return {**document, "message": " ".join(part for part in parts if part)}


@app.get("/api/v1/documents/{document_id}")
async def get_document(document_id: UUID, response: Response, session_id: UUID = Depends(current_session)):
    document = owned_document(session_id, document_id)
    response.headers["Cache-Control"] = "private, no-store"
    return {**document, "message": "PDF가 준비되었습니다."}


@app.get("/api/v1/documents/{document_id}/download")
async def download_document(document_id: UUID, session_id: UUID = Depends(current_session)):
    document = owned_document(session_id, document_id)
    path = document_store.pdf_path(document_id)
    if not path:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "PDF 파일을 찾을 수 없습니다."})
    return FileResponse(path, media_type="application/pdf", filename=f"jarimaegim-{document['template']}.pdf", headers={"Cache-Control": "private, no-store"})


@app.post("/api/v1/privacy/requests", status_code=202)
async def create_privacy_request(payload: PrivacyRequestCreate, session_id: UUID = Depends(current_session)):
    return {"request_id": str(uuid4()), "status": "RECEIVED", "request_type": payload.request_type, "subject": "ANONYMOUS", "session_id": str(session_id)}
