import json

import pytest

from app.industry import resolve
from app.models import AnalysisResult
from app.trade_area import TradeAreaService, TradeAreaUnavailable

PROFILE = {
    "generated_at": "2026-07-28T00:00:00Z", "quarter": "20261",
    "source_name": "서울시 우리마을가게 상권분석서비스", "spatial_unit": "행정동 내 상권 집계",
    "limitations": ["상권 경계 안의 집계이며 개별 점포의 실적이 아닙니다."],
    "industry_names": {"CS100010": "커피-음료"},
    "benchmarks": {"CS100010": {
        "footfall_per_store_median": 100_000, "store_count_median": 25,
        "close_rate_median": 4.0, "sales_per_store_krw_median": 20_000_000,
    }},
    "dongs": {
        "11680600": {
            "district": "강남구", "admin_dong": "대치1동", "trade_area_count": 2, "footfall_monthly": 3_000_000,
            "industries": {"CS100010": {
                "store_count": 30, "similar_store_count": 30, "franchise_store_count": 8,
                "opened_store_count": 1, "closed_store_count": 3, "open_rate": 3.33, "close_rate": 10.0,
                "monthly_sales_krw": 300_000_000, "monthly_sales_count": 1000,
                "sales_per_store_krw": 10_000_000, "sales_store_count": 30,
                "trade_area_count": 2, "sales_trade_area_count": 2,
            }},
        },
    },
}


@pytest.fixture
def service(tmp_path):
    path = tmp_path / "trade-area.seoul.json"
    path.write_text(json.dumps(PROFILE), encoding="utf-8")
    return TradeAreaService(path)


def test_a_missing_file_disables_the_axis_instead_of_raising(tmp_path):
    service = TradeAreaService(tmp_path / "absent.json")
    assert service.available is False
    result = service.lookup("11680600", "CS100010")
    assert isinstance(result, TradeAreaUnavailable)
    assert result.reason


