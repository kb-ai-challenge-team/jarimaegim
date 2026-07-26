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
from .models import (AnalysisCreate, CaseCreate, CasePatch, CaseRecord, CostPlanCreate, DocumentCreate,
                     LocationSearch, MessageCreate, PrivacyRequestCreate, SessionCreate)
from .repository import Repository, VersionError
from .services import AIService, AnalysisService, CostService, IntegrationError, LocationService, OfficialSourceService

settings = get_settings()
repository = Repository(settings)
locations = LocationService(settings)
analyses = AnalysisService(locations)
official_sources = OfficialSourceService(settings)
ai = AIService(settings)
document_store = DocumentStore(settings.document_storage_dir)

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


@app.get("/api/v1/status")
async def integration_status():
    return {"mode": settings.app_env, "integrations": {
        "supabase": settings.supabase_configured,
        "kakao_map": bool(settings.next_public_kakao_map_js_key),
        "kakao_local": bool(settings.kakao_rest_api_key),
        "openai": bool(settings.openai_api_key and settings.ai_chat_model and settings.ai_explanation_enabled),
        "seoul_data": bool(settings.seoul_open_data_key and settings.seoul_commercial_api_url),
        "bizinfo": bool(settings.bizinfo_api_key and settings.bizinfo_api_url),
        "kstartup": bool(settings.kstartup_api_key and settings.kstartup_api_url),
        "finlife": bool(settings.finlife_api_key and settings.finlife_api_url),
    }, "feature_flags": {"financial_application": settings.financial_application_enabled, "consultation_transfer": settings.consultation_transfer_enabled, "mydata": settings.mydata_enabled}}


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
    try:
        candidates, status, message = await locations.search(payload)
        return {"candidates": [candidate.model_dump(mode="json") for candidate in candidates], "status": status, "message": message}
    except IntegrationError as exc:
        raise HTTPException(503, {"code": "UPSTREAM_UNAVAILABLE", "message": str(exc), "retryable": True}) from exc


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


@app.get("/api/v1/programs")
async def list_programs(case_id: UUID = Query(), session_id: UUID = Depends(current_session)):
    owned_case(session_id, case_id)
    items = await official_sources.programs()
    return {"items": items, "status": "success" if items else "integration_pending", "message": None if items else "검증된 공식 API endpoint와 키가 설정되면 공고를 표시합니다."}


@app.get("/api/v1/programs/catalog")
async def list_program_catalog(session_id: UUID = Depends(current_session)):
    """Case-independent view of the same official notices — the 정책 tab browses them without a case."""
    items = await official_sources.programs()
    return {"items": items, "status": "success" if items else "integration_pending", "message": None if items else "검증된 공식 API endpoint와 키가 설정되면 공고를 표시합니다."}


@app.get("/api/v1/products")
async def list_products(case_id: UUID = Query(), session_id: UUID = Depends(current_session)):
    owned_case(session_id, case_id)
    items = [item for item in await official_sources.programs() if item["category"] == "PRIVATE"]
    return {"items": items, "status": "success" if items else "integration_pending"}


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
