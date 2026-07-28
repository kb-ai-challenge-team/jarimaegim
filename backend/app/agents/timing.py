"""언제 — 타이밍 팀.

잔존 후보에 대해서만 돈다. 개발·정책 일정 원천이 확보되지 않았으므로 현재는 언제나
"일정 확인 전 판단 유보"를 반환하고, 후보는 한 건도 건드리지 않는다.

이 팀을 지우지 않고 빈 채로 남겨 두는 것이 설계 결정이다 — 제품 정의의 "언제"를 삭제하면
공백이 보이지 않게 되고, 그러면 채워지지 않았다는 사실 자체가 화면에서 사라진다.

문서가 주어지면 모델이 후보와 관련 있는 것을 고른다. 그래도 **상태는 그대로 유보다**:
관련성 판단은 일정 원천이 아니고, 관련 문서가 있다는 사실만으로 계약 시점을 권고할 수는 없다.
검증된 일정 원천이 붙기 전에 이 축이 켜지면 그것이 가드 3 위반이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import AgentStatus, TeamReport
from .llm import AgentLLM, ChoiceSchema, Decision, Pick
from .registry import spec

_WITHHELD = ("개발·정책 일정 원천이 확보되지 않아 계약 시점을 권고하지 않습니다. "
             "일정 확인 전 판단 유보입니다.")

SCHEDULE_SCHEMA_NAME = "select_schedule_documents"


@dataclass(frozen=True)
class TimingReport(TeamReport):
    surviving: list[dict[str, Any]] = field(default_factory=list)


class TimingTeam:
    team = "timing"
    name = "타이밍 팀"

    def __init__(self, *, llm: AgentLLM | None = None,
                 documents: list[dict[str, Any]] | None = None):
        self.llm = llm
        self.documents = documents or []

    def run(self, candidates: list[dict[str, Any]],
            decision: Decision | None = None) -> TimingReport:
        decision = decision or Decision.deterministic("timing.policy", schema=SCHEDULE_SCHEMA_NAME)
        relevant = {str(item) for item in decision.chosen.get("relevant", [])}
        outcome = spec("timing.policy").outcome(
            AgentStatus.INTEGRATION_PENDING, message=_WITHHELD,
            data={"decision": decision.as_data(),
                  "documents": [{"id": item.get("id"), "title": item.get("title"),
                                 "relevant": str(item.get("id")) in relevant}
                                for item in self.documents]},
            required_actions=["재개발·교통·주택공급·공사 일정 원천을 확보해야 시점을 말할 수 있습니다."])
        # 후보는 그대로 통과시킨다. 판정하지 못한 팀이 후보를 줄이면 안 된다.
        return TimingReport(team=self.team, name=self.name, outcomes=[outcome], blocking=False,
                            surviving=list(candidates))

    async def arun(self, candidates: list[dict[str, Any]]) -> TimingReport:
        return self.run(candidates, await self.decide())

    async def decide(self) -> Decision:
        if self.llm is None or not self.documents:
            # 읽을 문서가 없으면 관련성을 판단할 대상도 없다(가드 3 · 예산).
            return Decision.deterministic("timing.policy", schema=SCHEDULE_SCHEMA_NAME)
        schema = ChoiceSchema(
            name=SCHEDULE_SCHEMA_NAME,
            description="후보 지역과 관련 있는 일정 문서를 고른다. 시점을 권고하는 것이 아니다.",
            fields={"relevant": Pick(tuple(str(item.get("id")) for item in self.documents),
                                     multi=True, description="목록에 있는 문서 id 만")})
        return await self.llm.choose(
            agent_key="timing.policy", schema=schema,
            instruction=("후보 지역과 겹치는 문서만 고르세요. 일정을 읽어 내거나 시점을 권고하지 마세요."),
            context={"문서": [{"id": item.get("id"), "title": item.get("title")}
                            for item in self.documents]})
