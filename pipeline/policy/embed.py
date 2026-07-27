"""텍스트 배치를 벡터로 바꾼다.

배치 하나가 실패하면 그 배치만 None으로 돌려준다. 호출자가 embedding=null로 저장하고
다음 회차가 재시도한다 — 설계 §8.
"""
from __future__ import annotations

from openai import OpenAI

BATCH_SIZE = 100


def embed_texts(client: OpenAI, model: str, texts: list[str]) -> list[list[float] | None]:
    vectors: list[list[float] | None] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        try:
            response = client.embeddings.create(model=model, input=batch)
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 배치 단위로 흡수한다
            print(f"  embedding batch {start // BATCH_SIZE} failed: {type(exc).__name__}")
            vectors.extend([None] * len(batch))
            continue
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors.extend(item.embedding for item in ordered)
    return vectors
