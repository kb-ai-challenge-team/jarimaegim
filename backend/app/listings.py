from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from supabase import Client, create_client

from .config import Settings
from .models import Candidate, ListingTerms, Provenance

DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "listings.seoul.json"

LIMITATIONS = [
    "실제 임대 매물이 아니며 계약 대상이 아닙니다.",
    "위치는 실제 상가 좌표이나 면적·월세는 서울교통공사 지하상가 임대정보 분포에서 생성했고, 보증금·관리비·층은 가정값입니다.",
]


class ListingService:
    """Demo listings, read once at startup. Supabase when configured, otherwise the committed seed file.

    Mirrors the dual-mode convention in repository.py so a machine with no keys still renders the map.
    """

    def __init__(self, settings: Settings, seed_path: Path | None = None):
        self.settings = settings
        self._by_id: dict[str, Candidate] = {}
        self._by_district: dict[str, list[Candidate]] = {}
        rows = self._load_supabase() if settings.supabase_configured else self._load_seed(seed_path or DEFAULT_SEED_PATH)
        for row in rows:
            candidate = self._to_candidate(row)
            self._by_id[candidate.id] = candidate
            self._by_district.setdefault(row["district"], []).append(candidate)
        for bucket in self._by_district.values():
            bucket.sort(key=lambda candidate: candidate.listing.monthly_rent_krw)

    def _load_seed(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8")).get("listings", [])

    def _load_supabase(self) -> list[dict[str, Any]]:
        client: Client = create_client(self.settings.supabase_url, self.settings.supabase_service_role_key)
        rows = client.table("listings").select("*").execute().data or []
        return [{
            "id": row["id"], "name": row["name"], "address": row["address"], "district": row["district"],
            "latitude": row["latitude"], "longitude": row["longitude"],
            "listing": {
                "listing_kind": row["listing_kind"], "deposit_krw": row["deposit_krw"],
                "monthly_rent_krw": row["monthly_rent_krw"], "maintenance_fee_krw": row["maintenance_fee_krw"],
                "area_m2": row["area_m2"], "floor": row["floor"],
            },
        } for row in rows]

    def _to_candidate(self, row: dict[str, Any]) -> Candidate:
        terms = ListingTerms(**row["listing"])
        provenance = Provenance(
            source_name="시연용 생성 데이터", source_as_of="2026-07-27",
            industry_scope="업종 무관 일반 상가", spatial_unit="개별 상가 좌표",
            confidence="LOW", limitations=LIMITATIONS,
        )
        return Candidate(
            id=row["id"], name=row["name"], address=row["address"],
            latitude=row["latitude"], longitude=row["longitude"],
            evidence_grade="C", display_label="시연용 매물", context_signals=[],
            provenance=provenance, listing=terms,
        )

    def covered_districts(self) -> set[str]:
        return set(self._by_district)

    def get(self, candidate_id: str) -> Candidate | None:
        return self._by_id.get(candidate_id)

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        """Alias so AnalysisService can take either this or LocationService without knowing which."""
        return self.get(candidate_id)

    def search(self, district: str, budget_krw: int | None, limit: int) -> tuple[list[Candidate], str, str | None]:
        bucket = self._by_district.get(district)
        if not bucket:
            covered = " · ".join(sorted(self._by_district)) or "없음"
            return [], "empty", f"현재 시연용 매물 데이터는 {covered} 에만 준비되어 있습니다."
        matched = [c for c in bucket if budget_krw is None or c.listing.deposit_krw <= budget_krw]
        if not matched:
            return [], "empty", "입력한 예산 안에 들어오는 시연용 매물이 없습니다. 예산을 조정해 다시 확인해 주세요."
        return matched[:limit], "success", None
