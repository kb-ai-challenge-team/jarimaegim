from __future__ import annotations
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
import httpx
from openai import AsyncOpenAI
from .config import Settings
from .models import AnalysisResult, Candidate, ContextSignal, CostPlanCreate, LocationSearch, Provenance


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

    # 모델에게 값을 채우게 하지 않고 "어느 구간이 그 말을 하는가"를 지목하게 한다.
    # 금액 환산조차 시키지 않는다 — monthly_rent_krw 의 value 는 서버가 evidence 에서 다시 계산한다.
    def build_interpret_prompt(self, user_text: str) -> str:
        """조건 추출기의 지시문. explain 과 마찬가지로 키 없이도 단정할 수 있게 분리해 둔다."""
        return (
            "당신은 자리매김의 조건 추출기입니다. 사용자 문장이 명시적으로 말한 것만 뽑습니다.\n"
            "industry·district·monthly_rent_krw·business_stage·startup_type·priority 여섯 필드를 "
            "각각 {\"value\": ..., \"evidence\": ...} 형태로 담은 JSON 객체 하나만 출력하세요.\n"
            "1. 문장에 없는 값은 반드시 null 로 두세요. 추론·보완·평균값 채우기를 금지합니다.\n"
            "2. 값을 채운 필드는 evidence 에 근거가 된 사용자 문장의 일부를 원문 그대로 복사하세요. "
            "요약·번역·재작성은 금지이며, 원문에 없는 문구를 넣으면 그 필드는 버려집니다.\n"
            "3. 어떤 계산도 하지 마세요. 합계·단위 환산·비율·기간 환산 전부 금지입니다.\n"
            "4. district 는 서울 25개 자치구 이름만 허용합니다. 그 밖의 지역은 null 입니다.\n"
            "5. monthly_rent_krw 는 value 를 null 로 두고 evidence 에 월세를 말한 구간만 넣으세요. "
            "금액 환산은 서버가 합니다.\n"
            "6. business_stage 는 PRE_OPEN·RELOCATING·SECOND_STORE, "
            "startup_type 은 INDEPENDENT·FRANCHISE·UNDECIDED, "
            "priority 는 STABILITY·DEMAND·COST·GROWTH 중 하나입니다.\n"
            f"사용자 문장: {user_text}"
        )

    async def interpret_conditions(self, user_text: str) -> dict[str, Any] | None:
        """모델이 제안한 필드 맵. 키가 없거나 호출이 실패하면 None 을 돌려주고 호출부가 규칙 경로로 간다.

        여기서 나온 값은 아직 신뢰 대상이 아니다 — condition_interpret.sanitize 를 반드시 통과해야 한다."""
        if not self.client or not self.settings.ai_chat_model or not self.settings.ai_explanation_enabled:
            return None
        try:
            response = await self._respond(self.build_interpret_prompt(user_text))
            text = (response.output_text or "").strip()
            if not text:
                return None
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

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

    def responder(self) -> "OpenAIResponder | None":
        if not self.client or not self.settings.ai_chat_model or not self.settings.ai_explanation_enabled:
            return None
        return OpenAIResponder(self.client, self.settings.ai_chat_model)


class OpenAIResponder:
    """Adapts the Responses API to the `{text, tool_calls}` shape ChatStreamer's tool loop expects.

    `messages` arrives from ChatStreamer already shaped like Chat Completions history -- an
    assistant message carries a nested `tool_calls` list, a tool result carries `tool_call_id` --
    because that is the shape the loop naturally accumulates as it runs. The Responses API's
    `input` array does not accept that shape: a function call and its result are each their own
    top-level item (`function_call` / `function_call_output`), never a field nested inside a
    role:assistant or role:tool message (confirmed against this environment's installed
    openai.types.responses.response_input_param -- ResponseFunctionToolCallParam and
    FunctionCallOutput are distinct sibling members of the ResponseInputItemParam union, not
    sub-fields of EasyInputMessageParam). `_translate` rebuilds each Chat-Completions-shaped
    message into the Responses API item(s) it corresponds to.
    """

    def __init__(self, client: AsyncOpenAI, model: str):
        self.client, self.model = client, model

    async def respond(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "input": self._translate(messages), "store": False,
                                    "max_output_tokens": 2000}
        if tools:
            # `strict` MUST stay False. Verified against the live Responses API, not just the SDK
            # stub: `strict: True` requires `required` to list every key in `properties`, and four
            # of our schemas deliberately have optional parameters (months, categories, keywords,
            # radius_m). Flipping this to True 400s on all four -- if you ever want strict schemas,
            # make every `required` list exhaustive first.
            # The SDK types `strict` as Required[Optional[bool]], implying the key must always be
            # present. The server does not agree: omitting it entirely is accepted. We send it
            # explicitly anyway so the value is a decision on the page rather than a default.
            payload["tools"] = [{"type": "function", "name": tool["name"], "description": tool["description"],
                                 "parameters": tool["parameters"], "strict": False} for tool in tools]
        # Same reasoning-parameter compatibility problem AIService._respond solves for explain(),
        # and the same fix, in the same order: TypeError means this SDK build's `responses.create`
        # doesn't accept `reasoning` as a keyword at all (a local, unconditional signature
        # mismatch) so it is checked first and retried without further inspection; an ordinary
        # Exception that *names* "reasoning" means the configured model rejected the parameter
        # server-side, which also warrants a retry; anything else is a real failure (auth, rate
        # limit, context length, ...) that must propagate so ChatStreamer's `except Exception`
        # reports it as UPSTREAM_UNAVAILABLE instead of this method silently eating it.
        try:
            response = await self.client.responses.create(**payload, reasoning={"effort": "low"})
        except TypeError:
            response = await self.client.responses.create(**payload)
        except Exception as exc:
            if "reasoning" not in str(exc):
                raise
            response = await self.client.responses.create(**payload)
        return self._parse(response)

    @staticmethod
    def _translate(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                items.append({"type": "function_call_output", "call_id": message.get("tool_call_id"),
                             "output": message.get("content") or ""})
                continue
            content = message.get("content") or ""
            if content:
                items.append({"type": "message", "role": role, "content": content})
            for call in message.get("tool_calls") or []:
                items.append({"type": "function_call", "call_id": call.get("id"), "name": call.get("name") or "",
                             "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False)})
        return items

    @staticmethod
    def _parse(response: Any) -> dict[str, Any]:
        calls = []
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", None) != "function_call":
                continue
            try:
                arguments = json.loads(getattr(item, "arguments", "") or "{}")
            except (TypeError, ValueError):
                arguments = {}
            calls.append({"id": getattr(item, "call_id", None) or getattr(item, "id", None),
                          "name": getattr(item, "name", ""),
                          "arguments": arguments if isinstance(arguments, dict) else {}})
        return {"text": (getattr(response, "output_text", "") or "").strip(), "tool_calls": calls}
