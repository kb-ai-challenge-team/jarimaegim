"""수집 → 정규화 → 차분 → 임베딩 → upsert → prune.

prune은 provider 단위로, 그 provider의 수집이 완전히 성공했을 때만 한다. 한 원천이
5xx를 뱉은 회차에 다른 원천의 결과로 전체를 정리하면 외부 장애가 우리 인덱스를
비우는 사고가 된다 — 설계 §4.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from openai import OpenAI
from supabase import create_client

sys.path.insert(0, str(Path(__file__).parent))

from embed import embed_texts                                            # noqa: E402
from fetch import fetch_bizinfo, fetch_kb_products, fetch_kstartup       # noqa: E402
from normalize import (KnowledgeDocument, normalize_bizinfo,             # noqa: E402
                       normalize_kb_product, normalize_kstartup)

ROOT = Path(__file__).resolve().parents[2]
TABLE = "knowledge_documents"
UPSERT_CHUNK = 200
SELECT_PAGE = 1000


def load_env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    for name in (".env", ".env.local"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            cfg[key.strip()] = value.strip().strip('"').strip("'")
    return cfg


def collect(cfg: dict[str, str], today: date) -> tuple[list[KnowledgeDocument], dict[str, bool]]:
    documents: list[KnowledgeDocument] = []
    healthy: dict[str, bool] = {}
    with httpx.Client(follow_redirects=True) as client:
        records, ok = fetch_bizinfo(client, cfg.get("BIZINFO_API_URL", ""), cfg.get("BIZINFO_API_KEY", ""))
        healthy["기업마당"] = ok
        documents.extend(doc for doc in (normalize_bizinfo(r, today=today) for r in records) if doc)
        print(f"기업마당: {len(records)} records, ok={ok}")

        records, ok = fetch_kstartup(client, cfg.get("KSTARTUP_API_URL", ""), cfg.get("KSTARTUP_API_KEY", ""))
        healthy["K-Startup"] = ok
        documents.extend(doc for doc in (normalize_kstartup(r, today=today) for r in records) if doc)
        print(f"K-Startup: {len(records)} records, ok={ok}")

        products, ok = fetch_kb_products(client, cfg.get("FINLIFE_API_BASE_URL", ""), cfg.get("FINLIFE_API_KEY", ""))
        healthy["금융상품 한눈에"] = ok
        documents.extend(doc for doc in (
            normalize_kb_product(base, option, category=category, label=label,
                                 kind_of_rate=kind_of_rate, source_url=source_url)
            for base, option, category, label, kind_of_rate, source_url in products) if doc)
        print(f"금융상품 한눈에: {len(products)} records, ok={ok}")

    unique: dict[str, KnowledgeDocument] = {}
    for doc in documents:
        unique.setdefault(doc.id, doc)
    return (list(unique.values()), healthy)


def _existing_rows(supabase) -> list[dict]:
    """PostgREST는 응답을 1000행에서 자른다. 한 번만 읽으면 그 뒤 문서가 전부
    '처음 보는 문서'로 보이고 매 회차 재임베딩된다. 실제로 그렇게 겪었다."""
    rows: list[dict] = []
    start = 0
    while True:
        page = (supabase.table(TABLE).select("id,content_sha256,embedding_model")
                .order("id").range(start, start + SELECT_PAGE - 1).execute().data or [])
        rows.extend(page)
        if len(page) < SELECT_PAGE:
            return rows
        start += SELECT_PAGE


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reembed", action="store_true",
                        help="본문이 그대로여도 전량 재임베딩한다. 임베딩 모델을 바꿀 때만 쓴다.")
    args = parser.parse_args()

    cfg = load_env()
    model = cfg.get("EMBEDDING_MODEL", "")
    if not (cfg.get("SUPABASE_URL") and cfg.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY가 없습니다.", file=sys.stderr)
        return 1
    if not (cfg.get("OPENAI_API_KEY") and model):
        print("OPENAI_API_KEY / EMBEDDING_MODEL이 없습니다.", file=sys.stderr)
        return 1

    run_started_at = datetime.now(UTC)
    today = run_started_at.date()
    supabase = create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])
    openai = OpenAI(api_key=cfg["OPENAI_API_KEY"])

    documents, healthy = collect(cfg, today)
    if not any(healthy.values()):
        print("모든 원천 수집에 실패했습니다. 인덱스를 건드리지 않고 종료합니다.", file=sys.stderr)
        return 1

    existing = {row["id"]: row for row in _existing_rows(supabase)}

    # 임베딩 모델이 섞이면 유사도가 의미를 잃는다. 자동으로 섞지 않고 멈춘다 — 설계 §8.
    stale_models = {row.get("embedding_model") for row in existing.values()
                    if row.get("embedding_model") and row.get("embedding_model") != model}
    if stale_models and not args.reembed:
        print(f"인덱스에 다른 임베딩 모델이 있습니다: {sorted(stale_models)}. "
              f"--reembed로 전량 재생성하세요.", file=sys.stderr)
        return 1

    needs_embedding = [doc for doc in documents
                       if args.reembed
                       or doc.id not in existing
                       or existing[doc.id].get("content_sha256") != doc.content_sha256
                       or not existing[doc.id].get("embedding_model")]
    print(f"문서 {len(documents)}건, 임베딩 대상 {len(needs_embedding)}건")

    vectors: dict[str, list[float] | None] = {}
    if needs_embedding:
        computed = embed_texts(openai, model, [doc.body_text for doc in needs_embedding])
        vectors = {doc.id: vector for doc, vector in zip(needs_embedding, computed, strict=True)}

    collected_at = run_started_at.isoformat()
    rows = []
    missing = 0
    for doc in documents:
        if doc.id in vectors:
            vector = vectors[doc.id]
            missing += 1 if vector is None else 0
            rows.append(doc.to_row(collected_at=collected_at, embedding=vector,
                                   embedding_model=model if vector else None))
        else:
            # 본문이 그대로인 문서는 벡터를 건드리지 않는다. 메타데이터만 갱신한다.
            row = doc.to_row(collected_at=collected_at, embedding=None, embedding_model=None)
            row.pop("embedding")
            row.pop("embedding_model")
            rows.append(row)

    # 벡터를 보내는 행과 보내지 않는 행은 열 구성이 달라 한 번에 upsert할 수 없다.
    with_vector = [row for row in rows if "embedding" in row]
    without_vector = [row for row in rows if "embedding" not in row]
    for group in (with_vector, without_vector):
        for start in range(0, len(group), UPSERT_CHUNK):
            supabase.table(TABLE).upsert(group[start:start + UPSERT_CHUNK]).execute()
    print(f"upsert {len(rows)}건 (벡터 갱신 {len(with_vector)}건, 메타데이터만 {len(without_vector)}건)")

    for provider, ok in healthy.items():
        if not ok:
            print(f"{provider}: 수집이 불완전하여 prune을 건너뜁니다.", file=sys.stderr)
            continue
        removed = (supabase.table(TABLE).delete()
                   .eq("provider", provider).lt("collected_at", collected_at).execute().data or [])
        print(f"{provider}: prune {len(removed)}건")

    if missing:
        print(f"임베딩 결측 {missing}건 — 다음 회차가 재시도합니다.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
