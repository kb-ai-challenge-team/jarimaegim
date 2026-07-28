from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any

from supabase import Client, create_client

from .config import Settings
from .industry import resolve as resolve_industry
from .models import Candidate, DistrictSummary, ListingTerms, Provenance, TradeAreaFit
from .ranking import axis_scores, cost_scores, weighted_total
from .trade_area import TradeAreaService, TradeAreaUnavailable

SUPABASE_PAGE = 1000

DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "listings.seoul.json"

LIMITATIONS = [
    "실제 임대 매물이 아니며 계약 대상이 아닙니다.",
    "위치는 실제 상가 좌표이나 면적·월세는 서울교통공사 지하상가 임대정보 분포에서 생성했고, 보증금·관리비·층은 가정값입니다.",
    "권리금·전용면적·준공년도·주차·코너·전면폭·엘리베이터·총층수·입주가능일은 실측 출처가 없어 가정한 값입니다. 계약 전 직접 확인해야 합니다.",
]

# Supabase 에서 읽어 오는 가정값 열. pipeline/lib/attribute-constants.mjs 가 생성하고
# scripts/seed-listings.mjs 가 적재한다. 세 곳의 목록이 어긋나면 값이 조용히 사라진다.
ASSUMED_COLUMNS = ("key_money_krw", "exclusive_area_m2", "built_year", "parking_slots",
                   "corner", "elevator", "floors_total", "frontage_m", "available_from")