def test_an_unreadable_file_disables_the_axis_instead_of_raising(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert TradeAreaService(path).available is False


def test_lookup_returns_the_industry_aggregate(service):
    found = service.lookup("11680600", "CS100010")
    assert found["admin_dong"] == "대치1동"
    assert found["store_count"] == 30
    assert found["industry_name"] == "커피-음료"


@pytest.mark.parametrize("dong,industry,fragment", [
    (None, "CS100010", "행정동을 확인하지 못해"),
    ("11680600", None, "업종 분류에 연결되지 않았"),
    ("99999999", "CS100010", "집계한 상권이 없습니다"),
    ("11680600", "CS100001", "최소 기준에 못 미칩니다"),
])
def test_each_missing_input_explains_itself(service, dong, industry, fragment):
    result = service.lookup(dong, industry)
    assert isinstance(result, TradeAreaUnavailable)
    assert fragment in result.reason
    assert result.required_actions


def test_signals_report_observed_values_not_shrunk_ones(service):
    signals = {s.name: s for s in service.signals(service.lookup("11680600", "CS100010"))}
    # 관측 폐업률 10% 가 설명문에 그대로 적혀야 한다. 축소는 등급에만 쓴다.
    assert "10.0%" in signals["turnover"].explanation
    # 매출은 서울 중앙값의 50%. 관측 비율이 그대로 나온다.
    assert "50%" in signals["sales"].explanation


def test_closure_is_compared_by_percentile_not_by_a_ratio_to_zero(tmp_path):
    """서울 100개 업종 중 91개는 폐업률의 행정동 중앙값이 0이다.

    0으로 나눌 수 없으므로 비율 방식에서는 이 축이 조용히 꺼졌고, 하필 안정성
    우선순위가 가장 무겁게 두는 축이었다. 백분위는 0-과잉 분포에서도 정의된다.
    """
    payload = json.loads(json.dumps(PROFILE))
    payload["benchmarks"]["CS100010"]["close_rate_median"] = 0
    payload["dongs"]["11680601"] = {
        "district": "강남구", "admin_dong": "옆동", "trade_area_count": 1, "footfall_monthly": 1_000_000,
        "industries": {"CS100010": {**payload["dongs"]["11680600"]["industries"]["CS100010"], "close_rate": 0.0}},
    }
    path = tmp_path / "zero-median.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    service = TradeAreaService(path)

    signals = {s.name: s for s in service.signals(service.lookup("11680600", "CS100010"))}
    assert signals["turnover"].score_band != "UNKNOWN", "중앙값이 0이어도 폐업률 축은 판정되어야 한다"
    # 폐업률 0인 동은 10%인 동보다 낮은 백분위에 놓인다.
    assert service.close_rate_percentile("CS100010", 0.0) < service.close_rate_percentile("CS100010", 10.0)


def test_percentile_uses_midrank_for_ties(service):
    """폐업률 0인 행정동이 과반인 업종에서 0의 순위를 0%로도 61%로도 부르지 않는다."""
    service._close_rates["TIE"] = [0.0, 0.0, 0.0, 0.0, 8.0]
    assert service.close_rate_percentile("TIE", 0.0) == pytest.approx(0.4)
    assert service.close_rate_percentile("TIE", 8.0) == pytest.approx(0.9)


def test_percentile_without_a_distribution_is_not_a_judgement(service):
    assert service.close_rate_percentile("CS999999", 3.0) is None
    assert service.close_rate_percentile("CS100010", None) is None


def test_closure_wording_never_claims_an_individual_probability(service):
    """부록 A 불변조건 2 — 폐업률은 상권 집계이지 이 매물의 폐업 확률이 아니다."""
    signals = {s.name: s for s in service.signals(service.lookup("11680600", "CS100010"))}
    assert "개별 점포의 폐업 확률이 아닙니다" in signals["turnover"].explanation


def test_risk_grade_counts_only_judged_signals(service):
    from app.models import ContextSignal

    def signal(name, band):
        return ContextSignal(name=name, label=name, score_band=band,
                             direction="NEUTRAL", explanation="")

    unknown_only = [signal("a", "UNKNOWN"), signal("b", "UNKNOWN")]
    assert TradeAreaService.risk_grade(unknown_only) == "MEDIUM"
    assert TradeAreaService.judged_count(unknown_only) == 0

    risky = [signal("a", "CAUTION"), signal("b", "CAUTION"), signal("c", "UNKNOWN")]
    assert TradeAreaService.risk_grade(risky) == "HIGH"

    safe = [signal("a", "FAVORABLE"), signal("b", "FAVORABLE")]
    assert TradeAreaService.risk_grade(safe) == "LOW"


def test_provenance_carries_the_sample_and_the_spatial_unit(service):
    found = service.lookup("11680600", "CS100010")
    provenance = service.provenance(industry_code="CS100010", sample_n=found["store_count"],
                                    trade_area_count=found["trade_area_count"])
    assert provenance.sample_n == 30
    assert provenance.spatial_unit == "행정동 내 상권 집계"
    assert provenance.source_as_of == "2026년 1분기"
    assert any("상권은 2개" in limitation for limitation in provenance.limitations)


def test_a_grade_b_result_cannot_carry_survival_output(service):
    """모델 계약이 B등급에 개별 생존 수치가 섞이는 것을 막는지 확인한다."""
    found = service.lookup("11680600", "CS100010")
    signals = service.signals(found)
    with pytest.raises(ValueError):
        AnalysisResult(
            analysis_id="00000000-0000-0000-0000-000000000000", status="completed",
            evidence_grade="B", display_label="상권 위험 진단", context_risk_grade="HIGH",
            confidence="MEDIUM", sample_n=30, context_signals=signals,
            survival_grade="C", probability_lower=10.0, probability_upper=20.0,
            probability_unit="PERCENT_0_100", horizon_months=18,
            provenance=service.provenance(industry_code="CS100010", sample_n=30, trade_area_count=2),
            limitations=[],
        )


def test_industry_mapping_never_guesses_a_lookalike():
    """'스터디카페'를 '커피-음료'로 붙이면 전혀 다른 업종의 숫자가 근거가 된다."""
    assert resolve("카페") == "CS100010"
    assert resolve("스터디카페") is None
    assert resolve("무인카페") is None
    assert resolve("") is None
    assert resolve("존재하지않는업종") is None


def test_industry_mapping_tolerates_spacing_and_case():
    assert resolve(" 카 페 ") == "CS100010"
    assert resolve("Cafe") == "CS100010"
    assert resolve("cs100010") == "CS100010"


def test_grade_b_provenance_still_discloses_the_listing_assumptions(service):
    """등급이 B로 오르면 provenance 가 상권 출처로 통째로 바뀐다.

    같은 카드에는 권리금 같은 가정값 임대 조건이 함께 뜨므로, 매물 쪽 한계가 사라지면
    가정값이 실측 출처만 달고 나가게 된다 (부록 A 불변조건 3).
    """
    provenance = service.provenance(
        industry_code="CS100010", sample_n=30, trade_area_count=2,
        extra_limitations=["권리금·전용면적은 실측 출처가 없어 가정한 값입니다."],
    )
    assert any("권리금" in limitation for limitation in provenance.limitations)
    assert any("상권 경계" in limitation for limitation in provenance.limitations)
