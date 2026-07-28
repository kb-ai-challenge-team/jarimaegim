from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


class DocumentStore:
    def __init__(self, directory: str):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def save(self, *, owner_session_id: UUID, case_id: UUID, template: str, pdf: bytes, document_id: UUID | None = None) -> dict[str, Any]:
        document_id = document_id or uuid4()
        created_at = datetime.now(UTC).isoformat()
        metadata = {
            "document_id": str(document_id), "owner_session_id": str(owner_session_id),
            "case_id": str(case_id), "template": template, "status": "ready",
            "created_at": created_at, "updated_at": created_at,
        }
        pdf_path = self.root / f"{document_id}.pdf"
        meta_path = self.root / f"{document_id}.json"
        pdf_tmp, meta_tmp = pdf_path.with_suffix(".pdf.tmp"), meta_path.with_suffix(".json.tmp")
        pdf_tmp.write_bytes(pdf)
        meta_tmp.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        os.chmod(pdf_tmp, 0o600)
        os.chmod(meta_tmp, 0o600)
        pdf_tmp.replace(pdf_path)
        meta_tmp.replace(meta_path)
        return metadata

    def get(self, document_id: UUID) -> dict[str, Any] | None:
        path = self.root / f"{document_id}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return None

    def pdf_path(self, document_id: UUID) -> Path | None:
        path = self.root / f"{document_id}.pdf"
        return path if path.is_file() else None


LISTING_DEMO_NOTICE = ("실제 임대 매물이 아니며 계약 대상이 아닙니다. 위치는 실제 상가 좌표이나 "
                       "면적·월세는 서울교통공사 지하상가 임대정보 분포에서 생성했고, 보증금·관리비·층은 가정값입니다.")

FUNDING_OMITTED = "조달 밴드를 계산하지 못해 이 문서에는 조달 요약이 없습니다."


def krw(value: int | None) -> str:
    """금액 표기. 없는 값은 0 이 아니라 '확인 필요'다 — 없는 것을 0 으로 적으면 계산된 0 처럼 읽힌다."""
    return "확인 필요" if value is None else f"{value:,}원"


def funding_section_lines(funding: dict[str, Any] | None) -> list[str]:
    """조달 요약 줄. 첫 줄은 언제나 제목이고, 계산이 없으면 없다는 사실을 그 자리에 적는다.

    화면이 계산한 숫자를 받지 않는다. 호출부가 compute_bands 를 다시 돌린 결과를 넘긴다.
    """
    bands = (funding or {}).get("bands") or []
    line = next((band for band in bands if band["band"] == "RECOMMENDED"), None)
    if funding is None or line is None:
        return ["자금조달 요약", FUNDING_OMITTED]
    lines = ["자금조달 요약",
             f"권장 조달선: {krw(line['ceiling_krw'])}",
             f"차입 필요액: {krw(line['loan_krw'])}",
             f"월 상환: {krw(line['monthly_repayment_krw'])}",
             f"넘어야 하는 일매출: {krw(line['target_daily_revenue_krw'])}"]
    required = funding.get("required_capital_krw")
    lines.append(f"필요자금: {krw(required)}" if required is not None
                 else "필요자금: 확인 필요 — 평수·보증금을 입력하지 않아 계산하지 않았습니다")
    assumed = funding.get("assumed") or []
    if assumed:
        lines.append(f"위 금액은 시연용 가정값 {len(assumed)}개 항목 위에서 계산했습니다. "
                     "공고 원문으로 확인한 값이 아니므로 실제 심사 결과와 다릅니다.")
    lines.append(f"출처: 자리매김 조달 밴드 계산 · 기준일 {funding.get('as_of') or '확인 필요'}")
    return lines


