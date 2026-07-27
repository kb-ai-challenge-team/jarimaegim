from __future__ import annotations
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4
import httpx
from openai import AsyncOpenAI
from .config import Settings
from .models import AnalysisResult, Candidate, ContextSignal, CostItem, CostPlanCreate, LocationSearch, Provenance


KAKAO_LOCAL_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


class IntegrationError(Exception):
    pass


class LocationService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._candidate_index: dict[str, Candidate] = {}

    async def search(self, payload: LocationSearch) -> tuple[list[Candidate], str, str | None]:
        if not self.settings.kakao_rest_api_key:
            return [], "integration_pending", "Kakao Local REST API 키가 설정되지 않아 실제 장소 후보를 불러오지 않았습니다."
        query = f"서울 {payload.district} {payload.industry}"
        headers = {"Authorization": f"KakaoAK {self.settings.kakao_rest_api_key}"}
        params = {"query": query, "size": payload.limit, "sort": "accuracy"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
                response = await client.get(KAKAO_LOCAL_URL, headers=headers, params=params)
                if response.status_code == 429:
                    raise IntegrationError("Kakao Local API 호출 한도에 도달했습니다. 잠시 후 다시 확인해 주세요.")
                response.raise_for_status()
                documents = response.json().get("documents", [])
        except IntegrationError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise IntegrationError("Kakao 위치 정보를 불러오지 못했습니다. 후보 목록 연결 상태를 확인해 주세요.") from exc

        collected = datetime.now(UTC).isoformat()
        candidates: list[Candidate] = []
        for item in documents:
            if not item.get("id") or not item.get("x") or not item.get("y") or not item.get("place_url"):
                continue
            signal = ContextSignal(
                name="access", label="위치 확인", score_band="UNKNOWN", direction="UNKNOWN",
                explanation="공식 장소 검색으로 주소와 좌표만 확인했습니다. 수요·경쟁·비용 수준은 별도 서울 데이터 연동 후 판단합니다."
            )
            provenance = Provenance(
                source_name="Kakao Local 장소 검색", official_url=item["place_url"], collected_at=collected,
                industry_scope=item.get("category_name") or payload.industry, spatial_unit="개별 장소 좌표",
                confidence="LOW", limitations=["장소 검색 결과는 입지 적합성, 매출, 생존 가능성을 의미하지 않습니다.", "서울 상권분석 데이터가 결합되기 전에는 맥락 신호만 제공합니다."]
            )
            candidate = Candidate(
                id=f"kakao-{item['id']}", name=item.get("place_name") or "이름 확인 필요",
                address=item.get("address_name") or "주소 확인 필요", road_address=item.get("road_address_name") or None,
                latitude=float(item["y"]), longitude=float(item["x"]), distance_m=int(item["distance"]) if item.get("distance") else None,
                evidence_grade="C", display_label="입지 환경 신호", context_signals=[signal], provenance=provenance
            )
            candidates.append(candidate)
            self._candidate_index[candidate.id] = candidate
        return candidates, "success" if candidates else "empty", None if candidates else "현재 검색어와 일치하는 공식 장소를 찾지 못했습니다."

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        return self._candidate_index.get(candidate_id)


class AnalysisService:
    def __init__(self, location_service: LocationService):
        self.locations = location_service

    def analyze(self, candidate_id: str) -> AnalysisResult:
        candidate = self.locations.get_candidate(candidate_id)
        if not candidate:
            return AnalysisResult(
                analysis_id=uuid4(), status="blocked", evidence_grade="U", display_label="현재 조건으로 분석 불가",
                confidence="INSUFFICIENT", blocked_reason="후보의 공식 위치 근거를 확인할 수 없습니다.",
                required_actions=["탐색에서 후보를 다시 선택해 주세요.", "위치 API 연결 상태를 확인해 주세요."],
                provenance=Provenance(source_name="원천 확인 불가", industry_scope="확인 불가", spatial_unit="확인 불가", confidence="INSUFFICIENT", limitations=["근거가 없는 결과를 만들지 않았습니다."]),
                limitations=["검증 가능한 후보 ID가 없습니다."]
            )
        return AnalysisResult(
            analysis_id=uuid4(), status="completed", evidence_grade="C", display_label="입지 환경 신호",
            survival_grade=None, context_risk_grade=None, probability_lower=None, probability_upper=None,
            probability_unit=None, horizon_months=None, confidence="LOW", sample_n=None, event_n=None,
            context_signals=candidate.context_signals, provenance=candidate.provenance,
            limitations=["공식 위치 좌표만 확인된 상태입니다.", "개별 점포 생존등급이나 생존·폐업 확률을 제공하지 않습니다."]
        )


class CostService:
    @staticmethod
    def calculate(payload: CostPlanCreate, equity_krw: int) -> dict[str, Any]:
        available = [item for item in payload.items if item.source_type != "UNAVAILABLE" and item.min_krw is not None and item.max_krw is not None]
        total_min = sum(int(item.min_krw or 0) for item in available)
        total_max = sum(int(item.max_krw or 0) for item in available)
        return {
            "items": [item.model_dump() for item in payload.items], "total_min_krw": total_min,
            "total_max_krw": total_max, "equity_krw": equity_krw,
            "gap_min_krw": max(0, total_min - equity_krw), "gap_max_krw": max(0, total_max - equity_krw)
        }


class OfficialSourceService:
    PROVIDERS = (
        ("GOVERNMENT", "기업마당", "bizinfo_api_url", "bizinfo_api_key"),
        ("GOVERNMENT", "K-Startup", "kstartup_api_url", "kstartup_api_key"),
        ("PRIVATE", "금융상품 한눈에", "finlife_api_url", "finlife_api_key"),
    )

    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def _resolved_url(template: str, key: str) -> str:
        return template.replace("{api_key}", quote(key, safe="")) if "{api_key}" in template else template

    @staticmethod
    def _response_payload(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            from xml.etree import ElementTree

            try:
                root = ElementTree.fromstring(response.content)
            except ElementTree.ParseError:
                return {}
            items = [
                {child.tag: (child.text or "").strip() for child in item}
                for item in root.findall(".//body/items/item")
            ]
            return {"items": items}

    async def programs(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0), follow_redirects=False) as client:
            for category, provider, url_name, key_name in self.PROVIDERS:
                template = getattr(self.settings, url_name)
                key = getattr(self.settings, key_name)
                if not template or not key:
                    continue
                if not template.startswith("https://"):
                    continue
                try:
                    response = await client.get(self._resolved_url(template, key), headers={"Accept": "application/json", "X-Api-Key": key})
                    response.raise_for_status()
                    payload = self._response_payload(response)
                    for record in self._extract_records(payload):
                        normalized = self._normalize(record, category, provider)
                        if normalized and normalized["official_url"].startswith("https://"):
                            results.append(normalized)
                except (httpx.HTTPError, ValueError, TypeError):
                    continue
        # Providers occasionally repeat the same record across pages or option rows.
        unique: dict[str, dict[str, Any]] = {}
        for item in results:
            unique.setdefault(item["id"], item)
        order = {"GOVERNMENT": 0, "POLICY_FUND": 1, "GUARANTEE": 2, "PRIVATE": 3}
        return sorted(unique.values(), key=lambda item: order[item["category"]])[:50]

    # FSS 금융상품 한눈에 공시. The per-API spec pages are still "콘텐츠 준비중", so every endpoint and
    # source page below was confirmed against the live service rather than published documentation.
    # Treat a shape change as expected: each category fails closed to nothing rather than guessing.
    KB_FIN_CO_NO = "0010927"
    KB_MAX_PAGES = 5
    KB_CATEGORIES = (
        ("BUSINESS_LOAN", "개인사업자대출", "busiLoanProductsSearch", "LOAN", "https://finlife.fss.or.kr/finlife/ldng/indvlBusi/list.do?menuNo=700072"),
        ("CREDIT_LOAN", "개인신용대출", "creditLoanProductsSearch", "LOAN", "https://finlife.fss.or.kr/finlife/ldng/indvCrdt/list.do?menuNo=700009"),
        ("MORTGAGE_LOAN", "주택담보대출", "mortgageLoanProductsSearch", "LOAN", "https://finlife.fss.or.kr/finlife/ldng/houseMortgage/list.do?menuNo=700007"),
        ("RENT_LOAN", "전세자금대출", "rentHouseLoanProductsSearch", "LOAN", "https://finlife.fss.or.kr/finlife/ldng/rentHouse/list.do?menuNo=700008"),
        ("DEPOSIT", "정기예금", "depositProductsSearch", "SAVING", "https://finlife.fss.or.kr/finlife/svings/fxdDpst/list.do?menuNo=700002"),
        ("SAVING", "적금", "savingProductsSearch", "SAVING", "https://finlife.fss.or.kr/finlife/svings/instsav/list.do?menuNo=700003"),
    )

    async def kb_products(self) -> list[dict[str, Any]]:
        """Every KB국민은행 product the FSS discloses. Returns [] when the base URL or key is unset."""
        base = self.settings.finlife_api_base_url.rstrip("/")
        key = self.settings.finlife_api_key
        if not base or not key or not base.startswith("https://"):
            return []
        results: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0), follow_redirects=False) as client:
            for category, label, endpoint, kind, source_url in self.KB_CATEGORIES:
                try:
                    records, options = await self._fetch_kb_category(client, f"{base}/{endpoint}.json?auth={quote(key, safe='')}&topFinGrpNo=020000")
                except (httpx.HTTPError, ValueError, TypeError):
                    continue
                rates: dict[str, dict[str, Any]] = {}
                for option in options:
                    code = str(option.get("fin_prdt_cd") or "")
                    if code and code not in rates:
                        rates[code] = option
                for record in records:
                    if str(record.get("fin_co_no") or "") != self.KB_FIN_CO_NO:
                        continue
                    item = self._normalize_kb_product(record, rates, category, label, kind, source_url)
                    if item:
                        results.append(item)
        return results

    async def _fetch_kb_category(self, client: httpx.AsyncClient, url: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        records: list[dict[str, Any]] = []
        options: list[dict[str, Any]] = []
        for page in range(1, self.KB_MAX_PAGES + 1):
            response = await client.get(f"{url}&pageNo={page}", headers={"Accept": "application/json"})
            response.raise_for_status()
            result = (self._response_payload(response) or {}).get("result") or {}
            if str(result.get("err_cd") or "000") != "000":
                break
            records.extend(item for item in (result.get("baseList") or []) if isinstance(item, dict))
            options.extend(item for item in (result.get("optionList") or []) if isinstance(item, dict))
            if page >= int(result.get("max_page_no") or page):
                break
        return records, options

    @staticmethod
    def _rate(option: dict[str, Any], *fields: str) -> float | None:
        for field in fields:
            value = option.get(field)
            if value in (None, "", "-"):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _normalize_kb_product(self, record: dict[str, Any], rates: dict[str, dict[str, Any]], category: str, label: str, kind: str, source_url: str) -> dict[str, Any] | None:
        name = self._first(record, ("fin_prdt_nm",))
        code = self._first(record, ("fin_prdt_cd",))
        if not name or not code:
            return None
        option = rates.get(code, {})
        if kind == "LOAN":
            rate_min = self._rate(option, "lend_rate_min")
            rate_max = self._rate(option, "lend_rate_max")
            rate_avg = self._rate(option, "lend_rate_avg", "crdt_grad_avg")
            rate_kind = "대출금리"
            limit = self._first(record, ("loan_limit",))
        else:
            rate_min = self._rate(option, "intr_rate")
            rate_max = self._rate(option, "intr_rate2")
            rate_avg = None
            rate_kind = "저축금리"
            limit = self._first(record, ("max_limit",))
        return {
            "id": f"kb-{category.lower()}-{code}", "name": name, "category": category, "category_label": label,
            "organization": self._first(record, ("kor_co_nm",)) or "KB국민은행",
            "product_type": self._first(record, ("fin_prdt_type_nm",)) or None,
            "rate_kind": rate_kind, "rate_min": rate_min, "rate_max": rate_max, "rate_avg": rate_avg,
            "rate_type": self._first(record, ("lend_rate_type", "intr_rate_type_nm")) or None,
            "loan_limit": None if limit in ("", "기타", "0") else limit,
            "join_way": self._first(record, ("join_way",)) or None,
            "repay_type": self._first(record, ("rpay_type",)) or None,
            "source_as_of": self._first(record, ("dcls_month",)) or None,
            "official_url": source_url,
            "unknown_conditions": ["공시 금리는 기준월 범위이며 실제 적용 금리·한도가 아닙니다.", "자격과 심사 결과는 KB국민은행에서 직접 확인해야 합니다."]
        }

    @staticmethod
    def _extract_records(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("items", "item", "baseList", "data", "result", "results", "body"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = OfficialSourceService._extract_records(value)
                if nested:
                    return nested
        return []

    @staticmethod
    def _first(record: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = record.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return ""

    def _normalize(self, record: dict[str, Any], category: str, provider: str) -> dict[str, Any] | None:
        title = self._first(record, ("title", "name", "pblancNm", "bizPbancNm", "biz_pbanc_nm", "supt_biz_titl_nm", "titl_nm", "fin_prdt_nm"))
        url = self._first(record, ("official_url", "url", "detailUrl", "pblancUrl", "detl_pg_url", "biz_gdnc_url", "biz_aply_url", "homepage_url"))
        if not url and provider == "금융상품 한눈에":
            url = "https://finlife.fss.or.kr/"
        if not title or not url:
            return None
        if url.startswith("http://"):
            url = "https://" + url.removeprefix("http://")
        organization = self._first(record, ("organization", "agency", "jrsdInsttNm", "insttNm", "pbanc_ntrp_nm", "sprv_inst", "kor_co_nm")) or provider
        period = self._first(record, ("application_period", "period", "reqstBeginEndDe", "pbanc_rcpt_bgng_dt", "pbanc_rcpt_end_dt", "dcls_strt_day", "dcls_end_day"))
        source_date = self._first(record, ("source_as_of", "updated_at", "creatPnttm", "fstm_reg_dt", "anncmnt_dt", "dcls_month", "fin_co_subm_day"))
        # Provider ids are only unique within a provider, and finlife product codes repeat across banks
        # (WR0002F, for example). Namespace by provider and organisation so list keys stay unique.
        seed = self._first(record, ("id", "pblancId", "biz_pbanc_sn", "pbanc_sn", "fin_prdt_cd")) or f"{title}:{url}"
        record_id = hashlib.sha256(f"{provider}:{organization}:{seed}".encode()).hexdigest()[:24]
        return {"id": record_id, "category": category, "title": title, "organization": organization,
                "status": "UNKNOWN", "application_period": period or None, "matched_conditions": [],
                "unknown_conditions": ["공식 원문의 지역·업종·업력·제외 조건을 직접 확인해야 합니다."],
                "official_url": url, "source_as_of": source_date or None}


class AIService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def build_prompt(self, user_text: str, case_summary: str) -> str:
        """The assistant's instructions. Extracted from explain() so the guardrails can be asserted."""
        return (
            "당신은 자리매김의 설명 도우미입니다. 새로운 숫자, 점수, 비용, 금융 자격을 만들지 마세요. "
            "제공된 케이스 요약 안의 사실만 짧고 명확한 한국어로 설명하세요. 개인정보 입력을 요청하지 마세요. "
            "요약에 매물 조건이 있다면 그것은 시연용으로 생성한 데이터이며 실제 임대 매물이 아닙니다. "
            "계약 가능 여부나 실제 거래 조건을 단정하지 말고, 시연용 데이터라는 점을 밝히세요. "
            "좁은 사이드 패널에 표시되므로 5문장 이내로 답하세요.\n"
            f"케이스: {case_summary}\n사용자 질문: {user_text}"
        )

    async def explain(self, user_text: str, case_summary: str) -> dict[str, Any]:
        if not self.client or not self.settings.ai_chat_model or not self.settings.ai_explanation_enabled:
            return {"message": "AI 설명 키가 아직 설정되지 않았습니다. 후보와 분석 화면의 저장된 공식 근거는 계속 확인할 수 있습니다.", "citations": [], "integration_status": "not_configured"}
        prompt = self.build_prompt(user_text, case_summary)
        try:
            response = await self._respond(prompt)
            text = response.output_text.strip()
            if not text:
                # Reasoning models spend the budget before emitting text; say so rather than looking generic.
                return {"message": "설명이 길어져 응답을 완성하지 못했습니다. 질문을 더 좁혀 다시 물어봐 주세요. 저장된 근거는 그대로 확인할 수 있습니다.", "citations": [], "integration_status": "incomplete"}
            return {"message": text, "citations": [], "integration_status": "connected"}
        except Exception:
            return {"message": "AI 설명 연결이 지연되고 있습니다. 저장된 분석과 공식 원문은 계속 사용할 수 있습니다.", "citations": [], "integration_status": "unavailable"}

    async def _respond(self, prompt: str):
        """Reasoning models need headroom beyond the reasoning pass; non-reasoning models reject `reasoning`."""
        common = {"model": self.settings.ai_chat_model, "input": prompt, "store": False, "max_output_tokens": 2000}
        try:
            return await self.client.responses.create(**common, reasoning={"effort": "low"})
        except TypeError:
            return await self.client.responses.create(**common)
        except Exception as exc:
            if "reasoning" not in str(exc):
                raise
            return await self.client.responses.create(**common)
