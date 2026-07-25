from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, date, datetime
from io import BytesIO
from typing import Any
from urllib.parse import quote, urlparse
from uuid import UUID, uuid5, NAMESPACE_URL

import httpx
from openai import AsyncOpenAI
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors

from .config import Settings
from .errors import APIError
from .models import LocationCandidate, LocationSearchRequest, LocationSearchResponse, OfficialProgram, SEOUL_DISTRICT_NAMES


OFFICIAL_HOSTS = {
    "SEOUL": ("seoul.go.kr",),
    "BIZINFO": ("bizinfo.go.kr", "data.go.kr"),
    "KSTARTUP": ("k-startup.go.kr", "data.go.kr"),
    "FINLIFE": ("fss.or.kr",),
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _official_https(url: str, provider: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        host_allowed = any(host == suffix or host.endswith(f".{suffix}") for suffix in OFFICIAL_HOSTS[provider])
        if not host_allowed:
            return False
        if parsed.scheme == "https":
            return True
        # Seoul's official Open API currently serves this dataset over HTTP on port 8088 only.
        return provider == "SEOUL" and parsed.scheme == "http" and host == "openapi.seoul.go.kr" and parsed.port == 8088
    except (KeyError, ValueError):
        return False


class Integrations:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.upstream_connect_timeout_seconds,
                read=settings.upstream_read_timeout_seconds,
                write=settings.upstream_read_timeout_seconds,
                pool=settings.upstream_connect_timeout_seconds,
            ),
            follow_redirects=False,
            headers={"User-Agent": "jarimaegim-api/1.0"},
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def search_kakao(self, request: LocationSearchRequest) -> LocationSearchResponse:
        if not self.settings.kakao_rest_api_key:
            return LocationSearchResponse(
                status="integration_pending",
                candidates=[],
                source="NONE",
                notice={
                    "message": "Kakao Local REST 연동 키가 아직 구성되지 않았습니다. 후보를 임의 생성하지 않습니다.",
                    "required_configuration": ["KAKAO_REST_API_KEY"],
                },
            )
        district_name = SEOUL_DISTRICT_NAMES[request.district_code]
        query = request.keyword if district_name in request.keyword else f"{district_name} {request.keyword}"
        params: dict[str, Any] = {"query": query, "page": request.page, "size": request.size}
        if request.geometry and request.geometry.x is not None:
            params.update({"x": str(request.geometry.x), "y": str(request.geometry.y)})
            if request.geometry.radius_m:
                params["radius"] = request.geometry.radius_m
        try:
            response = await self.http.get(
                "https://dapi.kakao.com/v2/local/search/keyword.json",
                params=params,
                headers={"Authorization": f"KakaoAK {self.settings.kakao_rest_api_key}"},
            )
            if response.status_code == 429:
                raise APIError("RATE_LIMITED", "위치 검색 호출 한도에 도달했습니다.", 429, retryable=True, retry_after=30)
            response.raise_for_status()
            payload = response.json()
        except APIError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise APIError("UPSTREAM_UNAVAILABLE", "위치 검색 서비스에 연결할 수 없습니다.", 503, retryable=True, retry_after=30) from exc
        candidates = []
        for item in payload.get("documents", []):
            if not isinstance(item, dict) or not item.get("place_name"):
                continue
            address_text = f"{item.get('address_name', '')} {item.get('road_address_name', '')}"
            if district_name not in address_text:
                continue
            stable = item.get("id") or json.dumps(item, sort_keys=True, ensure_ascii=False)
            candidates.append(LocationCandidate(
                candidate_id=uuid5(NAMESPACE_URL, f"kakao:{stable}"),
                name=str(item["place_name"]),
                category_name=item.get("category_name") or None,
                address_name=item.get("address_name") or None,
                road_address_name=item.get("road_address_name") or None,
                x=item.get("x") or None,
                y=item.get("y") or None,
                place_url=item.get("place_url") or None,
            ))
        return LocationSearchResponse(
            status="ok", candidates=candidates, source="KAKAO_LOCAL", retrieved_at=utcnow(),
            is_end=bool(payload.get("meta", {}).get("is_end", False)),
        )

    def _provider_configuration(self, provider: str) -> tuple[str, str]:
        return {
            "SEOUL": (self.settings.seoul_commercial_api_url, self.settings.seoul_open_data_key),
            "BIZINFO": (self.settings.bizinfo_api_url, self.settings.bizinfo_api_key or self.settings.data_go_kr_service_key),
            "KSTARTUP": (self.settings.kstartup_api_url, self.settings.kstartup_api_key or self.settings.data_go_kr_service_key),
            "FINLIFE": (self.settings.finlife_api_url, self.settings.finlife_api_key),
        }[provider]

    @staticmethod
    def _expand_verified_url(template: str, key: str) -> str:
        # The full endpoint and placement placeholder must be supplied from verified provider documentation.
        value = template
        for placeholder in ("{api_key}", "{service_key}", "{key}"):
            value = value.replace(placeholder, quote(key, safe=""))
        return value

    @staticmethod
    def _record_list(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("items", "data", "records", "results", "result", "row"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = Integrations._record_list(value)
                if nested:
                    return nested
        # Seoul Open API wraps rows under a dynamic service-name key.
        for value in payload.values():
            if isinstance(value, dict):
                rows = value.get("row")
                if isinstance(rows, list):
                    return [item for item in rows if isinstance(item, dict)]
        return []

    @staticmethod
    def _first(record: dict[str, Any], names: tuple[str, ...]) -> Any:
        for name in names:
            if record.get(name) not in (None, ""):
                return record[name]
        return None

    async def fetch_programs(self) -> tuple[list[OfficialProgram], list[str]]:
        all_records: list[OfficialProgram] = []
        pending: list[str] = []
        for provider in ("BIZINFO", "KSTARTUP", "FINLIFE", "SEOUL"):
            endpoint, key = self._provider_configuration(provider)
            if not endpoint or not key:
                pending.append(provider)
                continue
            expanded = self._expand_verified_url(endpoint, key)
            if not _official_https(expanded, provider):
                pending.append(provider)
                continue
            try:
                response = await self.http.get(expanded)
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                pending.append(provider)
                continue
            for raw in self._record_list(payload):
                url = self._first(raw, ("official_url", "officialUrl", "detail_url", "detailUrl", "url", "link"))
                title = self._first(raw, ("title", "name", "program_name", "programName", "pblancNm"))
                record_id = self._first(raw, ("id", "program_id", "programId", "pblancId", "announcement_id"))
                if not url or not title or not _official_https(str(url), provider):
                    continue
                identity = str(record_id or url)
                # No amounts, rates, scores, or inferred eligibility are copied from an unverified schema.
                all_records.append(OfficialProgram(
                    program_id=uuid5(NAMESPACE_URL, f"{provider}:{identity}"), provider=provider,
                    source_record_id=identity[:200], title=str(title)[:500], official_url=str(url),
                    collected_at=utcnow(), raw_summary={},
                ))
        return all_records, pending

    async def explain_analysis(self, analysis: dict[str, Any], *, allow_ai: bool = True) -> tuple[str, str, str | None]:
        fallback = self._safe_explanation(analysis)
        if not (allow_ai and self.settings.ai_explanation_enabled and self.settings.openai_api_key and self.settings.ai_chat_model):
            return fallback, "safe_fallback", None
        prompt = (
            "당신은 자리매김 결과 설명기입니다. 입력 JSON의 값만 쉬운 한국어로 재서술하세요. "
            "새 수치, 확률, 원인, 금융 승인 가능성, 추천 순위를 만들지 마세요. B/C/U에서는 개인 생존확률을 언급하지 마세요. "
            "공식 원문 우선, 참고정보이며 보장이 아니라는 문장을 포함하세요.\nJSON:\n"
            + json.dumps(analysis, ensure_ascii=False, default=str)
        )
        try:
            client = AsyncOpenAI(api_key=self.settings.openai_api_key)
            response = await client.responses.create(model=self.settings.ai_chat_model, input=prompt, store=False)
            text = (response.output_text or "").strip()
            if not text or not self._ai_output_safe(text, analysis, allow_personal=analysis.get("evidence_grade") == "A"):
                return fallback, "safe_fallback", None
            return text, "openai", self.settings.ai_chat_model
        except Exception:
            return fallback, "safe_fallback", None

    @staticmethod
    def _safe_explanation(analysis: dict[str, Any]) -> str:
        grade = analysis.get("evidence_grade")
        if grade == "A":
            return "검증된 개별 이력 기반 결과이지만 예측 범위는 참고정보이며 실제 결과를 보장하지 않습니다. 출처와 한계를 함께 확인해 주세요."
        if grade == "B":
            return "이 결과는 상권·업종 집계 위험 신호이며 개별 점포의 생존확률이 아닙니다. 공식 출처와 기준일을 확인해 주세요."
        if grade == "C":
            return "개별 사건 자료가 부족해 맥락 정보만 제공합니다. 예측이나 성공 가능성으로 해석하지 말고 공식 원문을 우선해 주세요."
        return "현재 근거가 부족하거나 입력이 매핑되지 않아 분석을 제공하지 않습니다. 필요한 입력과 데이터 준비 상태를 확인해 주세요."

    async def render_pdf(self, case: dict[str, Any], document: dict[str, Any], analysis: dict[str, Any] | None = None) -> bytes:
        return await asyncio.to_thread(self._render_pdf_sync, case, document, analysis)

    @staticmethod
    def _render_pdf_sync(case: dict[str, Any], document: dict[str, Any], analysis: dict[str, Any] | None) -> bytes:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
            font = "HYSMyeongJo-Medium"
        except Exception:
            font = "Helvetica"
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, title="자리매김 PDF 초안", author="자리매김")
        styles = getSampleStyleSheet()
        for style in styles.byName.values():
            style.fontName = font
        story = [Paragraph("자리매김 PDF 초안", styles["Title"]), Spacer(1, 12)]
        rows = [
            ["문서 ID", str(document["document_id"])],
            ["생성 시각", str(document["created_at"])],
            ["템플릿", str(document["template"])],
            ["케이스", str(case["id"])],
            ["사용자 확인 제목", str(case["title"])],
            ["케이스 버전", str(case["version"])],
        ]
        table = Table(rows, colWidths=[110, 380])
        table.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), font), ("GRID", (0, 0), (-1, -1), .25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.extend([table, Spacer(1, 16), Paragraph("사용자 확인값", styles["Heading2"])])
        for key, value in case.get("inputs", {}).items():
            story.append(Paragraph(f"{key}: {value}", styles["BodyText"]))
        provenance = analysis.get("provenance", {}) if analysis else {}
        if analysis:
            story.extend([Spacer(1, 12), Paragraph("분석 근거", styles["Heading2"])])
            story.append(Paragraph(f"증거 등급: {analysis.get('evidence_grade')}", styles["BodyText"]))
            for key in ("source_as_of", "published_at", "collected_at", "industry_scope", "spatial_unit", "model_version"):
                story.append(Paragraph(f"{key}: {provenance.get(key) or '사용자 확인 필요'}", styles["BodyText"]))
            if analysis.get("evidence_grade") == "A":
                story.append(Paragraph(f"검증된 범위: {analysis.get('probability_lower')}~{analysis.get('probability_upper')}% / {analysis.get('horizon_months')}개월", styles["BodyText"]))
            else:
                story.append(Paragraph("개별 점포 생존확률은 제공되지 않습니다.", styles["BodyText"]))
        payload = {"provenance": provenance, "official_urls": provenance.get("official_urls", [])}
        story.append(Paragraph(f"공식 출처 URL: {', '.join(str(url) for url in payload['official_urls']) or '연결된 공식 원문 없음'}", styles["BodyText"]))
        story.extend([Spacer(1, 16), Paragraph("AI가 작성한 초안이며 사용자 검토가 필요합니다. 결과는 보장되지 않으며 공식 원문이 우선합니다. 없는 값은 사용자 확인 필요로 남깁니다.", styles["BodyText"])])
        doc.build(story)
        return buffer.getvalue()


    @staticmethod
    def _ai_output_safe(text: str, source: dict[str, Any], *, allow_personal: bool) -> bool:
        blocked_claims = ("승인 가능성", "선정 가능성", "대출 가능성", "보장됩니다", "확실합니다")
        if any(claim in text for claim in blocked_claims):
            return False
        if not allow_personal and any(claim in text for claim in ("생존확률", "폐업확률", "개인 생존등급")):
            return False
        source_numbers = set(re.findall(r"\d+(?:[.]\d+)?", json.dumps(source, ensure_ascii=False, default=str)))
        output_numbers = set(re.findall(r"\d+(?:[.]\d+)?", text))
        return output_numbers.issubset(source_numbers)

    async def chat_explanation(self, content: str, case_summary: dict[str, Any], *, allow_ai: bool = True) -> tuple[str, str, str | None]:
        fallback = "확인했습니다. 자리매김는 공식 근거가 있는 정보만 설명하며, 현재 연동되지 않은 수치나 성공·승인 가능성은 만들지 않습니다."
        if not (allow_ai and self.settings.ai_explanation_enabled and self.settings.openai_api_key and self.settings.ai_chat_model):
            return fallback, "safe_fallback", None
        minimized_content = re.sub(r"\d[\d,]*(?:[.]\d+)?(?:원|만원|억원|%)?", "[수치 생략]", content)
        prompt = (
            "당신은 자리매김의 설명 전용 도우미입니다. 계산, 점수 생성, 개인 생존확률 생성, 금융 승인 예측, 자격 확정, 추천 순위를 하지 마세요. "
            "사용자가 제공한 민감정보를 반복하지 마세요. 제공된 확인값과 공식 근거가 없으면 모른다고 말하고 공식 원문 확인을 안내하세요. "
            "답변은 간결한 한국어로 작성하세요.\n확인된 케이스:\n"
            + json.dumps(case_summary, ensure_ascii=False, default=str)
            + "\n사용자 요청:\n" + minimized_content
        )
        try:
            client = AsyncOpenAI(api_key=self.settings.openai_api_key)
            response = await client.responses.create(model=self.settings.ai_chat_model, input=prompt, store=False)
            text = (response.output_text or "").strip()
            safe_source = {"case": case_summary, "request": minimized_content}
            return (text, "openai", self.settings.ai_chat_model) if text and self._ai_output_safe(text, safe_source, allow_personal=False) else (fallback, "safe_fallback", None)
        except Exception:
            return fallback, "safe_fallback", None
