"""에이전트 선언.

**판단 축은 `display_group` 을 가진 것이 전부다.** 밴드·스트레스는 커널이라 축이 아니고
(`team="kernel"`), 조건 수립과 메인 종합도 판단 축이 아니다. 화면의 "N개 축"은 이 필드를
세어 얻는다 — 개수를 문자열로 적어 두면 축이 늘 때마다 두 곳이 어긋난다.

키는 `main.py` 의 `analysis_axes()` 가 이미 쓰던 이름을 그대로 가져왔다. 축 9개가 그대로
서브에이전트 9개이므로, 두 곳이 다른 이름을 쓰면 같은 것을 두 번 정의하게 된다.

여기 있는 것은 선언뿐이다. "지금 켜지는가"는 설정과 데이터에 달렸고 실행 시점에 정해진다.
"""
from __future__ import annotations

from .contracts import AgentSpec

AGENT_SPECS: tuple[AgentSpec, ...] = (
    AgentSpec(
        key="main.integrate", team="main", name="메인 에이전트",
        source_name="팀 보고 — 자체 원천 없음",
        produces="업무 분담 · 대화 요약 · 팀 보고 통합 · 문서 초안",
    ),
    AgentSpec(
        key="condition.location", team="condition", name="입지 조건 확정",
        source_name="사용자 대화 · 케이스 입력",
        produces="업종 · 자치구 · 평수 · 운영형태 · 희망 임대조건",
    ),
    AgentSpec(
        key="condition.finance", team="condition", name="금융 프로필 확정",
        source_name="사용자 입력 (마이데이터는 게이트 off)",
        produces="자기자본 · 기존부채 · 월고정지출",
    ),

    # ── 얼마 · 금융처방 팀 ─────────────────────────────────────────────
    AgentSpec(
        key="finance.band", team="kernel", name="조달 밴드 산출",
        source_name="제도 파라미터 (config/policy-params.json)",
        produces="자기자본선 · 권장 조달선 · 최대 조달선 · 손익분기선",
    ),
    AgentSpec(
        key="finance.stress", team="kernel", name="창업 금융 스트레스 테스트",
        source_name="제도 파라미터 (스트레스 시나리오)",
        produces="매출 −20% 시 상환 부담과 현금소진 개월",
    ),
    AgentSpec(
        key="finance.kb_products", team="finance", name="금융상품",
        source_name="금융감독원 금융상품통합비교공시 (finlife)",
        produces="상품 · 금리 조합 시뮬레이션",
        display_group="얼마",
    ),
    AgentSpec(
        key="finance.subsidy", team="finance", name="정부지원",
        source_name="기업마당 · K-Startup 공고 인덱스",
        produces="조달선을 밀어올리는 지원금 반영분",
        display_group="얼마",
    ),

    # ── 어디 · 입지추천 팀 ─────────────────────────────────────────────
    AgentSpec(
        key="location.demand", team="location", name="수요",
        source_name="서울시 우리마을가게 상권분석서비스",
        produces="유동 · 상주 · 직장인구, 배후 구매력",
        evidence_grade="B", display_group="어디",
    ),
    AgentSpec(
        key="location.competition", team="location", name="경쟁",
        source_name="서울시 우리마을가게 상권분석서비스",
        produces="동종 점포밀도, 신규 · 폐업 추세",
        evidence_grade="B", display_group="어디",
    ),
    AgentSpec(
        key="location.viability", team="location", name="매출",
        source_name="서울시 우리마을가게 상권분석서비스 (추정매출)",
        produces="목표매출을 상권 동종 매출 분포에 대입한 위치",
        evidence_grade="B", display_group="어디",
    ),
    AgentSpec(
        key="location.survival", team="location", name="생존이력",
        source_name="행정안전부 지방행정 인허가데이터 — 개별 점포 이력 코호트",
        produces="18 / 24개월 영업유지율",
        evidence_grade="A", display_group="어디",
    ),

    AgentSpec(
        key="location.access", team="location", name="접근성",
        source_name="카카오 로컬 (presale-mcp) — 주변 시설 스캔",
        produces="역·버스·주요 시설과의 인접 관계",
        # 등급을 선언하지 않는다. 원천이 개별 좌표 조회라 상권 집계(B)도 개별 이력(A)도 아니고,
        # 좌표계 실측이 끝나기 전에는 이 축이 무엇을 말할 수 있는지 자체가 정해지지 않았다.
        display_group="어디",
    ),

    # ── 언제 · 타이밍 팀 ──────────────────────────────────────────────
    AgentSpec(
        key="timing.policy", team="timing", name="시점",
        source_name="개발 · 정책 일정 원천 (미확보)",
        produces="계약 시점 권고 또는 판단 유보",
        display_group="언제",
    ),
)

_BY_KEY = {item.key: item for item in AGENT_SPECS}


def spec(key: str) -> AgentSpec:
    return _BY_KEY[key]


def specs_for(team: str) -> tuple[AgentSpec, ...]:
    return tuple(item for item in AGENT_SPECS if item.team == team)
