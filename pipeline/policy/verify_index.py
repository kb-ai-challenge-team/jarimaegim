"""인덱스 상태를 사람이 읽는 형태로 출력한다. 자동 판정이 아니다.

pipeline/verify/cross_check.py와 같은 성격이다 — 숫자를 보여 주고 판단은 사람이 한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from openai import OpenAI
from supabase import create_client

sys.path.insert(0, str(Path(__file__).parent))
from index import SELECT_PAGE, TABLE, load_env  # noqa: E402

PROBES = ("서울 소상공인 창업 자금 지원", "청년 창업 임차료 지원", "개인사업자 대출 금리", "카페 창업 시설 자금")


def main() -> int:
    cfg = load_env()
    if not (cfg.get("SUPABASE_URL") and cfg.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("SUPABASE 설정이 없습니다.", file=sys.stderr)
        return 1
    supabase = create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])

    rows: list[dict] = []
    start = 0
    while True:
        page = (supabase.table(TABLE).select("id,kind,provider,status,embedding_model,collected_at")
                .order("id").range(start, start + SELECT_PAGE - 1).execute().data or [])
        rows.extend(page)
        if len(page) < SELECT_PAGE:
            break
        start += SELECT_PAGE

    print(f"문서 {len(rows)}건")
    for key in ("kind", "provider", "status"):
        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row.get(key))] = counts.get(str(row.get(key)), 0) + 1
        print(f"  {key}: {counts}")
    print(f"  마지막 수집: {max((r['collected_at'] for r in rows), default='없음')}")

    missing = supabase.table(TABLE).select("id", count="exact").is_("embedding", "null").limit(1).execute()
    print(f"  임베딩 결측: {missing.count}건")

    model = cfg.get("EMBEDDING_MODEL", "")
    if not (cfg.get("OPENAI_API_KEY") and model):
        print("\nOPENAI_API_KEY / EMBEDDING_MODEL이 없어 질의 확인은 건너뜁니다.")
        return 0

    openai = OpenAI(api_key=cfg["OPENAI_API_KEY"])
    for probe in PROBES:
        vector = openai.embeddings.create(model=model, input=[probe]).data[0].embedding
        hits = supabase.rpc("search_knowledge", {
            "query_embedding": vector, "match_regions": ["서울", "전국"], "match_count": 5,
        }).execute().data or []
        print(f"\n질의: {probe}")
        for hit in hits:
            print(f"  {hit['similarity']:.3f}  [{hit['provider']}] {hit['title'][:60]}")
        if not hits:
            print("  (결과 없음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