def rate_text(product: dict[str, Any]) -> str:
    """공시 금리 표기. 두 공시값을 나란히 적을 뿐 평균·환산 같은 계산을 하지 않는다.
    화면의 rateLabel(components/kb/JarimaegimPlan.tsx)과 같은 규칙이어야 문서와 화면이 갈라지지 않는다."""
    low, high = product.get("rate_min"), product.get("rate_max")
    if low is None and high is None:
        return "공시 금리 확인 필요"
    if low == high:
        return f"{low}%"
    return f"{'?' if low is None else low}~{'?' if high is None else high}%"


def selection_section_lines(products: list[dict[str, Any]], programs: list[dict[str, Any]],
                            dropped: int) -> list[str]:
    """사용자가 고른 조달 수단. 전달된 dict 는 서버 카탈로그에서 되찾은 것이며 클라이언트 문자열이 아니다."""
    if not products and not programs and dropped == 0:
        return ["고른 조달 수단", "고른 조달 수단이 없습니다."]
    lines = ["고른 조달 수단"]
    for product in products:
        lines.append(f"[KB 공시] {product.get('name', '이름 확인 필요')} · "
                     f"{product.get('loan_limit') or '한도 원문 확인'} · {rate_text(product)} · "
                     f"기준월 {product.get('source_as_of') or '확인 필요'}")
        lines.append(f"원문: {product.get('official_url', '확인 필요')}")
    for program in programs:
        lines.append(f"[공고] {program.get('title', '제목 확인 필요')} · "
                     f"{program.get('organization', '기관 확인 필요')} · "
                     f"{program.get('application_period') or '기간 원문 확인'}")
        lines.append(f"원문: {program.get('official_url', '확인 필요')}")
    lines.append("공시·공고 문구와 입력 조건을 텍스트로 대조해 고른 목록이며, 자격이나 승인 가능성을 판단한 것이 아닙니다.")
    if dropped:
        lines.append(f"{dropped}건은 공시 목록에서 확인되지 않아 제외했습니다.")
    return lines


def listing_section_lines(case: dict[str, Any]) -> list[str]:
    """Lines for the committed-listing block; empty when the case has no committed listing.

    Kept separate from rendering because the PDF encodes text through a CID font, which makes
    byte-level assertions on the output meaningless. Assert on this instead.
    """
    listing_id = case.get("inputs", {}).get("committed_listing_id")
    if not listing_id:
        return []
    return ["선택한 자리 (시연용 생성 데이터)", f"매물 ID: {listing_id}", LISTING_DEMO_NOTICE]


def render_case_pdf(case: dict[str, Any], document: dict[str, Any]) -> bytes:
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
        font = "HYSMyeongJo-Medium"
    except Exception:
        font = "Helvetica"
    buffer = BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A4, title="자리매김 PDF 초안", author="자리매김")
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font
    rows = [["문서 ID", str(document["document_id"])], ["템플릿", str(document["template"])], ["케이스", str(case["id"])], ["제목", str(case["title"])], ["버전", str(case["version"])]]
    table = Table(rows, colWidths=[110, 380])
    table.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), font), ("GRID", (0, 0), (-1, -1), .25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story = [Paragraph("자리매김 PDF 초안", styles["Title"]), Spacer(1, 12), table, Spacer(1, 16), Paragraph("사용자 확인값", styles["Heading2"])]
    for key, value in case.get("inputs", {}).items():
        story.append(Paragraph(f"{key}: {value}", styles["BodyText"]))
    lines = listing_section_lines(case)
    if lines:
        heading, *body = lines
        story.append(Spacer(1, 16))
        story.append(Paragraph(heading, styles["Heading2"]))
        story.extend(Paragraph(line, styles["BodyText"]) for line in body)
    story.extend([Spacer(1, 16), Paragraph("AI가 작성한 초안이며 사용자 검토가 필요합니다. 결과는 보장되지 않으며 공식 원문이 우선합니다. 확인하지 못한 값은 공란으로 유지합니다.", styles["BodyText"])])
    pdf.build(story)
    return buffer.getvalue()
