"""원시 응답 레코드를 KnowledgeDocument로 바꾼다.

이 모듈은 순수함수만 담는다. 네트워크도 시계도 건드리지 않으므로 오늘 날짜가 필요한
함수는 today를 인자로 받는다. 원천이 모양을 바꾸면 test_normalize.py가 먼저 깨진다.

문서 하나는 두 가지 텍스트를 낳는다. body_text는 임베딩에 들어가고, display는 프론트가
이미 쓰고 있는 Program·KbProduct 모양 그대로다. 둘을 같은 곳에서 만들어야 어긋나지 않는다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

_TAG = re.compile(r"<[^>]+>")
# 블록이 끝나는 자리에만 공백을 넣는다. </b> 같은 인라인 태그까지 공백으로 바꾸면
# '중소기업입니다'가 '중소기업 입니다'가 되어 인용문이 원문과 달라진다.
_BLOCK_BOUNDARY = re.compile(r"</(?:p|div|li|tr|h[1-6]|table|ul|ol)\s*>|<br\s*/?>", re.IGNORECASE)
_ENTITIES = (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "))

# 광역지자체 표기를 짧은 형태로 모은다. 여기에 없는 문자열은 지역으로 인정하지 않는다.
_REGION_ALIASES = {
    "서울": "서울", "서울특별시": "서울", "부산": "부산", "부산광역시": "부산",
    "대구": "대구", "대구광역시": "대구", "인천": "인천", "인천광역시": "인천",
    "광주": "광주", "광주광역시": "광주", "대전": "대전", "대전광역시": "대전",
    "울산": "울산", "울산광역시": "울산", "세종": "세종", "세종특별자치시": "세종",
    "경기": "경기", "경기도": "경기", "강원": "강원", "강원도": "강원", "강원특별자치도": "강원",
    "충북": "충북", "충청북도": "충북", "충남": "충남", "충청남도": "충남",
    "전북": "전북", "전라북도": "전북", "전북특별자치도": "전북",
    "전남": "전남", "전라남도": "전남", "경북": "경북", "경상북도": "경북",
    "경남": "경남", "경상남도": "경남", "제주": "제주", "제주특별자치도": "제주",
    "전국": "전국",
}


def strip_html(value: str | None) -> str:
    text = _BLOCK_BOUNDARY.sub(" ", value or "")
    text = _TAG.sub("", text)
    for entity, char in _ENTITIES:
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def parse_compact_date(value: str | None) -> date | None:
    """'20260812' 형식만 읽는다. 다른 형식은 추측하지 않고 None을 낸다."""
    text = (value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def parse_iso_date(value: str | None) -> date | None:
    text = (value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_range_dates(value: str | None) -> tuple[date | None, date | None]:
    """'2026-07-22 ~ 2026-08-18'을 두 날짜로 가른다."""
    text = (value or "").strip()
    if "~" not in text:
        return (None, None)
    head, _, tail = text.partition("~")
    return (parse_iso_date(head.strip()), parse_iso_date(tail.strip()))


def canonical_regions(value: str | None) -> list[str] | None:
    """지역 문자열을 짧은 표기 목록으로 바꾼다. 하나도 못 맞추면 None(=제한 미상)."""
    tokens = [token.strip() for token in re.split(r"[,/·]", value or "") if token.strip()]
    mapped = sorted({_REGION_ALIASES[token] for token in tokens if token in _REGION_ALIASES})
    return mapped or None


def resolve_status(application_end: date | None, today: date) -> str:
    """원천이 준 날짜의 산술이지 판단이 아니다. 날짜가 없으면 UNKNOWN으로 남는다."""
    if application_end is None:
        return "UNKNOWN"
    return "CLOSED" if application_end < today else "ACTIVE"


def display_status(application_end: date | None, today: date) -> str:
    """프론트 Program.status용 값.

    테이블의 status는 접수창이 열려 있는지를 뜻하고 프론트의 status는 자격 사전판정
    결과를 뜻한다. 접수 중이라는 사실은 자격이 있다는 뜻이 아니므로 ACTIVE를 잇지 않고
    UNKNOWN으로 둔다. 마감일이 지난 것만 CLOSED다 — 그건 날짜의 산술이다.
    """
    if application_end is not None and application_end < today:
        return "CLOSED"
    return "UNKNOWN"


@dataclass(frozen=True)
class KnowledgeDocument:
    id: str
    kind: str
    provider: str
    category: str
    title: str
    organization: str
    official_url: str
    body_text: str
    status: str
    raw: dict[str, Any]
    # 프론트가 이미 쓰는 Program/KbProduct 모양. 엔드포인트가 이걸 그대로 반환한다.
    display: dict[str, Any]
    regions: list[str] | None = None
    business_age_limit_years: int | None = None
    application_start: date | None = None
    application_end: date | None = None
    source_as_of: date | None = None

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.body_text.encode("utf-8")).hexdigest()

    def to_row(self, *, collected_at: str, embedding: list[float] | None,
               embedding_model: str | None) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "provider": self.provider, "category": self.category,
            "title": self.title, "organization": self.organization, "official_url": self.official_url,
            "body_text": self.body_text, "content_sha256": self.content_sha256,
            "embedding": embedding, "embedding_model": embedding_model,
            "regions": self.regions, "business_age_limit_years": self.business_age_limit_years,
            "application_start": self.application_start.isoformat() if self.application_start else None,
            "application_end": self.application_end.isoformat() if self.application_end else None,
            "status": self.status,
            "source_as_of": self.source_as_of.isoformat() if self.source_as_of else None,
            "raw": self.raw, "display": self.display, "collected_at": collected_at,
        }
