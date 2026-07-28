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
# 쉼표로 자릿수를 묶은 숫자(1,200)를 우선 매칭하고, 아니면 일반 숫자(소수 포함)로 떨어진다.
# 쉼표를 소수점과 한 문자 클래스로 묶던 예전 [.,] 는 "3,000,000" 의 뒷자리를 잘라 먹었다 —
# 한국어 금액 표기의 쉼표는 천단위 구분자이지 소수점이 아니므로 두 역할을 더는 섞지 않는다.
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
AMOUNT = re.compile(r"(" + NUMBER + r")\s*(억|천만|백만|만)?\s*원?")
# 월세 힌트 뒤 18자 안에서 금액을 찾는다. 힌트가 없으면 금액을 월세로 읽지 않는다.
# amount_from 이 이 그룹(2)을 그대로 받아 파싱하므로 숫자 패턴은 AMOUNT 와 반드시 일치해야 한다.
RENT = re.compile(r"(월세|임대료|월\s*임대)[^\d]{0,18}(" + NUMBER + r"\s*(?:억|천만|백만|만)?\s*원?)")

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
    """'300만원'·'1억 5천만원'·'300'·'3,000,000원'을 원 단위 정수로. 두 경로의 유일한 산술이다.

    성분마다 세 갈래 규칙을 따른다:
    (1) 억/천만/백만/만 단위어가 있으면 그 단위를 곱한다.
    (2) 단위어가 없고 숫자가 1만 미만이면 만원 관행을 적용한다 — "월세 300" 은 300만원이다.
    (3) 단위어가 없고 숫자가 1만 이상이면 그대로 원 단위로 읽는다 — "3,000,000" 을 쓴 사람은
        정확히 그 금액을 뜻한 것이지, 300억을 뜻한 게 아니다.
    쉼표는 천단위 구분자로만 벗겨내고 자릿수 판단에는 관여하지 않는다.

    **인접한 성분만 더한다.** "1억 5천만원" 은 한 금액의 두 성분이므로 더해야 하지만,
    "월세 300, 관리비 20" 의 20 은 다른 항목이다. 성분 사이에 공백 아닌 것이 끼면 거기서
    멈춘다 — 더 관대하게 두면 사용자가 말하지 않은 금액이 조건에 들어간다.

    금액이 없으면 None 이다. 0 을 돌려주면 "월세 0원" 이라는 조건이 조용히 만들어진다.

    AI 경로도 이 함수를 쓴다 — 모델은 근거 구간만 지목하고 산술은 코드가 한다
    (부록 A 불변조건 4). `agents/conditions.resolve_mention` 도 같은 이유로 이것을 부른다:
    실행 경로가 자체 산술을 가지면 화면이 읽은 값과 실행이 읽는 값이 갈라진다."""
    total, found, cursor = 0, False, None
    for match in AMOUNT.finditer(text or ""):
        if cursor is not None and text[cursor:match.start()].strip():
            # 앞 성분과 공백만으로 이어지지 않았다. 여기서부터는 다른 항목이다.
            break
        try:
            raw = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if raw <= 0:
            continue
        unit = match.group(2)
        if unit:
            value = round(raw * UNITS[unit])
        elif raw < 10_000:
            value = round(raw * 10_000)
        else:
            value = round(raw)
        total += value
        found = True
        cursor = match.end()
    if not found or total <= 0 or total > MAX_KRW:
        return None
    return total


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
    return _field(value, match.group(0).strip()) if value is not None else _field()


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
