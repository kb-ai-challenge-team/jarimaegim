"""에이전트 한 개가 무엇을 선언하고 무엇을 돌려주는지에 대한 계약.

설계 근거 — 제안서 06장 "LLM 멀티에이전트 신뢰 가드 3종":

  가드 1 · 숫자는 도구 결과만. 각 서브에이전트는 조회 도구와 순수 계산기를 갖는다. 그래서
    `AgentOutcome.data` 에 들어가는 값은 전부 코드가 만든 것이고, 이 모듈에는 LLM 을 부르는
    경로가 없다. "AI가 설명하고 코드가 계산한다"를 멀티에이전트에서 성립시키는 방법은
    수치 경로에 LLM 을 아예 두지 않는 것뿐이다.

  가드 3 · 미검증 축은 기본 비활성. 그래서 `AgentSpec` 이 원천을 선언하고, 실행 결과는
    `ok` 만이 아니라 `integration_pending` / `withheld` 를 1급 상태로 갖는다. 원천이 없을 때
    중립값으로 채우면 근거가 없는데도 후보가 통과하거나 탈락한다.

`evidence_grade` 가 `None` 인 것과 `"U"` 인 것은 다른 말이다. None 은 "이 에이전트는 입지
주장을 하지 않는다"(금융·타이밍·조건·메인)이고, U 는 "입지 주장을 하려 했으나 근거가 막혔다"이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from ..models import Provenance

#: 화면이 축을 묶어 보여주는 세 갈래. **실행 단위가 아니다.**
#:
#: 실행 그래프의 단위는 축 하나이고, 이 값은 그 축들을 화면에서 어떻게 모아 보여줄지만 정한다.
#: 둘을 겹쳐 놓으면 "같이 보여주는 것"이 "같이 실행되는 것"이 되고, 한 축이 죽을 때 함께 죽는
#: 이유가 데이터 원천이 아니라 화면 배치가 된다 — 팀 계층이 정확히 그렇게 굳었다.
DisplayGroup = Literal["어디", "얼마", "언제"]


class AgentStatus(StrEnum):
    """에이전트 한 번의 실행 결과. 팀장과 화면이 같이 읽으므로 계약이다.

    ok                  — 판정했다. `data` 에 값이 있다.
    integration_pending — 원천이 연동되지 않아 시도조차 못 했다. 축을 켜지 않는다.
    withheld            — 원천은 있으나 이 입력으로는 판정을 유보한다(근거 부족·충돌).
                          `integration_pending` 과 구분하는 이유: 전자는 "우리가 아직 안 붙였다",
                          후자는 "붙였지만 이 건은 말할 수 없다"이고, 사용자가 할 수 있는 일이 다르다.
    failed              — 실행 자체가 실패했다. 탈락 근거로 절대 쓰지 않는다(팀 계약).
    """

    OK = "ok"
    INTEGRATION_PENDING = "integration_pending"
    WITHHELD = "withheld"
    FAILED = "failed"


#: 축을 켠 것으로 볼 수 있는 상태. `withheld` 는 포함하지 않는다 — 판정을 유보한 축을
#: "가동 중"으로 세면 화면의 "12개 축 중 N개 가동"이 실제보다 낙관적으로 보인다.
ACTIVE_STATUSES = frozenset({AgentStatus.OK})


@dataclass(frozen=True)
class AgentSpec:
    """에이전트의 정적 선언. 실행 전에 화면이 읽을 수 있어야 하므로 런타임 값을 담지 않는다."""

    key: str
    team: str
    name: str
    #: 답이 나온다면 어디서 나오는가. 원천이 아직 없으면 "무엇이 있어야 하는가"를 적는다.
    source_name: str
    #: 이 에이전트가 내는 결론의 한 줄 정의.
    produces: str
    #: 입지 주장을 하는 에이전트만 A/B/C/U 를 선언한다. 나머지는 None.
    evidence_grade: str | None = None
    #: 화면이 이 축을 어느 묶음에 놓는가. 판단 축만 갖는다 — 메인(종합)과 조건(수립)은
    #: 판단 축이 아니므로 None 이고, 묶음에 끼면 화면의 축 개수가 실제 판단 개수보다 많아진다.
    display_group: DisplayGroup | None = None

    def outcome(self, status: AgentStatus, *, message: str | None = None,
                data: dict[str, Any] | None = None,
                provenance: Provenance | None = None,
                required_actions: list[str] | None = None) -> "AgentOutcome":
        return AgentOutcome(key=self.key, team=self.team, name=self.name, status=status,
                            message=message, data=data or {}, provenance=provenance,
                            required_actions=required_actions or [])


@dataclass(frozen=True)
class AgentOutcome:
    """에이전트 한 번의 실행 결과."""

    key: str
    team: str
    name: str
    status: AgentStatus
    message: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None
    required_actions: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATUSES


@dataclass(frozen=True)
class AxisReport:
    """실행 단위 하나가 낸 결과.

    팀 보고가 아니다 — **멈출지 말지를 스스로 선언하지 않는다.** 예전에는 `blocking` 과
    `halted` 가 여기 있었고, 세 곳(기본 · 조건 · 금융)이 각자 다른 규칙으로 그것을 덮어썼다.
    그 결과 논리적으로 독립인 판단이 팀 경계에 인질로 잡혔다: 금융 밴드가 실패하면 "이 자리에
    손님이 있나"까지 함께 멈췄다.

    지금 중단 판정은 `orchestrator` 한 곳에만 있다. 여기 있는 것은 사실뿐이다 — 어느 축들이
    무엇을 냈는가. 그 사실을 읽고 무엇을 멈출지 정하는 것은 메인의 책임이다.
    """

    key: str
    name: str
    outcomes: list[AgentOutcome]
    message: str | None = None

    @property
    def active_count(self) -> int:
        return sum(1 for item in self.outcomes if item.active)
