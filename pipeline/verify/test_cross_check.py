import pytest

from cross_check import BASELINE_KRW_PER_M2, RATIO_MAX, RATIO_MIN, evaluate_district, summarize


def band(p50: float) -> dict:
    return {"label": "33~66㎡", "n": 20,
            "monthly_rent_krw": {"p10": p50 * 0.5, "p25": p50 * 0.8, "p50": p50, "p75": p50 * 1.3, "p90": p50 * 2.0, "n": 20},
            "deposit_multiple": {"p10": 10, "p25": 14, "p50": 16, "p75": 20, "p90": 30, "n": 20}}


def district(p50_rent: float, area_p50: float = 50.0) -> dict:
    return {"area": {"p10": 30, "p25": 40, "p50": area_p50, "p75": 60, "p90": 80, "n": 20},
            "bands": {"M": band(p50_rent)}}


def test_baseline_is_the_measured_subway_median():
    assert BASELINE_KRW_PER_M2 == 98770


def test_ratio_window_matches_the_design():
    assert (RATIO_MIN, RATIO_MAX) == (0.5, 3.0)


def test_a_plausible_district_passes():
    # 50㎡ x 98,770 won/㎡ ~= 4.94M won, so the ratio should be about 1.0
    result = evaluate_district("강남구", district(4_938_500))
    assert result["ok"] is True
    assert result["ratio"] == pytest.approx(1.0, abs=0.01)


def test_an_order_of_magnitude_error_fails():
    result = evaluate_district("강남구", district(49_385_000))
    assert result["ok"] is False
    assert result["ratio"] > RATIO_MAX


def test_a_far_too_cheap_district_fails():
    result = evaluate_district("강남구", district(1_000_000))
    assert result["ok"] is False
    assert result["ratio"] < RATIO_MIN


def test_the_largest_band_is_the_representative_one():
    payload = {"area": {"p10": 30, "p25": 40, "p50": 50.0, "p75": 60, "p90": 80, "n": 30},
               "bands": {"S": band(4_938_500) | {"n": 5}, "M": band(9_877_000) | {"n": 25}}}
    result = evaluate_district("강남구", payload)
    assert result["n"] == 25
    assert result["rent_p50"] == 9_877_000


def test_summarize_fails_when_any_district_fails():
    districts = {"강남구": district(4_938_500), "마포구": district(49_385_000)}
    report = summarize(districts)
    assert report["ok"] is False
    assert len(report["results"]) == 2


def test_summarize_passes_when_all_districts_pass():
    districts = {"강남구": district(4_938_500), "마포구": district(3_000_000)}
    assert summarize(districts)["ok"] is True


def test_summarize_rejects_an_empty_distribution():
    with pytest.raises(ValueError, match="no districts"):
        summarize({})
