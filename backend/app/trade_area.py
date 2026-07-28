"""서울시 우리마을가게 상권분석서비스 프로파일.

`data/trade-area.seoul.json` 을 시작 시 한 번 읽어 (행정동, 업종) 조합의 집계값을 준다.
이 파일이 없거나 조합이 없으면 **판정하지 않는다**. 비어 있는 축을 중립값으로 채워 넣으면
근거가 없는데도 후보가 통과하거나 탈락하므로, 없는 것은 없다고 말한다.

부록 A 불변조건 2 — 여기서 나오는 것은 전부 상권×업종 집계이므로 근거 등급 B 다.
개별 점포의 생존등급이나 생존·폐업 확률은 이 경로에서 절대 만들 수 없다. 폐업률은
'상권 안 동종 점포 중 이번 분기에 폐업한 비율'이지 '이 매물이 폐업할 확률'이 아니다.
"""

from __future__ import annotations

import bisect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .industry import display_name
from .models import ContextSignal, Provenance
from .ranking import SHRINKAGE_PRIOR, shrink_ratio

DEFAULT_TRADE_AREA_PATH = Path(__file__).resolve().parents[2] / "data" / "trade-area.seoul.json"

# 서울 중앙값 대비 어느 비율부터 '높다/낮다'로 부를지. 데이터가 아니라 선언한 분류 기준이다.
# ±20% 는 분기 갱신에서 흔히 생기는 변동을 넘어서는 폭으로 잡았다.
HIGH_RATIO = 1.2
LOW_RATIO = 0.8

# 위험 등급 산정. 판정된 신호만 센다 — 판정하지 못한 축은 0표이지 안전표가 아니다.
RISK_HIGH_SCORE = 2
RISK_LOW_SCORE = -2

# 폐업률은 백분위로 비교한다. 사분위 바깥이면 양호/주의로 부른다.
LOW_PERCENTILE = 0.25
HIGH_PERCENTILE = 0.75


@dataclass(frozen=True)
class TradeAreaUnavailable:
    """판정하지 못한 이유. 화면과 provenance 가 그대로 인용한다."""

    reason: str
    required_actions: list[str]


def _ratio(value: float | None, benchmark: float | None) -> float | None:
    if value is None or not benchmark:
        return None
    return value / benchmark


def _band(ratio: float | None, sample_n: int | None, *, high_is_good: bool) -> tuple[str, str]:
    """비율을 밴드로. high_is_good 이 False 면 높을수록 위험 쪽으로 읽는다.

    밴드는 관측 비율이 아니라 표본으로 축소한 비율에 매긴다. 점포 6곳에서 나온 617% 를
    그대로 '양호'라고 부르면, 표본이 얇다는 사실이 등급에서 사라진다. 설명문에 적히는
    숫자는 관측값 그대로이고 표본 크기도 함께 나가므로, 사용자는 둘 다 볼 수 있다.
    """
    adjusted = shrink_ratio(ratio, sample_n)
    if adjusted is None:
        return "UNKNOWN", "UNKNOWN"
    if adjusted >= HIGH_RATIO:
        return ("FAVORABLE", "POSITIVE") if high_is_good else ("CAUTION", "RISK")
    if adjusted <= LOW_RATIO:
        return ("CAUTION", "RISK") if high_is_good else ("FAVORABLE", "POSITIVE")
    return "NEUTRAL", "NEUTRAL"


def _pct(ratio: float) -> str:
    return f"{round(ratio * 100)}%"


def _rank_phrase(percentile: float) -> str:
    """백분위를 사람이 읽는 순위 문구로.

    '낮은 쪽에서 83% 지점' 같은 표현은 좋은 뜻인지 나쁜 뜻인지 한 번에 읽히지 않는다.
    폐업률은 낮을수록 좋으므로, 중앙을 기준으로 어느 쪽인지를 먼저 말하고 순위를 붙인다.
    """
    if percentile <= 0.5:
        return f"폐업률이 낮은 편(하위 {round(percentile * 100)}%)"
    return f"폐업률이 높은 편(상위 {round((1 - percentile) * 100)}%)"


