import pytest

from app.ranking import PRIORITY_WEIGHTS, axis_scores, cost_scores, shrink_ratio, weighted_total

BENCHMARK = {
    "footfall_per_store_median": 100_000, "store_count_median": 25,
    "close_rate_median": 4.0, "sales_per_store_krw_median": 20_000_000,
}


def profile(**overrides):
    base = {"store_count": 25, "footfall_monthly": 2_500_000, "close_rate": 4.0,
            "sales_per_store_krw": 20_000_000, "sales_store_count": 25}
    base.update(overrides)
    return base


def test_every_priority_weights_sum_to_one():
    for priority, weights in PRIORITY_WEIGHTS.items():
        assert round(sum(weights.values()), 6) == 1.0, f"{priority} weights must sum to 1"


def test_every_priority_covers_the_same_axes():
    axes = {frozenset(weights) for weights in PRIORITY_WEIGHTS.values()}
    assert len(axes) == 1, "축 집합이 우선순위마다 다르면 가중치 재배분이 어긋난다"


def test_an_unjudged_axis_does_not_drag_the_score_down():
    """빠진 축을 0점으로 채우면 데이터 없는 후보가 자동으로 나빠진다 — 설계 스펙 §3.7 공통규칙 1."""
    complete = {"demand": 1.0, "competition": 1.0, "turnover": 1.0, "sales": 1.0, "cost": 1.0}
    partial = {"demand": 1.0, "competition": 1.0, "turnover": 1.0, "sales": None, "cost": 1.0}
    assert weighted_total(complete, "STABILITY")[0] == weighted_total(partial, "STABILITY")[0] == 1.0


def test_missing_axis_weight_is_redistributed_proportionally():
    scores = {"demand": 1.0, "competition": 0.0, "turnover": None, "sales": None, "cost": None}
    total, judged, unjudged = weighted_total(scores, "DEMAND")
    # demand 0.35, competition 0.10 만 남는다 → 1.0*0.35 / 0.45
    assert total == pytest.approx(0.35 / 0.45)
    assert set(judged) == {"demand", "competition"}
    assert set(unjudged) == {"turnover", "sales", "cost"}


def test_a_candidate_with_no_judged_axis_scores_zero_and_reports_it():
    total, judged, unjudged = weighted_total({k: None for k in PRIORITY_WEIGHTS["STABILITY"]}, "STABILITY")
    assert total == 0.0
    assert judged == []
    assert len(unjudged) == 5


def test_priority_changes_the_ordering():
    """비용이 싼 후보와 매출이 좋은 후보는 우선순위에 따라 순서가 뒤집혀야 한다."""
    cheap = {"demand": 0.2, "competition": 0.5, "turnover": 0.5, "sales": 0.2, "cost": 1.0}
    lucrative = {"demand": 0.9, "competition": 0.5, "turnover": 0.5, "sales": 0.9, "cost": 0.0}
    assert weighted_total(cheap, "COST")[0] > weighted_total(lucrative, "COST")[0]
    assert weighted_total(lucrative, "DEMAND")[0] > weighted_total(cheap, "DEMAND")[0]


def test_shrinkage_pulls_thin_samples_toward_the_median():
    # 점포 6곳에서 나온 6배는 그대로 인정되지 않는다.
    assert shrink_ratio(6.0, 6) < 3.0
    # 표본이 커질수록 관측값에 가까워진다.
    assert shrink_ratio(6.0, 1000) > shrink_ratio(6.0, 100) > shrink_ratio(6.0, 6)
    # 중앙값과 같은 관측값은 표본 크기와 무관하게 그대로다.
    assert shrink_ratio(1.0, 3) == 1.0


def test_shrinkage_without_a_sample_is_not_a_judgement():
    assert shrink_ratio(2.0, None) is None
    assert shrink_ratio(2.0, 0) is None
    assert shrink_ratio(None, 100) is None


def test_high_closure_percentile_scores_worse_than_low():
    calm = axis_scores(profile(), BENCHMARK, None, close_rate_percentile=0.1)
    churny = axis_scores(profile(), BENCHMARK, None, close_rate_percentile=0.9)
    assert calm["turnover"] > churny["turnover"]


def test_turnover_is_judged_even_when_the_median_closure_is_zero():
    """서울 100개 업종 중 91개가 폐업률 중앙값 0이다. 비율이었다면 여기서 축이 꺼졌다."""
    zero_median = {**BENCHMARK, "close_rate_median": 0}
    scores = axis_scores(profile(close_rate=0.0), zero_median, None, close_rate_percentile=0.3)
    assert scores["turnover"] is not None


def test_turnover_without_a_percentile_is_not_judged():
    assert axis_scores(profile(), BENCHMARK, None, close_rate_percentile=None)["turnover"] is None


def test_dense_competition_scores_worse_than_sparse():
    sparse = axis_scores(profile(store_count=10, footfall_monthly=1_000_000, sales_store_count=10), BENCHMARK, None)
    dense = axis_scores(profile(store_count=80, footfall_monthly=8_000_000, sales_store_count=80), BENCHMARK, None)
    assert sparse["competition"] > dense["competition"]


def test_axes_without_source_data_stay_none_rather_than_zero():
    scores = axis_scores(profile(sales_per_store_krw=None, sales_store_count=0, footfall_monthly=None),
                         BENCHMARK, None, close_rate_percentile=0.5)
    assert scores["sales"] is None
    assert scores["demand"] is None
    assert scores["turnover"] is not None
    assert scores["competition"] is not None


def test_no_profile_means_no_axis_is_judged():
    scores = axis_scores(None, BENCHMARK, 0.5, close_rate_percentile=0.5)
    assert scores == {"demand": None, "competition": None, "turnover": None, "sales": None, "cost": 0.5}


def test_cost_score_favours_the_cheaper_rent():
    scores = cost_scores([1_000_000, 2_000_000, 3_000_000])
    assert scores[1_000_000] == 1.0
    assert scores[3_000_000] == 0.0
    assert scores[2_000_000] == pytest.approx(0.5)


def test_identical_rents_do_not_let_cost_break_the_ordering():
    assert cost_scores([2_000_000, 2_000_000]) == {2_000_000: 1.0}


def test_cost_scores_of_an_empty_set_is_empty():
    assert cost_scores([]) == {}
