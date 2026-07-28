from __future__ import annotations
import re
from typing import Any

from .districts import SEOUL_DISTRICTS

# lib/parse-case.ts 의 이식본. 자기자본·총예산 추출은 뺐다 — 1단계 금융 프로필이 소유하는 값을
# 발화가 덮어쓰면 확정한 것이 조용히 흔들린다. 대신 희망 월세를 뽑는다.
# 모든 필드는 value 와 함께 evidence(원문 구간)를 돌려준다. AI 경로와 같은 계약을 지켜야
# 확인 화면의 인용 표시가 두 경로에서 동일하게 동작한다.

FIELDS = ("industry", "district", "monthly_rent_krw", "business_stage", "startup_type", "priority")

INDUSTRY_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"카페|커피|coffee", re.I), "카페"),
    (re.compile(r"베이커리|빵집|제과"), "제과점"),
    (re.compile(r"치킨"), "치킨전문점"),
    (re.compile(r"분식"), "분식점"),
    (re.compile(r"술집|주점|호프|이자카야|와인바"), "주점"),
    (re.compile(r"편의점"), "편의점"),
    (re.compile(r"미용실|헤어|미용"), "미용실"),
    (re.compile(r"네일|속눈썹"), "네일샵"),
    (re.compile(r"학원|공부방|교습소"), "학원"),
    (re.compile(r"세탁"), "세탁소"),
    (re.compile(r"피시방|PC방", re.I), "PC방"),
    (re.compile(r"무인|셀프\s*빨래"), "무인점포"),
    (re.compile(r"음식점|식당|밥집|한식|중식|일식|양식"), "일반음식점"),
]

# {2,10} 대신 지연(lazy) 수량자를 쓴다: 탐욕적 수량자는 조사(을/를)까지 통째로 삼켜
# "꽃집을"을 업종명으로 잡아버린다("꽃집을 창업" -> 조사 앞에서 멈추도록 최소 매칭을 선호해야 한다).
NAMED_INDUSTRY = re.compile(r"([가-힣A-Za-z]{2,10}?)\s*(?:을|를|)\s*(?:창업|개업|오픈|차리|열려|열고|준비)")

UNITS = {"억": 100_000_000, "천만": 10_000_000, "백만": 1_000_000, "만": 10_000}
AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(억|천만|백만|만)?\s*원?")
# 월세 힌트 뒤 18자 안에서 금액을 찾는다. 힌트가 없으면 금액을 월세로 읽지 않는다.
RENT = re.compile(r"(월세|임대료|월\s*임대)[^\d]{0,18}(\d+(?:[.,]\d+)?\s*(?:억|천만|백만|만)?\s*원?)")

STAGES = [(re.compile(r"이전|옮기|이사"), "RELOCATING"),
          (re.compile(r"2호점|두\s*번째|분점|추가\s*매장"), "SECOND_STORE"),
          (re.compile(r"처음|첫\s*가게|초보|신규"), "PRE_OPEN")]
TYPES = [(re.compile(r"프랜차이즈|가맹"), "FRANCHISE"),
         (re.compile(r"개인\s*창업|독립|자체\s*브랜드"), "INDEPENDENT")]
PRIORITIES = [(re.compile(r"안정|오래|버티|리스크|위험"), "STABILITY"),
              (re.compile(r"유동인구|손님|수요|매출"), "DEMAND"),
              (re.compile(r"저렴|싼|비용|임대료|월세\s*낮"), "COST"),
              (re.compile(r"성장|확장|뜨는|상권\s*발전"), "GROWTH")]

MAX_KRW = 100_000_000_000


def amount_from(text: str) -> int | None:
    """'300만원'·'1억'·'300'을 원 단위 정수로. 단위 없는 수는 만원 관행을 따른다.

    AI 경로도 이 함수를 쓴다 — 모델은 근거 구간만 지목하고 산술은 코드가 한다
    (부록 A 불변조건 4)."""
    match = AMOUNT.search(text)
    if not match:
        return None
    try:
        raw = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = match.group(2)
    value = round(raw * UNITS[unit]) if unit else round(raw * 10_000)
    if value <= 0 or value > MAX_KRW:
        return None
    return value


def _field(value: Any = None, evidence: str | None = None) -> dict[str, Any]:
    return {"value": value, "evidence": evidence}


def _first(patterns: list[tuple[re.Pattern[str], str]], text: str) -> dict[str, Any]:
    for pattern, value in patterns:
        match = pattern.search(text)
        if match:
            return _field(value, match.group(0))
    return _field()


def _district(text: str) -> dict[str, Any]:
    # 전체 이름을 먼저 찾고, 없을 때만 "마포에서"처럼 조사를 뗀 어간을 본다. 어간이 한 글자인
    # 중구는 "준비 중이에요"의 "중"에 걸려 자치구를 통째로 잘못 채우므로 어간 검색에서 제외한다.
    for name in SEOUL_DISTRICTS:
        if name in text:
            return _field(name, name)
    for name in SEOUL_DISTRICTS:
        stem = name[:-1]
        if len(stem) >= 2 and stem in text:
            return _field(name, stem)
    return _field()


def _industry(text: str) -> dict[str, Any]:
    for pattern, name in INDUSTRY_HINTS:
        match = pattern.search(text)
        if match:
            return _field(name, match.group(0))
    named = NAMED_INDUSTRY.search(text)
    if named:
        return _field(named.group(1), named.group(1))
    return _field()


def _rent(text: str) -> dict[str, Any]:
    match = RENT.search(text)
    if not match:
        return _field()
    value = amount_from(match.group(2))
    return _field(value, match.group(0)) if value is not None else _field()


def parse_conditions(text: str) -> dict[str, dict[str, Any]]:
    """문장이 실제로 말한 필드만 채운다. 말하지 않은 것은 value·evidence 모두 None 이다."""
    return {
        "industry": _industry(text),
        "district": _district(text),
        "monthly_rent_krw": _rent(text),
        "business_stage": _first(STAGES, text),
        "startup_type": _first(TYPES, text),
        "priority": _first(PRIORITIES, text),
    }
