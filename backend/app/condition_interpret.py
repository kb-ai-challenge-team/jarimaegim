from __future__ import annotations
from typing import Any

from .condition_parse import FIELDS, amount_from
from .districts import SEOUL_DISTRICTS
from .industry import canonical

# AI 경로와 규칙 경로가 함께 통과하는 단 하나의 게이트.
#
# 부록 A 불변조건 4("AI는 설명, 계산은 코드")를 프롬프트 문구가 아니라 코드로 강제한다.
# 핵심은 evidence 부분문자열 검증이다 — 모델이 "카페면 보통 월세 300쯤"이라고 채우면 그
# 근거 문구가 사용자 원문에 없으므로 여기서 죽는다. 프롬프트는 어길 수 있지만 이 검사는 없다.
#
# 금액은 모델이 준 value 를 믿지 않고 evidence 구간에서 코드가 다시 계산한다. 모델이 하는 일은
# "어느 구간이 월세를 말하는가"를 지목하는 것뿐이다.

# 열거값은 tuple 로 둔다. frozenset 은 in 검사에서 값을 해시하므로 모델이 리스트나 dict 를
# 넣으면 TypeError 로 터진다 — SEOUL_DISTRICTS 가 tuple 인 것과 같은 이유다. tuple 의 in 은
# 동등 비교라 어떤 타입이 와도 조용히 False 가 된다.
STAGES = ("PRE_OPEN", "RELOCATING", "SECOND_STORE")
TYPES = ("INDEPENDENT", "FRANCHISE", "UNDECIDED")
PRIORITIES = ("STABILITY", "DEMAND", "COST", "GROWTH")
ENUMS = {"business_stage": STAGES, "startup_type": TYPES, "priority": PRIORITIES}

# 케이스 모델(models.py CaseInput.industry)의 상한. 넘으면 422 대신 여기서 떨어뜨린다.
MAX_INDUSTRY_LEN = 120


def _blank() -> dict[str, Any]:
    return {"value": None, "evidence": None}


def sanitize(text: str, proposed: dict[str, Any]) -> dict[str, Any]:
    """제안된 필드를 검증해 살아남은 것만 돌려준다. 실패한 필드는 조용히 버리고 unresolved 로 옮긴다.

    응답 전체를 버리지 않는 것이 의도다 — 여섯 필드 중 하나가 어긋났다고 나머지 다섯을
    사용자에게 다시 입력받게 만들 이유가 없다."""
    # 이 함수는 모델 응답의 격리 경계다. 어떤 모양이 와도 예외를 던지지 않고 빈 제안으로 떨어진다.
    if not isinstance(text, str):
        text = ""
    if not isinstance(proposed, dict):
        proposed = {}
    notes: list[str] = []
    fields = {name: _keep(text, name, proposed.get(name), notes) for name in FIELDS}
    unresolved = [name for name, field in fields.items() if field["value"] is None]
    kept = len(FIELDS) - len(unresolved)
    message = (f"말씀에서 조건 {kept}개를 찾았습니다. 맞는지 확인해 주세요."
               if kept else "말씀에서 확정할 수 있는 조건을 찾지 못했습니다. 아래에서 직접 골라 주세요.")
    if notes:
        message = f"{message} {' '.join(notes)}"
    return {"fields": fields, "unresolved": unresolved, "message": message}


def _keep(text: str, name: str, raw: Any, notes: list[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _blank()
    evidence, value = raw.get("evidence"), raw.get("value")
    # 게이트 1 — 근거 없는 값은 통과하지 못한다.
    if not isinstance(evidence, str) or not evidence or evidence not in text:
        return _blank()
    if name == "monthly_rent_krw":
        # 게이트 2 — 산술은 코드가 한다. 모델이 준 숫자는 읽지 않는다.
        amount = amount_from(evidence)
        return {"value": amount, "evidence": evidence} if amount is not None else _blank()
    if name == "district":
        # 게이트 3 — 서울 25개 자치구 밖은 거절한다(부록 A 불변조건 6).
        if value not in SEOUL_DISTRICTS:
            notes.append("서울 25개 자치구만 지원해 지역은 직접 골라 주세요.")
            return _blank()
        return {"value": value, "evidence": evidence}
    if name in ENUMS:
        # 게이트 4 — 정의된 열거값만 통과한다.
        return {"value": value, "evidence": evidence} if value in ENUMS[name] else _blank()
    # industry — 자유 문자열이지만 길이와 타입은 케이스 모델의 상한을 따른다.
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_INDUSTRY_LEN:
        return _blank()
    # 게이트 5 — 모델은 "카페를 준비 중"에서 업종을 `카페를` 로 뽑는다. 인용은 사용자의 말
    # 그대로여야 하니 그 자체는 옳지만, 조사가 붙은 채로는 상권 코드로 풀리지 않아 후보가
    # 근거 B 대신 근거 C 로 떨어진다. 이미 풀리는 값은 canonical 이 손대지 않으므로, 이
    # 한 줄이 할 수 있는 일은 못 찾던 것을 찾게 만드는 것뿐이다.
    return {"value": canonical(value), "evidence": evidence}
