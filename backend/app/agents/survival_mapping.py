"""인허가 업종코드 ↔ 상권분석 서비스업종 코드의 대조 결과.

제안서 15장이 "가장 위험"으로 지목한 리스크가 업종코드 매핑 오류다. 이 오류의 성질이
다른 오류와 다른 점은 **화면에 오류로 나타나지 않는다**는 것이다. 잘못 이어진 코드로 조회한
생존율은 예외도 빈 상태도 아닌, 그럴듯한 숫자로 나온다. 사용자는 그것이 다른 업종의 통계라는
사실을 알 방법이 없다.

그래서 매핑은 **제안과 확정을 분리한다.** 모델은 후보 쌍을 제안할 수 있지만, 확정은 이
파일의 대조 결과가 한다. 여기에 없는 쌍은 통과하지 못하고, 통과하지 못하면 해당 축이 꺼진다.
"모르면 끈다"가 "그럴듯한 숫자를 낸다"보다 낫다는 판단이 이 파일의 전부다.

`VERIFIED_PAIRS` 가 비어 있는 것은 미완성이 아니라 현재의 사실이다 — 두 코드 체계의 원문
대조를 아직 하지 않았고, 대조하지 않은 쌍을 등록하면 이 파일이 막으려는 오류를 이 파일이
만들게 된다. 대조를 마친 쌍만, 출처와 함께 등록한다.
"""
from __future__ import annotations

from typing import Iterable

#: (인허가 업종코드, 상권분석 서비스업종 코드). 원문 대조를 마친 쌍만 등록한다.
VERIFIED_PAIRS: frozenset[tuple[str, str]] = frozenset()


class VerificationTable:
    """제안된 매핑을 확정된 것과 확정되지 않은 것으로 가른다."""

    def __init__(self, pairs: Iterable[tuple[str, str]] | None = None):
        self.pairs = frozenset(pairs if pairs is not None else VERIFIED_PAIRS)

    @property
    def empty(self) -> bool:
        return not self.pairs

    def split(self, proposed: Iterable[tuple[str, str]]
              ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        confirmed, rejected = [], []
        for pair in proposed:
            (confirmed if pair in self.pairs else rejected).append(pair)
        return confirmed, rejected
