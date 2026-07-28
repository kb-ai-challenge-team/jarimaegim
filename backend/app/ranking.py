"""후보 순위 계산. 순수 함수만 있고 외부 호출도 LLM도 없다 (부록 A 불변조건 4).

지금까지 후보 순서는 월세 오름차순 하나였다. 업종도 우선순위도 받아만 놓고 쓰지 않아,
'강남구 카페'를 물어도 카페와 무관한 가장 싼 5평짜리가 1순위로 올라왔다. 이 모듈이
그 자리를 대신한다.

두 가지를 지킨다.

1. **판정하지 못한 축은 순위에 관여하지 않는다.** 가중치를 0으로 두는 것이 아니라
   그 축의 가중치를 판정된 축들에 비례 배분한다. 0점 처리하면 데이터가 없는 후보가
   자동으로 나빠지고, 이는 설계 스펙 §3.7 공통규칙 1 위반이다.
2. **점수는 예측이 아니라 정렬 규칙이다.** 여기서 나온 숫자는 매출도 생존확률도 아니며
   화면에도 확률로 표시되지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 우선순위별 축 가중치. 합은 1이며, 사용자가 무엇을 먼저 보겠다고 했는지를 그대로 옮긴 값이다.
# 데이터에서 추정한 계수가 아니라 제품이 선언한 정책이므로 이 파일 한 곳에만 둔다.
PRIORITY_WEIGHTS: dict[str, dict[str, float]] = {
    "STABILITY": {"turnover": 0.40, "competition": 0.20, "demand": 0.15, "sales": 0.15, "cost": 0.10},
    "DEMAND": {"demand": 0.35, "sales": 0.30, "turnover": 0.15, "competition": 0.10, "cost": 0.10},
    "COST": {"cost": 0.45, "turnover": 0.20, "demand": 0.15, "competition": 0.10, "sales": 0.10},
    "GROWTH": {"sales": 0.35, "demand": 0.30, "competition": 0.15, "turnover": 0.10, "cost": 0.10},
}

# 중앙값의 2배를 만점으로 본다. 상한이 없으면 거대 상권 하나가 다른 모든 후보를 0점으로 만든다.
RATIO_CEILING = 2.0

# 축소(shrinkage) 사전 강도. 점포 n곳에서 관측한 비율을 서울 중앙값(=비율 1.0) 쪽으로
# n/(n+SHRINKAGE_PRIOR) 만큼만 인정한다.
#
# 이게 없으면 점포 6곳짜리 행정동이 "서울 중앙값의 617%"로 1순위를 차지한다. 점포가 적을수록
# 비율은 크게 튀는데, 큰 비율이 곧 좋은 입지라는 뜻은 아니다. 값은 서울 전체 업종별 점포 수
# 중앙값과 같은 자릿수(25)로 두었다 — 중앙값만큼의 점포가 모여야 관측값을 절반쯤 믿는다는 뜻이다.
#
# 축소는 **판정에만** 적용된다. 화면에 적히는 숫자는 관측값 그대로이고, 표본 크기가 함께 나간다.
SHRINKAGE_PRIOR = 25.0


def shrink_ratio(ratio: float | None, sample_n: int | None) -> float | None:
    """관측 비율을 표본 크기에 따라 중앙값(1.0) 쪽으로 당긴다. 표본이 없으면 판정하지 않는다."""
    if ratio is None or not sample_n or sample_n <= 0:
        return None
    weight = sample_n / (sample_n + SHRINKAGE_PRIOR)
    return 1.0 + (ratio - 1.0) * weight


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _ratio_score(ratio: float | None, *, high_is_good: bool) -> float | None:
    """중앙값 대비 비율을 0~1 점수로. 판정 불가는 None 이고 0이 아니다."""
    if ratio is None:
        return None
    scaled = clamp01(ratio / RATIO_CEILING)
    return scaled if high_is_good else clamp01(1.0 - scaled)


@dataclass
class CandidateScore:
    candidate_id: str
    total: float
    axes: dict[str, float] = field(default_factory=dict)
    judged_axes: list[str] = field(default_factory=list)
    unjudged_axes: list[str] = field(default_factory=list)


def shrink_percentile(percentile: float | None, sample_n: int | None) -> float | None:
    """백분위를 표본 크기에 따라 중앙(0.5) 쪽으로 당긴다."""
    if percentile is None or not sample_n or sample_n <= 0:
        return None
    weight = sample_n / (sample_n + SHRINKAGE_PRIOR)
    return 0.5 + (percentile - 0.5) * weight


def axis_scores(profile: dict | None, benchmark: dict | None, cost_score: float | None,
                close_rate_percentile: float | None = None) -> dict[str, float | None]:
    """후보 하나의 축별 점수. 근거가 없는 축은 None 으로 남긴다.

    폐업률만 백분위로 들어온다. 서울 100개 업종 중 91개에서 폐업률의 행정동 중앙값이
    0이라 중앙값 대비 비율이 정의되지 않기 때문이다 — 자세한 이유는
    `TradeAreaService._index_close_rates` 의 주석에 있다.
    """
    scores: dict[str, float | None] = {"demand": None, "competition": None, "turnover": None, "sales": None, "cost": cost_score}
    if not profile or not benchmark:
        return scores

    stores = profile.get("store_count") or 0
    footfall = profile.get("footfall_monthly")
    if footfall and stores and benchmark.get("footfall_per_store_median"):
        scores["demand"] = _ratio_score(
            shrink_ratio((footfall / stores) / benchmark["footfall_per_store_median"], stores), high_is_good=True)
    if stores and benchmark.get("store_count_median"):
        # 동종 점포가 서울 중앙값보다 조밀할수록 경쟁 부담이 크다고 읽는다.
        scores["competition"] = _ratio_score(
            shrink_ratio(stores / benchmark["store_count_median"], stores), high_is_good=False)
    adjusted = shrink_percentile(close_rate_percentile, stores)
    if adjusted is not None:
        # 백분위가 낮을수록(폐업이 드물수록) 좋다. 이미 0~1이라 상한을 다시 씌우지 않는다.
        scores["turnover"] = clamp01(1.0 - adjusted)
    if profile.get("sales_per_store_krw") is not None and benchmark.get("sales_per_store_krw_median"):
        # 매출은 매출을 확인한 점포 수가 표본이다. 행정동 전체 점포 수보다 작을 수 있다.
        scores["sales"] = _ratio_score(
            shrink_ratio(profile["sales_per_store_krw"] / benchmark["sales_per_store_krw_median"],
                         profile.get("sales_store_count")), high_is_good=True)
    return scores


def weighted_total(scores: dict[str, float | None], priority: str) -> tuple[float, list[str], list[str]]:
    """판정된 축만으로 가중 평균을 낸다. 빠진 축의 가중치는 남은 축에 비례 배분된다.

    판정된 축이 하나도 없으면 0.0 과 빈 목록을 돌려준다. 호출자는 그 후보를 점수로
    비교하지 않고 별도 묶음으로 다뤄야 한다.
    """
    weights = PRIORITY_WEIGHTS.get(priority, PRIORITY_WEIGHTS["STABILITY"])
    judged = [axis for axis, score in scores.items() if score is not None]
    unjudged = [axis for axis, score in scores.items() if score is None]
    total_weight = sum(weights[axis] for axis in judged)
    if total_weight <= 0:
        return 0.0, [], unjudged
    total = sum(weights[axis] * float(scores[axis]) for axis in judged) / total_weight
    return total, judged, unjudged


def cost_scores(rents: list[int]) -> dict[int, float]:
    """월세를 후보 집합 안에서 0~1로 정규화한다. 가장 싼 곳이 1점이다.

    자치구 간 비교가 아니라 지금 보고 있는 후보들 사이의 상대 위치다. 후보가 전부
    같은 월세면 비용 축이 순위를 흔들 이유가 없으므로 모두 1점으로 둔다.
    """
    if not rents:
        return {}
    low, high = min(rents), max(rents)
    if high == low:
        return {rent: 1.0 for rent in rents}
    return {rent: (high - rent) / (high - low) for rent in set(rents)}
