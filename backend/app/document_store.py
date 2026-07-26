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
    story.extend([Spacer(1, 16), Paragraph("AI가 작성한 초안이며 사용자 검토가 필요합니다. 결과는 보장되지 않으며 공식 원문이 우선합니다. 확인하지 못한 값은 공란으로 유지합니다.", styles["BodyText"])])
    pdf.build(story)
    return buffer.getvalue()
