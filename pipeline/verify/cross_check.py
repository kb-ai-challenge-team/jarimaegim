"""Stage 2 - gate the crawled rent distribution against a public-data baseline.

The baseline is the median monthly rent per square metre from the Seoul Metro
underground shopping arcade dataset (OA-12927, as of 2025-12-31). Underground
arcades and ground-floor storefronts sit at genuinely different price levels,
so the tolerance is wide. This gate catches order-of-magnitude mistakes; it
does not certify that the rents are accurate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASELINE_KRW_PER_M2 = 98_770
RATIO_MIN = 0.5
RATIO_MAX = 3.0

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
        "# 시세 분포 교차검증 리포트", "",
        f"기준선: 서울교통공사 지하상가 임대정보 ㎡당 월임대료 중앙값 {BASELINE_KRW_PER_M2:,}원 (기준일 2025-12-31)",
        f"허용 범위: {RATIO_MIN}× ~ {RATIO_MAX}×", "",
        "지하상가와 지상 1층 상가는 시세대가 다르므로 범위를 넓게 잡았다.",
        "이 게이트는 자릿수 오류를 잡는 안전망이며 시세의 정확성을 보증하지 않는다.", "",
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