def _percentile_band(percentile: float | None, sample_n: int | None) -> tuple[str, str]:
    """백분위를 밴드로. 낮을수록(폐업이 드물수록) 양호하다.

    비율과 마찬가지로 표본으로 축소한다. 기준점은 1.0 이 아니라 0.5(중앙)이므로
    점포가 적은 행정동의 극단 순위는 중앙 쪽으로 당겨진다.
    """
    if percentile is None or not sample_n or sample_n <= 0:
        return "UNKNOWN", "UNKNOWN"
    weight = sample_n / (sample_n + SHRINKAGE_PRIOR)
    adjusted = 0.5 + (percentile - 0.5) * weight
    if adjusted <= LOW_PERCENTILE:
        return "FAVORABLE", "POSITIVE"
    if adjusted >= HIGH_PERCENTILE:
        return "CAUTION", "RISK"
    return "NEUTRAL", "NEUTRAL"


class TradeAreaService:
    """읽기 전용 프로파일 조회. 계산은 전부 여기(코드)에서 하고 AI는 관여하지 않는다."""

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_TRADE_AREA_PATH
        self._payload: dict[str, Any] = {}
        self._dongs: dict[str, Any] = {}
        self._benchmarks: dict[str, Any] = {}
        if self.path.exists():
            try:
                self._payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                # 참조 데이터다. 읽지 못하면 축만 꺼지고 서비스는 계속 떠 있어야 한다.
                print(f"[trade-area] 프로파일을 읽지 못해 상권 축을 끕니다: {exc}")
                self._payload = {}
            self._dongs = self._payload.get("dongs", {})
            self._benchmarks = self._payload.get("benchmarks", {})
        self._close_rates = self._index_close_rates()

    def _index_close_rates(self) -> dict[str, list[float]]:
        """업종별 폐업률 분포(정렬된 행정동 값들).

        폐업률은 중앙값 대비 비율로 비교할 수 없다. 서울 100개 업종 중 91개에서
        분기 폐업률의 행정동 중앙값이 정확히 0이기 때문이다 — 한 분기에 아무 곳도 닫지
        않은 행정동이 절반을 넘는 0-과잉 분포다. 0으로 나눌 수 없으니 비율 방식에서는
        이 축이 조용히 꺼졌고, 하필 안정성 우선순위가 가장 무겁게(0.40) 두는 축이었다.
        그래서 이 축만 백분위 순위로 비교한다. 0-과잉이어도 순위는 언제나 정의된다.

        분포는 파일에 따로 싣지 않고 로드 시점에 `dongs` 에서 만든다. 같은 값을 두 곳에
        두면 한쪽만 갱신될 수 있다.
        """
        collected: dict[str, list[float]] = {}
        for entry in self._dongs.values():
            for code, industry in entry.get("industries", {}).items():
                rate = industry.get("close_rate")
                if rate is not None:
                    collected.setdefault(code, []).append(rate)
        for rates in collected.values():
            rates.sort()
        return collected

    def close_rate_percentile(self, industry_code: str, rate: float | None) -> float | None:
        """서울 동종 행정동 중 이 폐업률의 백분위(0=가장 낮음, 1=가장 높음).

        동점은 중간순위(midrank)로 센다. 폐업률 0인 행정동이 61%인 업종에서 0을
        '하위 0%'로 부르면 실제보다 좋아 보이고, '하위 61%'로 부르면 나빠 보인다.
        """
        rates = self._close_rates.get(industry_code)
        if rate is None or not rates:
            return None
        below = bisect.bisect_left(rates, rate)
        equal = bisect.bisect_right(rates, rate) - below
        return (below + equal / 2) / len(rates)

    @property
    def available(self) -> bool:
        return bool(self._dongs)

    @property
    def quarter(self) -> str | None:
        return self._payload.get("quarter")

    @property
    def dong_count(self) -> int:
        return len(self._dongs)

    def benchmark(self, industry_code: str | None) -> dict[str, Any] | None:
        """업종별 서울 기준선(행정동 값들의 중앙값). 순위 계산이 비교 대상으로 쓴다."""
        return self._benchmarks.get(industry_code) if industry_code else None

    def provenance(self, *, industry_code: str | None, sample_n: int | None, trade_area_count: int | None) -> Provenance:
        return Provenance(
            source_name=self._payload.get("source_name", "서울시 우리마을가게 상권분석서비스"),
            official_url="https://data.seoul.go.kr/dataList/datasetList.do",
            source_as_of=self._quarter_label(),
            collected_at=self._payload.get("generated_at"),
            industry_scope=display_name(industry_code) if industry_code else "업종 미지정",
            spatial_unit=self._payload.get("spatial_unit", "행정동 내 상권 집계"),
            sample_n=sample_n,
            confidence="MEDIUM",
            limitations=[
                *self._payload.get("limitations", []),
                f"이 행정동에서 집계에 포함된 상권은 {trade_area_count}개입니다." if trade_area_count else "집계 상권 수를 확인하지 못했습니다.",
            ],
        )

    def _quarter_label(self) -> str | None:
        quarter = self._payload.get("quarter")
        if not quarter or len(quarter) != 5:
            return quarter
        return f"{quarter[:4]}년 {quarter[4]}분기"

    def lookup(self, dong_code: str | None, industry_code: str | None) -> dict[str, Any] | TradeAreaUnavailable:
        """(행정동, 업종) 집계. 없으면 왜 없는지를 돌려준다."""
        if not self.available:
            return TradeAreaUnavailable(
                reason="서울시 상권분석 프로파일이 준비되지 않았습니다.",
                required_actions=["`npm run pipeline:trade-area` 로 상권 데이터를 생성해 주세요."],
            )
        if not industry_code:
            return TradeAreaUnavailable(
                reason="입력한 업종이 서울시 상권분석서비스의 업종 분류에 연결되지 않았습니다.",
                required_actions=["상권 통계가 제공되는 업종명으로 다시 입력해 주세요.", "예: 카페, 한식, 미용실, 편의점, 학원"],
            )
        if not dong_code:
            return TradeAreaUnavailable(
                reason="이 후보의 행정동을 확인하지 못해 상권 통계를 붙이지 못했습니다.",
                required_actions=["다른 후보를 선택해 주세요."],
            )
        dong = self._dongs.get(dong_code)
        if not dong:
            return TradeAreaUnavailable(
                reason="이 행정동에는 서울시 상권분석서비스가 집계한 상권이 없습니다.",
                required_actions=["인접한 다른 행정동의 후보를 확인해 주세요."],
            )
        industry = dong.get("industries", {}).get(industry_code)
        if not industry:
            return TradeAreaUnavailable(
                reason=f"이 행정동에는 {display_name(industry_code)} 점포가 집계 최소 기준에 못 미칩니다.",
                required_actions=["점포 수가 충분한 다른 행정동의 후보를 확인해 주세요."],
            )
        return {
            "dong_code": dong_code, "district": dong.get("district"), "admin_dong": dong.get("admin_dong"),
            "trade_area_count": dong.get("trade_area_count"), "footfall_monthly": dong.get("footfall_monthly"),
            "industry_code": industry_code, "industry_name": display_name(industry_code),
            **industry,
        }

    def signals(self, profile: dict[str, Any]) -> list[ContextSignal]:
        """집계값을 서울 중앙값과 견준 맥락 신호. 전부 코드가 계산한 비교값이다."""
        benchmark = self._benchmarks.get(profile["industry_code"], {})
        signals: list[ContextSignal] = []

        footfall = profile.get("footfall_monthly")
        stores = profile.get("store_count") or 0
        footfall_per_store = (footfall / stores) if footfall and stores else None
        ratio = _ratio(footfall_per_store, benchmark.get("footfall_per_store_median"))
        score_band, direction = _band(ratio, stores, high_is_good=True)
        signals.append(ContextSignal(
            name="demand", label="점포당 유동인구",
            score_band=score_band, direction=direction,
            explanation=(
                f"{profile['admin_dong']} 상권의 분기 유동인구는 {footfall:,}명이고 {profile['industry_name']} 점포는 {stores:,}곳입니다. "
                f"점포당 유동인구는 서울 동종 중앙값의 {_pct(ratio)} 수준입니다."
                if ratio is not None else "유동인구 또는 점포 수를 확인하지 못해 판정하지 않았습니다."
            ),
        ))

        ratio = _ratio(stores, benchmark.get("store_count_median"))
        score_band, direction = _band(ratio, stores, high_is_good=False)
        franchise = profile.get("franchise_store_count") or 0
        signals.append(ContextSignal(
            name="competition", label="동종 점포 밀집도",
            score_band=score_band, direction=direction,
            explanation=(
                f"{profile['industry_name']} 점포가 {stores:,}곳으로 서울 동종 중앙값의 {_pct(ratio)}입니다. "
                f"이 가운데 프랜차이즈는 {franchise:,}곳입니다."
                if ratio is not None else "비교 기준선이 없어 판정하지 않았습니다."
            ),
        ))

        close_rate = profile.get("close_rate")
        percentile = self.close_rate_percentile(profile["industry_code"], close_rate)
        score_band, direction = _percentile_band(percentile, stores)
        peers = len(self._close_rates.get(profile["industry_code"], []))
        signals.append(ContextSignal(
            name="turnover", label="동종 폐업률",
            score_band=score_band, direction=direction,
            explanation=(
                f"이번 분기 이 상권의 {profile['industry_name']} 폐업률은 {close_rate}%로, "
                f"같은 업종이 있는 서울 행정동 {peers:,}곳 중 {_rank_phrase(percentile)}입니다. "
                f"상권 집계값이며 개별 점포의 폐업 확률이 아닙니다."
                if percentile is not None else "폐업률 비교 분포가 없어 판정하지 않았습니다."
            ),
        ))

        sales = profile.get("sales_per_store_krw")
        ratio = _ratio(sales, benchmark.get("sales_per_store_krw_median"))
        # 매출의 표본은 매출을 확인한 점포 수다. 행정동 전체 점포 수와 다를 수 있다.
        score_band, direction = _band(ratio, profile.get("sales_store_count"), high_is_good=True)
        signals.append(ContextSignal(
            name="sales", label="점포당 추정매출",
            score_band=score_band, direction=direction,
            explanation=(
                f"{profile['industry_name']} 점포당 추정매출이 서울 동종 중앙값의 {_pct(ratio)}입니다. "
                f"매출을 확인한 점포는 {profile.get('sales_store_count', 0):,}곳입니다. 카드매출 기반 추정치입니다."
                if ratio is not None else "이 상권·업종은 추정매출이 제공되지 않아 판정하지 않았습니다."
            ),
        ))
        return signals

    @staticmethod
    def risk_grade(signals: list[ContextSignal]) -> str:
        """판정된 신호만 세어 상권 위험 수준을 낸다.

        주의(CAUTION) 하나에 +1, 양호(FAVORABLE) 하나에 -1. UNKNOWN 은 0표이며
        '안전'으로 세지 않는다 — 설계 스펙 §3.7 공통규칙 1(가동 불가 축을 탈락 근거로
        쓰지 않는다)의 반대 방향 이행이다.
        """
        score = sum(1 if signal.score_band == "CAUTION" else -1 if signal.score_band == "FAVORABLE" else 0 for signal in signals)
        if score >= RISK_HIGH_SCORE:
            return "HIGH"
        if score <= RISK_LOW_SCORE:
            return "LOW"
        return "MEDIUM"

    @staticmethod
    def judged_count(signals: list[ContextSignal]) -> int:
        return sum(1 for signal in signals if signal.score_band != "UNKNOWN")
