from __future__ import annotations
import asyncio
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from .config import get_settings
from .document_store import DocumentStore, render_case_pdf
from .funding import compute_bands
from .knowledge import EMPTY_PRODUCTS, EMPTY_PROGRAMS, KnowledgeReader
from .listings import ListingService
from .models import (AnalysisCreate, BandLine, BreakEven, CaseCreate, CasePatch, CaseRecord, CostPlanCreate,
                     DocumentCreate, FundingBandInput, FundingBandResult, LocationSearch, MessageCreate,
                     PrivacyRequestCreate, Provenance, RetrievalResponse, SessionCreate)
from .policy_params import PolicyParams
from .repository import Repository, VersionError
from .retrieval import RetrievalService
from .services import AIService, AnalysisService, CostService, LocationService

settings = get_settings()
repository = Repository(settings)
locations = LocationService(settings)
listings_service = ListingService(settings)
analyses = AnalysisService(listings_service)
knowledge = KnowledgeReader(settings)
retrieval = RetrievalService(settings)
ai = AIService(settings)
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
    trade_area_pending = "서울 상권분석 연동 미구현 — 원천 설정 여부와 무관하게 판정하지 않습니다"
    return {
        "finance.band": {"enabled": True, "disabled_reason": None,
                         "note": "제도 파라미터 미등록 시 integration_pending을 반환합니다"},
        "finance.stress": {"enabled": True, "disabled_reason": None, "note": None},
        "finance.kb_products": {"enabled": finlife,
                                "disabled_reason": None if finlife else "금융상품 공시 endpoint 미검증",
                                "note": "finlife는 소비자 대출만 공시합니다. 창업자금 상품 정보는 연동 대기입니다"},
        "finance.subsidy": {"enabled": subsidy,
                            "disabled_reason": None if subsidy else "지원사업 endpoint 미검증",
                            "note": "조달선 상향분 반영은 미구현입니다"},
        "location.demand": {"enabled": False, "disabled_reason": trade_area_pending, "note": None},
        "location.competition": {"enabled": False, "disabled_reason": trade_area_pending, "note": None},
        "location.viability": {"enabled": False, "disabled_reason": trade_area_pending, "note": None},
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
    }, "feature_flags": {"financial_application": settings.financial_application_enabled, "consultation_transfer": settings.consultation_transfer_enabled, "mydata": settings.mydata_enabled},
        "knowledge_index": await knowledge.freshness(),
        "axes": analysis_axes()}


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
    candidates, status, message = listings_service.search(payload.district, case.inputs.budget_krw, payload.limit)
    return {"candidates": [candidate.model_dump(mode="json") for candidate in candidates], "status": status, "message": message}


@app.get("/api/v1/listings/summary")
async def listing_summary():
    """Public: per-district aggregate for the landing map. No session — listings are
    reference data, and browsing must not mint an anonymous cookie."""
    return {"districts": [entry.model_dump(mode="json") for entry in listings_service.summary()]}


@app.get("/api/v1/listings")
async def public_listings(district: str = Query(min_length=1, max_length=20), limit: int = Query(default=15, ge=1, le=55)):
    """Public: one district's demo listings. No session, for the same reason as the summary."""
    if district not in SEOUL_DISTRICTS:
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "서울 25개 자치구 중에서 선택해 주세요."})
    candidates, status, message = listings_service.search(district, None, limit)
    return {"candidates": [candidate.model_dump(mode="json") for candidate in candidates], "status": status, "message": message}


@app.post("/api/v1/analyses")
async def create_analysis(payload: AnalysisCreate, session_id: UUID = Depends(current_session)):
    owned_case(session_id, payload.case_id)
    return analyses.analyze(payload.candidate_id).model_dump(mode="json")


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
    assumptions = [f"원가율·인건비율·평당 인테리어 단가는 등록된 업종 파라미터를 사용했습니다 (출처: {', '.join(policy_params.sources(payload.industry)) or '미기재'})",
                   f"운전자금 {int(policy_params.value('working_capital.months'))}개월분을 필요자금에 포함했습니다",
                   "인테리어비는 평수 기준 추정값입니다" if computed["fitout_is_estimate"] else "인테리어비는 사용자 입력값입니다",
                   "최대 조달선은 신용평가·보증 심사 전 추정치이며 확정 한도가 아닙니다"]
    provenance = Provenance(source_name="자리매김 조달 밴드 계산", industry_scope=payload.industry,
                            spatial_unit="사용자 입력 조건", source_as_of=policy_params.updated_at,
                            confidence="LOW",
                            limitations=["상권별 임대 수준 데이터가 없어 밴드별 진입 가능 상권 수는 제공하지 않습니다",
                                         "지원사업·창업자금 상품 반영분은 연동 대기 상태입니다",
                                         "제도 파라미터는 실측 검증 전 등록값입니다"])
    return FundingBandResult(status="computed", required_capital_krw=computed["required_capital_krw"],
                             required_capital_band=computed["required_capital_band"],
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


@app.post("/api/v1/cases/{case_id}/messages")
async def create_message(case_id: UUID, payload: MessageCreate, session_id: UUID = Depends(current_session)):
    case = owned_case(session_id, case_id)
    if payload.confirmed_case_patch:
        raise HTTPException(422, {"code": "CONSENT_REQUIRED", "message": "이 화면에서는 대화의 조건 변경을 자동 적용하지 않습니다."})
    summary = f"업종 {case.inputs.industry}, 지역 {case.inputs.district}, 사업단계 {case.inputs.business_stage.value}. 현재 화면의 공식 출처와 수치 외에는 생성 금지."
    return await ai.explain(payload.content, summary)


@app.post("/api/v1/documents", status_code=201)
async def create_document(payload: DocumentCreate, session_id: UUID = Depends(current_session)):
    case = owned_case(session_id, payload.case_id)
    if not payload.confirmed:
        raise HTTPException(422, {"code": "CONSENT_REQUIRED", "message": "포함 정보를 확인한 뒤 문서를 생성해 주세요."})
    document_id = uuid4()
    descriptor = {"document_id": str(document_id), "created_at": datetime.now(UTC).isoformat(), "template": payload.template}
    try:
        pdf = await asyncio.to_thread(render_case_pdf, case.model_dump(mode="json"), descriptor)
        document = document_store.save(owner_session_id=session_id, case_id=payload.case_id, template=payload.template, pdf=pdf, document_id=document_id)
    except OSError as exc:
        raise HTTPException(500, {"code": "DOCUMENT_STORAGE_FAILED", "message": "PDF를 안전하게 저장하지 못했습니다."}) from exc
    return {**document, "message": "PDF가 준비되었습니다. 현재 익명 세션에서 다운로드할 수 있습니다."}


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
