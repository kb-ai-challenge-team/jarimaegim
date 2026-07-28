"""상권 프로파일을 입지팀 계약으로 옮기는 어댑터.

이 어댑터가 지키는 것은 하나다 — **같은 숫자를 두 번 판정하지 않는다.** `TradeAreaService` 는
서울 중앙값 대비 비교와 표본 보정(적은 표본을 중앙값 쪽으로 당기는 것)을 이미 끝낸 판정을
내놓는다. 어댑터가 원시 비율을 다시 받아 자기 기준으로 등급을 매기면 그 보정이 사라지고,
점포 6곳짜리 행정동이 다시 1순위를 차지한다(제안서 06장 JUDGEMENT 02). 그래서 어댑터는
판정을 **그대로 옮기고**, 옮길 수 없는 축은 옮길 수 없다고 말한다.

달성 가능성은 옮기지 않는다. 그 축은 "목표매출을 상권 매출 분포에 대입한 백분위"이고 상위
10%를 넘으면 **후보를 탈락시킨다.** 이 데이터셋에서 그 백분위를 어떻게 정의할지가 정해지기
전에 붙이면, 정의되지 않은 기준으로 후보가 사라진다.
"""
from app.agents.trade_area_adapter import TradeAreaProfiles
from app.models import ContextSignal


class FakeService:
    """TradeAreaService 의 어댑터가 실제로 쓰는 표면만 흉내 낸다."""

    available = True

    def __init__(self, rows=None, signals=None):
        self.rows = rows if rows is not None else {("1168051000", "CS100010"): {"admin_dong": "역삼1동", "store_count": 42}}
        self._signals = signals
        self.asked = []

    def lookup(self, dong_code, industry_code):
        self.asked.append((dong_code, industry_code))
        found = self.rows.get((dong_code, industry_code))
        return found if found is not None else Unavailable("이 행정동에는 집계가 없습니다.")

    def signals(self, profile):
        return self._signals if self._signals is not None else [
            ContextSignal(name="demand", label="점포당 유동인구", score_band="FAVORABLE",
                          direction="POSITIVE", explanation="서울 동종 중앙값의 140% 수준입니다."),
            ContextSignal(name="competition", label="동종 점포 밀집도", score_band="CAUTION",
                          direction="RISK", explanation="서울 동종 중앙값의 180%입니다."),
            ContextSignal(name="turnover", label="동종 폐업률", score_band="NEUTRAL",
                          direction="NEUTRAL", explanation="상위 40% 수준입니다."),
            ContextSignal(name="sales", label="점포당 추정매출", score_band="FAVORABLE",
                          direction="POSITIVE", explanation="중앙값의 120%입니다."),
        ]

    @property
    def quarter(self):
        return "20261"


class Unavailable:
    """trade_area.TradeAreaUnavailable 자리. 어댑터는 이것을 '판정 없음'으로 읽어야 한다."""

    def __init__(self, reason):
        self.reason = reason
        self.required_actions = []


def adapter(service=None, **kwargs):
    return TradeAreaProfiles(service or FakeService(), unavailable_type=Unavailable, **kwargs)


def test_the_adapter_is_available_only_when_the_source_is():
    class Off(FakeService):
        available = False
    assert adapter().available is True
    assert adapter(Off()).available is False


def test_it_looks_the_profile_up_by_dong_code_and_industry_code():
    service = FakeService()
    adapter(service, resolve=lambda name: "CS100010").profile("1168051000", "카페")
    assert service.asked == [("1168051000", "CS100010")]


def test_an_unmapped_industry_never_reaches_the_source():
    # 업종 코드로 정규화되지 않으면 조회하지 않는다. 비슷한 업종을 대신 넣지 않는다.
    service = FakeService()
    assert adapter(service, resolve=lambda name: None).profile("1168051000", "스터디카페") is None
    assert service.asked == []


def test_a_dong_without_an_aggregate_yields_no_profile_rather_than_an_error():
    service = FakeService(rows={})
    assert adapter(service, resolve=lambda name: "CS100010").profile("1168051000", "카페") is None


def test_the_source_verdict_is_carried_through_verbatim():
    # 여기서 등급을 다시 매기지 않는다. 표본 보정이 끝난 판정이 그대로 와야 한다.
    profile = adapter(resolve=lambda name: "CS100010").profile("1168051000", "카페")
    assert profile["signals"]["demand"]["score_band"] == "FAVORABLE"
    assert profile["signals"]["competition"]["score_band"] == "CAUTION"
    assert profile["signals"]["competition"]["direction"] == "RISK"
    assert "중앙값의 180%" in profile["signals"]["competition"]["explanation"]


def test_the_profile_carries_the_quarter_and_the_sample_size():
    profile = adapter(resolve=lambda name: "CS100010").profile("1168051000", "카페")
    assert profile["quarter"] == "20261"
    assert profile["sample_n"] == 42


def test_only_the_two_axes_that_map_one_to_one_are_declared_judgeable():
    assert adapter().judgeable == ("demand", "competition")


def test_viability_declares_why_it_is_not_judged_rather_than_going_quiet():
    reason = adapter().reason_for("viability")
    assert reason and "백분위" in reason


def test_an_axis_that_is_judgeable_has_no_pending_reason():
    assert adapter().reason_for("demand") is None
