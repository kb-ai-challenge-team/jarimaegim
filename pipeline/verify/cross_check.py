"""Stage 2 - a self-consistency gate over the aggregated rent distribution.

This was designed as an independent cross-check: crawled rents compared against
public data. The crawl was dropped, and the rents now come from the same Seoul
Metro underground arcade dataset (OA-12927, as of 2025-12-31) that supplies the
baseline. Baseline and subject are therefore the same source, and the comparison
is no longer independent.

What it still catches is a bug in the aggregation path - columns read in the
wrong order, a station-to-district mapping that slipped, a district dropped
entirely. Any of those pushes a district's rent per square metre far away from
the source-wide median. It does not certify that the rents are accurate, and it
cannot, because there is nothing here to check them against.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASELINE_KRW_PER_M2 = 98_770
# Widened from 0.5-3.0 when coverage grew from five districts to nineteen. The baseline is
# the source-wide median, so by construction half the districts sit below 1.0x; a 0.5x floor
# rejected the genuinely cheap tail (중랑 0.43x, 성북 0.47x) even though the nineteen ratios
# run smoothly from 0.43 to 2.15 with no outlier gap. This window still catches the failure
# this gate exists for - a 10x or 100x unit slip between 원 and 만원.
RATIO_MIN = 0.2
RATIO_MAX = 5.0

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION_PATH = ROOT / "data" / "rent-distribution.seoul.json"
REPORT_PATH = ROOT / "data" / "rent-distribution.verification.md"


def evaluate_district(name: str, payload: dict) -> dict:
    """Compare a district's representative rent per square metre to the baseline."""
    area_p50 = payload["area"]["p50"]
    bands = payload["bands"]
    if not bands:
        raise ValueError(f"{name} has no area bands")
    largest = max(bands.values(), key=lambda band: band["n"])
    rent_p50 = largest["monthly_rent_krw"]["p50"]
    per_m2 = rent_p50 / area_p50
    ratio = per_m2 / BASELINE_KRW_PER_M2
    return {
        "district": name, "area_p50": area_p50, "rent_p50": rent_p50,
        "per_m2": per_m2, "ratio": ratio, "band_label": largest["label"], "n": largest["n"],
        "ok": RATIO_MIN <= ratio <= RATIO_MAX,
    }


def summarize(districts: dict) -> dict:
    if not districts:
        raise ValueError("distribution has no districts to verify")
    results = [evaluate_district(name, payload) for name, payload in districts.items()]
    return {"ok": all(result["ok"] for result in results), "results": results}


def render_report(report: dict, merges: list) -> str:
    lines = [
        "# 시세 분포 자기일관성 리포트", "",
        "> **이 리포트는 독립적인 교차검증이 아니다.** 임대료 표본과 기준선이 같은 출처",
        "> (서울교통공사 지하상가 임대정보 OA-12927)에서 나오므로, 비교 대상은 자기 자신이다.",
        "> 여기서 잡히는 것은 집계 경로의 버그뿐이다 — 컬럼을 뒤바꿔 읽거나, 역-자치구 매핑이",
        "> 어긋나거나, 특정 구가 통째로 빠지는 경우. 시세의 정확성은 보증하지 않으며,",
        "> 대조할 독립 출처가 없으므로 보증할 수도 없다.", "",
        f"기준선: 출처 전체의 ㎡당 월임대료 중앙값 {BASELINE_KRW_PER_M2:,}원 (기준일 2025-12-31)",
        f"허용 범위: {RATIO_MIN}× ~ {RATIO_MAX}×", "",
        "기준선이 출처 전체의 중앙값이므로 정의상 절반의 자치구는 1.0× 아래에 온다.",
        "범위는 원↔만원 같은 단위 오류(10×·100×)를 잡는 폭으로 잡았고, 실제 자치구 간",
        "시세 차이는 통과시킨다.", "",
        "| 자치구 | 대표 구간 | 표본 | 면적 P50 | 월세 P50 | ㎡당 | 배수 | 판정 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in report["results"]:
        lines.append(
            f"| {result['district']} | {result['band_label']} | {result['n']} | "
            f"{result['area_p50']:.1f}㎡ | {result['rent_p50']:,.0f}원 | {result['per_m2']:,.0f}원 | "
            f"{result['ratio']:.2f}× | {'통과' if result['ok'] else '실패'} |"
        )
    lines += ["", f"**전체 판정: {'통과' if report['ok'] else '실패'}**", ""]
    if merges:
        lines += ["## 병합된 면적구간", "", "표본 5건 미만이라 상위 구간으로 접은 구간이다.", ""]
        lines += [f"- {entry['district']}: {entry['from']} → {entry['into']} ({entry['moved']}건)" for entry in merges]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    payload = json.loads(DISTRIBUTION_PATH.read_text(encoding="utf-8"))
    report = summarize(payload["districts"])
    REPORT_PATH.write_text(render_report(report, payload.get("merges", [])), encoding="utf-8")
    for result in report["results"]:
        mark = "OK  " if result["ok"] else "FAIL"
        print(f"{mark} {result['district']}: {result['per_m2']:,.0f}원/㎡ ({result['ratio']:.2f}×)")
    print(f"\n리포트: {REPORT_PATH}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
