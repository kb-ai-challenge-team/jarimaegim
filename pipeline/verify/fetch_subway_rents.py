"""Download the Seoul Metro underground arcade rent dataset (OA-12927) and report
the median monthly rent per square metre.

This is file data rather than an Open API, so it is fetched with a POST form
request. The payload is EUC-KR encoded. Run this only when the baseline in
cross_check.BASELINE_KRW_PER_M2 needs to be re-derived.
"""
from __future__ import annotations

import csv
import io
import statistics
from pathlib import Path

import httpx

URL = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do"
FORM = {"infId": "OA-12927", "seq": "14", "infSeq": "1"}
CACHE = Path(__file__).resolve().parents[1] / "raw" / "subway-rents.csv"


def download() -> str:
    response = httpx.post(URL, data=FORM, timeout=60.0)
    response.raise_for_status()
    text = response.content.decode("euc-kr", errors="replace")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(text, encoding="utf-8")
    return text


def median_per_m2(text: str) -> float:
    values = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            area = float(row["면적(제곱미터)"])
            rent = float(row["월임대료"])
        except (KeyError, TypeError, ValueError):
            continue
        if area > 0 and rent > 0:
            values.append(rent / area)
    if not values:
        raise SystemExit("no rows had both a positive area and a positive rent; check the column names")
    return statistics.median(values)


if __name__ == "__main__":
    text = CACHE.read_text(encoding="utf-8") if CACHE.exists() else download()
    print(f"median monthly rent per square metre: {median_per_m2(text):,.0f} won")