class ListingService:
    """Demo listings, read once at startup. Supabase when configured, otherwise the committed seed file.

    Mirrors the dual-mode convention in repository.py so a machine with no keys still renders the map.

    임대 조건(보증금·월세·면적·층)은 시연용 생성 데이터지만, 후보를 고르고 줄 세우는 근거는
    실측 공개 데이터다. 각 매물의 좌표가 속한 행정동을 통해 서울시 상권분석서비스의
    업종별 집계를 붙인다. 두 성격이 한 카드 안에 섞이므로 provenance 도 둘 다 나간다.
    """

    def __init__(self, settings: Settings, seed_path: Path | None = None, trade_areas: TradeAreaService | None = None):
        self.settings = settings
        self.trade_areas = trade_areas or TradeAreaService()
        self._by_id: dict[str, Candidate] = {}
        self._by_district: dict[str, list[Candidate]] = {}
        rows: list[dict[str, Any]] = self._load_supabase() if settings.supabase_configured else []
        if not rows:
            rows = self._load_seed(seed_path or DEFAULT_SEED_PATH)
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
        try:
            client: Client = create_client(self.settings.supabase_url, self.settings.supabase_service_role_key)
            # PostgREST caps an unranged select at 1000 rows and says nothing about the ones it
            # dropped. At 275 listings that was invisible; at 1045 it silently truncated a whole
            # district. Page until a batch comes back short.
            rows: list[dict[str, Any]] = []
            while True:
                batch = client.table("listings").select("*").range(len(rows), len(rows) + SUPABASE_PAGE - 1).execute().data or []
                rows.extend(batch)
                if len(batch) < SUPABASE_PAGE:
                    break
        except Exception as exc:
            # Public reference data. A missing or unreadable table must not take down the whole API,
            # so fall back to the committed seed, which holds the content the seeding script uploads.
            print(f"[listings] Supabase read failed, falling back to the committed seed: {exc}")
            return []
        return [{
            "id": row["id"], "name": row["name"], "address": row["address"], "district": row["district"],
            "latitude": row["latitude"], "longitude": row["longitude"],
            # 행정동은 나중에 추가된 열이다. 아직 마이그레이션되지 않은 테이블에서도 읽히도록
            # 없으면 None 으로 둔다 — 그 매물은 상권 축만 꺼진 채 목록에 남는다.
            "admin_dong": row.get("admin_dong"), "admin_dong_code": row.get("admin_dong_code"),
            "listing": {
                "listing_kind": row["listing_kind"], "deposit_krw": row["deposit_krw"],
                "monthly_rent_krw": row["monthly_rent_krw"], "maintenance_fee_krw": row["maintenance_fee_krw"],
                "area_m2": row["area_m2"], "floor": row["floor"],
                # 부가 속성은 나중에 추가된 열이다. admin_dong 과 같은 이유로 .get 을 쓴다 —
                # 마이그레이션 이전 테이블에서도 매물 자체는 읽히고 이 항목만 비워진다.
                **{key: row.get(key) for key in ASSUMED_COLUMNS},
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
            admin_dong=row.get("admin_dong"), admin_dong_code=row.get("admin_dong_code"),
            evidence_grade="C", display_label="시연용 매물", context_signals=[],
            provenance=provenance, listing=terms,
        )

    def covered_districts(self) -> set[str]:
        return set(self._by_district)

    def summary(self) -> list[DistrictSummary]:
        """Per-district aggregate for the landing map. Median rather than mean so one
        expensive unit does not drag a district's headline number."""
        entries = []
        for district in sorted(self._by_district):
            bucket = self._by_district[district]
            entries.append(DistrictSummary(
                district=district,
                count=len(bucket),
                median_monthly_rent_krw=round(median(c.listing.monthly_rent_krw for c in bucket)),
                latitude=sum(c.latitude for c in bucket) / len(bucket),
                longitude=sum(c.longitude for c in bucket) / len(bucket),
            ))
        return entries

    def get(self, candidate_id: str) -> Candidate | None:
        return self._by_id.get(candidate_id)

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        """Alias so AnalysisService can take either this or LocationService without knowing which."""
        return self.get(candidate_id)

    def enrich(self, candidate: Candidate, industry: str) -> Candidate:
        """후보 하나에 상권 신호를 붙인 사본. 원본 카탈로그는 건드리지 않는다."""
        industry_code = resolve_industry(industry)
        profile = self.trade_areas.lookup(candidate.admin_dong_code, industry_code)
        if isinstance(profile, TradeAreaUnavailable):
            return candidate.model_copy(update={
                "trade_area_fit": TradeAreaFit(status="unavailable", reason=profile.reason,
                                               unjudged_axes=["demand", "competition", "turnover", "sales"]),
            })
        signals = self.trade_areas.signals(profile)
        return candidate.model_copy(update={
            "context_signals": signals,
            # 등급이 C에서 B로 올라가는 지점이다. 개별 좌표만 확인된 상태(C)에서
            # 상권×업종 집계를 확인한 상태(B)가 된다. A는 개별 이력이 있어야 하므로 여기서 나올 수 없다.
            "evidence_grade": "B",
            "display_label": "상권 위험 진단",
            "provenance": self.trade_areas.provenance(
                industry_code=profile["industry_code"], sample_n=profile.get("store_count"),
                trade_area_count=profile.get("trade_area_count"),
                extra_limitations=LIMITATIONS,
            ),
        })

    def search(self, district: str, budget_krw: int | None, limit: int,
               industry: str = "", priority: str = "STABILITY") -> tuple[list[Candidate], str, str | None]:
        """예산 안의 후보를 업종·우선순위 기준으로 줄 세운다.

        상권 통계를 확인한 후보가 먼저 오고, 확인하지 못한 후보는 그 뒤에 월세 순으로 붙는다.
        뒤로 보내는 것이지 떨어뜨리는 것이 아니며, 각 후보가 왜 판정되지 않았는지는
        `trade_area_fit.reason` 에 실려 나간다.
        """
        bucket = self._by_district.get(district)
        if not bucket:
            covered = " · ".join(sorted(self._by_district)) or "없음"
            return [], "empty", f"현재 시연용 매물 데이터는 {covered} 에만 준비되어 있습니다."
        matched = [c for c in bucket if budget_krw is None or c.listing.deposit_krw <= budget_krw]
        if not matched:
            return [], "empty", "입력한 예산 안에 들어오는 시연용 매물이 없습니다. 예산을 조정해 다시 확인해 주세요."

        industry_code = resolve_industry(industry)
        benchmark = self.trade_areas.benchmark(industry_code)
        by_rent = cost_scores([c.listing.monthly_rent_krw for c in matched])

        judged: list[tuple[float, Candidate]] = []
        unjudged: list[Candidate] = []
        for candidate in matched:
            profile = self.trade_areas.lookup(candidate.admin_dong_code, industry_code)
            if isinstance(profile, TradeAreaUnavailable):
                unjudged.append(candidate.model_copy(update={
                    "trade_area_fit": TradeAreaFit(status="unavailable", reason=profile.reason,
                                                   unjudged_axes=["demand", "competition", "turnover", "sales"]),
                }))
                continue
            scores = axis_scores(
                profile, benchmark, by_rent.get(candidate.listing.monthly_rent_krw),
                self.trade_areas.close_rate_percentile(profile["industry_code"], profile.get("close_rate")),
            )
            total, judged_axes, unjudged_axes = weighted_total(scores, priority)
            enriched = candidate.model_copy(update={
                "context_signals": self.trade_areas.signals(profile),
                "evidence_grade": "B",
                "display_label": "상권 위험 진단",
                "provenance": self.trade_areas.provenance(
                    industry_code=profile["industry_code"], sample_n=profile.get("store_count"),
                    trade_area_count=profile.get("trade_area_count"),
                    # 같은 카드에 상권 실측과 가정값 임대 조건이 함께 뜬다. 매물 쪽 한계를
                    # 얹지 않으면 권리금 같은 가정값이 실측 출처만 달고 나간다.
                    extra_limitations=LIMITATIONS,
                ),
                "trade_area_fit": TradeAreaFit(
                    status="judged", score=round(total, 4), judged_axes=judged_axes, unjudged_axes=unjudged_axes,
                    store_count=profile.get("store_count"), trade_area_count=profile.get("trade_area_count"),
                ),
            })
            judged.append((total, enriched))

        # 점수 내림차순, 동점이면 월세 낮은 순. 두 번째 키가 없으면 같은 점수 후보의 순서가
        # 사전 정렬 순서에 따라 임의로 정해진다.
        judged.sort(key=lambda pair: (-pair[0], pair[1].listing.monthly_rent_krw, pair[1].id))
        ordered = [candidate for _, candidate in judged] + unjudged
        result = ordered[:limit]

        if not industry.strip():
            # 업종을 아직 받지 않은 상태(랜딩 지도의 자치구 둘러보기)다. 실패가 아니므로
            # 사용자에게 알릴 것이 없다.
            message = None
        elif not industry_code:
            message = f"'{industry}'은(는) 서울시 상권분석서비스 업종 분류에 연결되지 않아 상권 근거 없이 월세 기준으로만 정렬했습니다."
        elif not judged:
            message = "예산 안의 후보 가운데 상권 통계를 확인한 곳이 없어 월세 기준으로만 정렬했습니다."
        elif unjudged and len(result) > len(judged):
            message = f"{len(judged)}곳은 상권 통계로 판정했고, 나머지는 통계가 없어 뒤에 월세 순으로 붙였습니다."
        else:
            message = None
        return result, "success", message
