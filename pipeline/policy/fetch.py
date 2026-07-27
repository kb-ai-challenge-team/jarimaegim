"""공공 API 3종에서 원시 레코드를 긁어 온다. 해석은 normalize.py가 한다.

수집 실패는 예외로 올리지 않고 (records, ok) 튜플의 ok=False로 알린다. prune이
'이 provider를 정말 다 봤는가'를 알아야 하기 때문이다 — 설계 §4.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

TIMEOUT = httpx.Timeout(20.0, connect=5.0)
PAGE_SIZE = 100
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


def _with_params(url: str, **overrides: Any) -> str:
    """기존 쿼리 파라미터를 덮어쓴다.

    두 원천의 URL 템플릿에는 이미 page/pageNo가 들어 있다. 뒤에 덧붙이면 서버가 첫
    값을 쓰므로 같은 페이지를 반복해서 받게 된다(실제로 그렇게 겪었다).
    """
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.update({key: str(value) for key, value in overrides.items()})
    return urlunsplit(parts._replace(query=urlencode(params)))


def fetch_bizinfo(client: httpx.Client, template: str, key: str, *,
                  max_pages: int = 20) -> tuple[list[dict[str, str]], bool]:
    if not template or not key or not template.startswith("https://"):
        return ([], False)
    url = _resolved(template, key)
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        try:
            response = client.get(_with_params(url, pageNo=page, numOfRows=PAGE_SIZE),
                                  headers={"X-Api-Key": key}, timeout=TIMEOUT)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except (httpx.HTTPError, ElementTree.ParseError):
            return (records, False)
        batch = [{child.tag: (child.text or "").strip() for child in item}
                 for item in root.findall(".//body/items/item")]
        fresh = [item for item in batch if item.get("pblancId") not in seen]
        if not fresh:
            break
        seen.update(item.get("pblancId", "") for item in fresh)
        records.extend(fresh)
        if len(batch) < PAGE_SIZE:
            break
    return (records, True)


def fetch_kstartup(client: httpx.Client, template: str, key: str, *,
                   max_pages: int = 30) -> tuple[list[dict[str, Any]], bool]:
    """진행 중인 공고만 모은다. 종료된 공고를 인덱싱할 이유가 없다."""
    if not template or not key or not template.startswith("https://"):
        return ([], False)
    url = _resolved(template, key)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        try:
            response = client.get(_with_params(url, page=page, perPage=PAGE_SIZE),
                                  headers={"Accept": "application/json"}, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return (records, False)
        batch = [item for item in (payload.get("data") or []) if isinstance(item, dict)]
        # 페이지네이션이 먹히지 않으면 같은 레코드가 계속 돌아온다. 조용히 도는 대신 멈춘다.
        fresh = [item for item in batch if str(item.get("pbanc_sn") or "") not in seen]
        if not fresh:
            break
        seen.update(str(item.get("pbanc_sn") or "") for item in fresh)
        records.extend(item for item in fresh if str(item.get("rcrt_prgs_yn") or "").upper() == "Y")
        if len(batch) < PAGE_SIZE:
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
