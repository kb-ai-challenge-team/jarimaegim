"""공공 API 3종에서 원시 레코드를 긁어 온다. 해석은 normalize.py가 한다.

수집 실패는 예외로 올리지 않고 (records, ok) 튜플의 ok=False로 알린다. prune이
'이 provider를 정말 다 봤는가'를 알아야 하기 때문이다 — 설계 §4.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

import httpx

TIMEOUT = httpx.Timeout(20.0, connect=5.0)
KB_FIN_CO_NO = "0010927"
KB_CATEGORIES = (
    ("BUSINESS_LOAN", "개인사업자대출", "busiLoanProductsSearch", "LOAN",
     "https://finlife.fss.or.kr/finlife/ldng/indvlBusi/list.do?menuNo=700072"),
    ("CREDIT_LOAN", "개인신용대출", "creditLoanProductsSearch", "LOAN",
     "https://finlife.fss.or.kr/finlife/ldng/indvCrdt/list.do?menuNo=700009"),
    ("MORTGAGE_LOAN", "주택담보대출", "mortgageLoanProductsSearch", "LOAN",
     "https://finlife.fss.or.kr/finlife/ldng/houseMortgage/list.do?menuNo=700007"),
    ("RENT_LOAN", "전세자금대출", "rentHouseLoanProductsSearch", "LOAN",
     "https://finlife.fss.or.kr/finlife/ldng/rentHouse/list.do?menuNo=700008"),
    ("DEPOSIT", "정기예금", "depositProductsSearch", "SAVING",
     "https://finlife.fss.or.kr/finlife/svings/fxdDpst/list.do?menuNo=700002"),
    ("SAVING", "적금", "savingProductsSearch", "SAVING",
     "https://finlife.fss.or.kr/finlife/svings/instsav/list.do?menuNo=700003"),
)


def _resolved(template: str, key: str) -> str:
    return template.replace("{api_key}", quote(key, safe="")) if "{api_key}" in template else template


def _paged(url: str, page: int) -> str:
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}page={page}"


def fetch_bizinfo(client: httpx.Client, template: str, key: str) -> tuple[list[dict[str, str]], bool]:
    if not template or not key or not template.startswith("https://"):
        return ([], False)
    try:
        response = client.get(_resolved(template, key), headers={"X-Api-Key": key}, timeout=TIMEOUT)
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
    except (httpx.HTTPError, ElementTree.ParseError):
        return ([], False)
    records = [{child.tag: (child.text or "").strip() for child in item}
               for item in root.findall(".//body/items/item")]
    return (records, True)


def fetch_kstartup(client: httpx.Client, template: str, key: str, *,
                   max_pages: int = 20) -> tuple[list[dict[str, Any]], bool]:
    """진행 중인 공고만 모은다. 종료된 공고를 인덱싱할 이유가 없다."""
    if not template or not key or not template.startswith("https://"):
        return ([], False)
    url = _resolved(template, key)
    records: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        try:
            response = client.get(_paged(url, page), headers={"Accept": "application/json"}, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return (records, False)
        batch = [item for item in (payload.get("data") or []) if isinstance(item, dict)]
        if not batch:
            break
        records.extend(item for item in batch if str(item.get("rcrt_prgs_yn") or "").upper() == "Y")
        if len(batch) < int(payload.get("perPage") or len(batch)):
            break
    return (records, True)


def fetch_kb_products(client: httpx.Client, base_url: str, key: str, *,
                      max_pages: int = 5) -> tuple[list[tuple[dict, dict, str, str, str, str]], bool]:
    """(base, option, category, label, kind_of_rate, source_url) 튜플을 낸다."""
    base = (base_url or "").rstrip("/")
    if not base or not key or not base.startswith("https://"):
        return ([], False)
    out: list[tuple[dict, dict, str, str, str, str]] = []
    ok = True
    for category, label, endpoint, kind_of_rate, source_url in KB_CATEGORIES:
        url = f"{base}/{endpoint}.json?auth={quote(key, safe='')}&topFinGrpNo=020000"
        bases: list[dict] = []
        options: list[dict] = []
        for page in range(1, max_pages + 1):
            try:
                response = client.get(f"{url}&pageNo={page}", headers={"Accept": "application/json"}, timeout=TIMEOUT)
                response.raise_for_status()
                result = (response.json() or {}).get("result") or {}
            except (httpx.HTTPError, ValueError):
                ok = False
                break
            if str(result.get("err_cd") or "000") != "000":
                break
            bases.extend(item for item in (result.get("baseList") or []) if isinstance(item, dict))
            options.extend(item for item in (result.get("optionList") or []) if isinstance(item, dict))
            if page >= int(result.get("max_page_no") or page):
                break
        rates: dict[str, dict] = {}
        for option in options:
            code = str(option.get("fin_prdt_cd") or "")
            if code and code not in rates:
                rates[code] = option
        for record in bases:
            if str(record.get("fin_co_no") or "") != KB_FIN_CO_NO:
                continue
            out.append((record, rates.get(str(record.get("fin_prdt_cd") or ""), {}),
                        category, label, kind_of_rate, source_url))
    return (out, ok)
