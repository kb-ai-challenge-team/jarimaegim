"""Apply a SQL migration file through SUPABASE_DB_URL.

psql과 supabase CLI가 모두 없는 환경을 위한 최소 러너다. 파일 하나를 한 트랜잭션으로
실행하고, 실패하면 전부 롤백한다. 키 값은 절대 출력하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]


def db_url() -> str:
    for name in (".env", ".env.local"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "SUPABASE_DB_URL" and value.strip():
                return value.strip().strip('"').strip("'")
    raise SystemExit("SUPABASE_DB_URL이 .env에 없습니다.")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-migration.py <path-to-sql>")
    sql_path = Path(sys.argv[1])
    sql = sql_path.read_text()
    conn = psycopg2.connect(db_url())
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql)
        print(f"applied {sql_path.name}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
