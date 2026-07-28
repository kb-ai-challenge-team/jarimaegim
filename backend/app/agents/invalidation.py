"""조건이 바뀌면 **무엇이 무효가 되는가.** 결정론이고 모델이 없다.

가드 2는 "같은 조건이면 다시 돌리지 않는다"였다. 그 규칙을 실행 전체에 걸면 조건 한 칸만
고쳐도 열세 축이 전부 다시 돈다 — 사용자가 자치구를 바꿨을 뿐인데 공시 조회까지 다시 하는 것은
느릴 뿐 아니라 같은 답을 다시 받아 오는 낭비다. 반대로 무효 판정을 느슨하게 하면 낡은 판정이
새 조건 옆에 남고, 그게 훨씬 나쁘다.

그래서 **어느 입력이 어느 축을 무효화하는가**를 표로 못박는다. 표에 없는 입력은 아무것도
무효화하지 않는 것이 아니라 **전부 무효화한다**(`_UNKNOWN_INVALIDATES_ALL`) — 모르는 입력이
조용히 아무 영향도 없는 것으로 취급되면, 새 조건을 추가한 사람이 표를 고치는 것을 잊었을 때
낡은 판정이 살아남는다. 안전한 기본값은 "다시 돈다"다.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .registry import AGENT_SPECS

#: 모든 축과 커널의 키. 선언에서 파생한다 — 여기 목록을 따로 적으면 축이 늘 때 어긋난다.
ALL_UNITS: tuple[str, ...] = tuple(item.key for item in AGENT_SPECS)

#: 여력·밴드·스트레스를 계산하는 커널. 금융 프로필만 읽는다.
KERNEL_UNITS: tuple[str, ...] = tuple(
    item.key for item in AGENT_SPECS if item.team == "kernel")

#: 상권·주변을 읽는 입지 축.
WHERE_UNITS: tuple[str, ...] = tuple(
    item.key for item in AGENT_SPECS if item.display_group == "어디")

#: 조회 축(공시·공고)과 시점. 조건의 지리·금액을 읽지 않는다.
LOOKUP_UNITS: tuple[str, ...] = tuple(
    item.key for item in AGENT_SPECS if item.display_group in ("얼마", "언제"))

#: 조건 수립과 메인 종합은 언제나 다시 돈다 — 전자는 입력 그 자체이고, 후자는 나머지를 읽는다.
ALWAYS: tuple[str, ...] = tuple(
    item.key for item in AGENT_SPECS if item.team in ("condition", "main"))

#: 입력 하나가 무효화하는 단위들.
#:
#: 업종은 전부다 — 상권 조회 코드도, 손익분기의 원가 구조도, 공고 대조도 업종에서 갈린다.
#: 자치구는 탐색 공간이므로 입지 축만이고, 금융 프로필은 커널만이다(입지 축은 금액을 읽지 않는다).
DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "industry": ALL_UNITS,
    "district": WHERE_UNITS,
    "equity_krw": KERNEL_UNITS,
    "existing_debt_krw": KERNEL_UNITS,
    "other_monthly_fixed_krw": KERNEL_UNITS,
    "monthly_rent_krw": KERNEL_UNITS,
    "monthly_maintenance_krw": KERNEL_UNITS,
    "key_money_krw": KERNEL_UNITS,
    "deposit_krw": KERNEL_UNITS,
    "area_pyeong": KERNEL_UNITS,
    "fitout_krw": KERNEL_UNITS,
    # 발화는 조건 추출의 입력이다. 추출 결과가 조건을 바꾸면 그 조건 키가 다시 판정하므로,
    # 발화 자체는 조건 수립만 다시 돌리면 된다.
    "utterance": ALWAYS,
    # 우선순위·사업단계·창업형태는 정렬과 문구에만 쓰이고 축의 판정을 바꾸지 않는다.
    "priority": (),
    "business_stage": (),
    "startup_type": (),
    "operating_style": (),
    "budget_krw": (),
    "committed_listing_id": (),
}

_UNKNOWN_INVALIDATES_ALL = ALL_UNITS


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def condition_digests(conditions: dict[str, Any]) -> dict[str, str]:
    """조건을 **키마다** 해시한다. 통짜 지문 하나로는 무엇이 바뀌었는지 알 수 없다."""
    return {key: _digest(conditions.get(key)) for key in conditions}


def invalidated(previous: dict[str, str], current: dict[str, str],
                candidates_changed: bool) -> set[str]:
    """다시 돌려야 하는 단위들.

    후보 집합이 바뀌면 후보마다 판정하는 축은 전부 무효다. 커널은 후보를 읽지 않으므로
    (조건만으로 계산한다) 후보가 바뀌어도 유효하다."""
    stale: set[str] = set(ALWAYS)
    touched = {key for key in set(previous) | set(current)
               if previous.get(key) != current.get(key)}
    for key in touched:
        stale.update(DEPENDENCIES.get(key, _UNKNOWN_INVALIDATES_ALL))
    if candidates_changed:
        stale.update(WHERE_UNITS)
        stale.update(LOOKUP_UNITS)
    return stale
