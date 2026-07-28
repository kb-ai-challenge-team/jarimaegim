"""조건 확정 레이어.

제안서 03장 — "최소 조건 미충족 시 후보를 생성하지 않고 질문합니다. 최대 3개, 답이 후보를
바꾸는 항목만." 그래서 이 레이어는 `blocking=True` 다. 조건이 덜 찬 채로 후보를 만들면
그 후보는 사용자가 말하지 않은 가정 위에 서게 된다.

질문 상한 3개는 UX 예의가 아니라 정보 설계다. 답이 후보 목록을 바꾸지 않는 항목까지 물으면
사용자는 "무엇을 답해야 결과가 달라지는지" 알 수 없게 된다. 평수·운영형태를 선택 항목으로
둔 이유가 그것이다 — 없어도 후보는 나오고, 있으면 필요자금과 현금소진이 더 정확해질 뿐이다.

마이데이터는 게이트 off 다. 수동 입력이 **동일 스키마를 충족**하므로 제품은 성립하고,
이 레이어는 어느 경로로 채워졌는지를 `source` 로 밝힌다.

── 이 레이어에서 LLM 이 하는 일과 하지 않는 일 ──────────────────────────────

condition.location 은 자유 문장에서 조건을 읽는다. 그러나 **모델이 값을 말하지는 않는다**:
모델은 원문의 어느 조각이 어느 항목인지 가리키기만 하고(`field` + `span`), 그 조각이 원문에
그대로 있는지 확인한 뒤 금액·평수를 코드가 다시 읽는다(`amount_krw` · `resolve_mention`).
"월세 400만원 정도 생각한다"고 말한 적 없는 사용자의 조건에 400만원이 들어가는 경로를
이 방식으로 없앴다. 발화가 없으면 대조할 원문이 없으므로 모델을 아예 부르지 않는다.

condition.finance 는 되물을 항목을 고른다. 모델은 **실제로 비어 있는 항목 중에서만** 고를 수
있고, 상한 3개는 코드가 다시 강제한다. 모델이 고르지 않으면 선언 순서로 되돌아간다.

추출은 **비어 있던 항목만 채운다.** 사용자가 화면에서 확정한 값을 모델의 해석이 덮어쓰면
"확인 후 수정하고 시작해 주세요"라는 화면의 약속이 거짓이 된다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .contracts import AgentStatus, TeamReport
from .llm import AgentLLM, ChoiceSchema, Decision, Pick, Records, Span
from .registry import spec

#: 답이 후보를 바꾸는 항목. 이것이 최소 조건이다.
REQUIRED_LOCATION = (("industry", "업종"), ("district", "자치구"))
REQUIRED_FINANCE = (("equity_krw", "자기자본"), ("monthly_rent_krw", "희망 월세"))

#: 있으면 필요자금·현금소진이 정확해지지만, 없어도 후보는 나온다.
OPTIONAL_LOCATION = (("area_pyeong", "희망 평수"), ("operating_style", "운영형태"),
                     ("deposit_krw", "희망 보증금"))

QUESTION_LIMIT = 3

SEOUL_DISTRICTS = ("종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구",
                   "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구",
                   "구로구", "금천구", "영등포구", "동작구", "관악구", "서초구", "강남구", "송파구",
                   "강동구")

#: 발화에서 읽을 수 있는 항목. 여기 없는 항목은 모델이 가리킬 문법 자체가 없다.
EXTRACTABLE = ("industry", "district", "area_pyeong", "operating_style",
               "deposit_krw", "monthly_rent_krw")

_AMOUNT_UNITS = (("억", 100_000_000), ("천만", 10_000_000), ("백만", 1_000_000), ("만", 10_000))
#: 천단위 쉼표는 반복될 수 있으므로 `*` 다. `?` 로 두면 "2,500,000원"이 2,500 으로 읽혀
#: 천 배 작은 금액이 조용히 조건에 들어간다.
_AMOUNT = re.compile(r"(\d+(?:[.,]\d+)*)\s*(억|천만|백만|만)?\s*원?")
_AREA = re.compile(r"(\d+(?:\.\d+)?)\s*평")
#: 조사만 떼어 낸다. 그 이상 손대면 업종명을 코드가 고쳐 쓰는 셈이 된다.
_PARTICLES = re.compile(r"(?:을|를|이|가|은|는|에서|에|으로|로|랑|하고|와|과)$")

EXTRACT_SCHEMA = ChoiceSchema(
    name="extract_conditions",
    description="사용자 발화에서 각 조건이 언급된 위치를 가리킨다. 값을 새로 쓰지 말고 원문 조각만 적는다.",
    fields={"mentions": Records(
        description="발화에 실제로 등장한 언급만. 언급되지 않은 항목은 넣지 않는다.",
        fields={"field": Pick(EXTRACTABLE, description="이 조각이 가리키는 조건 항목"),
                "span": Span(description="발화에 그대로 등장하는 조각. 금액은 단위까지 포함한다.")})})


def amount_krw(text: str) -> int | None:
    """문자열에서 금액을 읽는다. 없으면 None — 0 을 돌려주면 "월세 0원"이 조용히 만들어진다.

    "1억 5천만원"처럼 단위가 이어지면 더한다. 단위 없는 숫자는 원 단위로 본다."""
    total = 0
    found = False
    for match in _AMOUNT.finditer(text or ""):
        raw, unit = match.group(1), match.group(2)
        if not raw:
            continue
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if value <= 0:
            continue
        multiplier = next((factor for name, factor in _AMOUNT_UNITS if name == unit), 1)
        total += int(round(value * multiplier))
        found = True
    return total if found else None


def resolve_mention(field_name: str, span: str) -> Any | None:
    """모델이 가리킨 조각에서 값을 읽는다. 읽지 못하면 None — 추측하지 않는다."""
    text = (span or "").strip()
    if not text:
        return None
    if field_name == "district":
        return next((item for item in SEOUL_DISTRICTS if item in text), None)
    if field_name == "area_pyeong":
        match = _AREA.search(text)
        return float(match.group(1)) if match else None
    if field_name in ("deposit_krw", "monthly_rent_krw"):
        return amount_krw(text)
    if field_name in ("industry", "operating_style"):
        return _PARTICLES.sub("", text).strip() or None
    return None


@dataclass(frozen=True)
class ConditionReport(TeamReport):
    questions: list[dict[str, str]] = field(default_factory=list)
    settled: bool = False
    #: 발화에서 읽어 채운 값까지 반영된 조건. 후속 팀은 이것을 받는다.
    conditions: dict[str, Any] = field(default_factory=dict)

    @property
    def halted(self) -> bool:
        """기본 규칙(`활성 0건`)을 쓰지 않는다. 두 에이전트 중 하나만 미충족이어도 후보를
        만들면 안 되므로, 이 레이어의 중단 조건은 "전부 확정되었는가" 하나다."""
        return not self.settled


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _missing(conditions: dict[str, Any], required) -> list[tuple[str, str]]:
    gaps = []
    for key, label in required:
        if _blank(conditions.get(key)):
            gaps.append((key, label))
    return gaps


class ConditionLayer:
    team = "condition"
    name = "조건 확정 레이어"

    def __init__(self, *, mydata_enabled: bool = False, llm: AgentLLM | None = None):
        self.mydata_enabled = mydata_enabled
        self.llm = llm

    def run(self, conditions: dict[str, Any], *, extraction: Decision | None = None,
            asked: Decision | None = None) -> ConditionReport:
        """결정론 경로. 두 결정이 없으면 오늘까지의 동작 그대로다."""
        extraction = extraction or Decision.deterministic("condition.location",
                                                          schema=EXTRACT_SCHEMA.name)
        asked = asked or Decision.deterministic("condition.finance", schema="select_questions")
        extracted = self._extracted(conditions, extraction)
        merged = {**conditions, **extracted}

        location_gaps = _missing(merged, REQUIRED_LOCATION)
        finance_gaps = _missing(merged, REQUIRED_FINANCE)

        location = spec("condition.location")
        finance = spec("condition.finance")
        outcomes = [
            location.outcome(
                AgentStatus.WITHHELD if location_gaps else AgentStatus.OK,
                message="입지 최소 조건이 아직 확정되지 않았습니다." if location_gaps else None,
                data={"settled": {key: merged.get(key) for key, _ in REQUIRED_LOCATION},
                      "optional": {key: merged.get(key) for key, _ in OPTIONAL_LOCATION},
                      "extracted": extracted, "decision": extraction.as_data(),
                      "missing": [key for key, _ in location_gaps]}),
            finance.outcome(
                AgentStatus.WITHHELD if finance_gaps else AgentStatus.OK,
                message="금융 프로필이 아직 확정되지 않았습니다." if finance_gaps else None,
                data={"source": "MYDATA" if self.mydata_enabled else "MANUAL",
                      "mydata_enabled": self.mydata_enabled, "decision": asked.as_data(),
                      "settled": {key: merged.get(key) for key, _ in REQUIRED_FINANCE},
                      "missing": [key for key, _ in finance_gaps]}),
        ]

        questions = self._questions(location_gaps + finance_gaps, asked)
        settled = not location_gaps and not finance_gaps
        return ConditionReport(team=self.team, name=self.name, outcomes=outcomes, blocking=True,
                               questions=questions, settled=settled, conditions=merged,
                               message=None if settled else "확정되지 않은 조건이 있어 후보를 생성하지 않았습니다.")

    async def interpret(self, conditions: dict[str, Any]) -> tuple[dict[str, Any], Decision]:
        """발화만 읽어 빈칸을 채운다. 조건 카드를 채우는 화면이 케이스를 만들기 전에 쓴다.

        실행 전체를 돌리지 않는 이유는 이 시점에 케이스도 후보도 없기 때문이고, 그래도 같은
        추출 경로를 쓰는 이유는 화면에 채워지는 값과 실행이 읽는 값이 갈라지면 안 되기 때문이다."""
        decision = await self._extract(conditions)
        return self._extracted(conditions, decision), decision

    async def arun(self, conditions: dict[str, Any]) -> ConditionReport:
        """추론을 붙인 경로. 모델이 없으면 `run` 과 같은 결과가 나온다."""
        extraction = await self._extract(conditions)
        merged = {**conditions, **self._extracted(conditions, extraction)}
        asked = await self._ask(merged)
        return self.run(conditions, extraction=extraction, asked=asked)

    # ── condition.location · 발화에서 읽기 ──────────────────────────────
    async def _extract(self, conditions: dict[str, Any]) -> Decision:
        utterance = str(conditions.get("utterance") or "").strip()
        gaps = [key for key, _ in (REQUIRED_LOCATION + REQUIRED_FINANCE + OPTIONAL_LOCATION)
                if _blank(conditions.get(key))]
        if self.llm is None or not utterance or not gaps:
            # 대조할 원문이 없거나 채울 칸이 없으면 부르지 않는다 — 검증할 수 없는 추출은 하지 않고,
            # 이미 확정된 조건을 다시 해석해 봐야 덮어쓸 수도 없으므로 호출이 낭비다.
            return Decision.deterministic("condition.location", schema=EXTRACT_SCHEMA.name)
        return await self.llm.choose(
            agent_key="condition.location", schema=EXTRACT_SCHEMA, verify_against=utterance,
            instruction=("발화에서 아직 비어 있는 조건이 언급된 곳을 가리키세요. "
                         "금액을 계산하지 말고 원문 조각을 그대로 적으세요."),
            context={"발화": utterance, "비어 있는 항목": gaps,
                     "이미 확정된 항목": {key: conditions.get(key)
                                    for key, _ in REQUIRED_LOCATION + REQUIRED_FINANCE
                                    if not _blank(conditions.get(key))}})

    @staticmethod
    def _extracted(conditions: dict[str, Any], extraction: Decision) -> dict[str, Any]:
        """검증된 조각에서 값을 읽어, 비어 있던 항목만 채운다."""
        filled: dict[str, Any] = {}
        for row in extraction.chosen.get("mentions", []):
            name = row.get("field")
            if name not in EXTRACTABLE or name in filled or not _blank(conditions.get(name)):
                continue
            value = resolve_mention(name, row.get("span", ""))
            if value is not None:
                filled[name] = value
        return filled

    # ── condition.finance · 무엇을 되물을지 고르기 ───────────────────────
    async def _ask(self, merged: dict[str, Any]) -> Decision:
        gaps = [key for key, _ in _missing(merged, REQUIRED_LOCATION + REQUIRED_FINANCE)]
        if self.llm is None or not gaps:
            return Decision.deterministic("condition.finance", schema="select_questions")
        schema = ChoiceSchema(
            name="select_questions",
            description="되물을 항목을 고른다. 답이 후보 목록을 바꾸는 항목만, 최대 3개.",
            fields={"ask": Pick(tuple(gaps), multi=True, max_items=QUESTION_LIMIT,
                                description="비어 있는 항목 중 되물을 것")})
        return await self.llm.choose(
            agent_key="condition.finance", schema=schema,
            instruction="비어 있는 항목 중 답이 후보 목록을 바꾸는 것만 고르세요. 확신이 없으면 비워 두세요.",
            context={"비어 있는 항목": gaps,
                     "확정된 조건": {key: value for key, value in merged.items()
                                if key != "utterance" and not _blank(value)}})

    @staticmethod
    def _questions(gaps: list[tuple[str, str]], asked: Decision) -> list[dict[str, str]]:
        """모델은 순서와 개수만 정한다. 비어 있지 않은 항목은 골라도 질문이 되지 않는다."""
        labels = dict(gaps)
        chosen = [key for key in asked.chosen.get("ask", []) if key in labels]
        ordered = chosen or [key for key, _ in gaps]
        return [{"field": key, "label": labels[key]} for key in ordered][:QUESTION_LIMIT]
