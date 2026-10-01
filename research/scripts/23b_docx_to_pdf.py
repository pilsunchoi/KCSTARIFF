"""
23b_docx_to_pdf.py — DOCX → PDF(MS Word COM). pywin32가 있는 기본 anaconda python으로 돌린다(kcsdb 환경에는 pywin32가 없고 기본 python에는 python-docx가 없어 23과 나눈다).
사용: C:\\Users\\pilsu\\anaconda3\\python.exe scripts/23b_docx_to_pdf.py <docx> [<docx> ...]
"""
import sys
from pathlib import Path

import win32com.client


def to_pdf(docx_path: Path) -> Path:
    pdf = docx_path.with_suffix(".pdf")
    word = win32com.client.DispatchEx("Word.Application"); word.Visible = False; word.DisplayAlerts = 0
    try:
        d = word.Documents.Open(str(docx_path.resolve()), ReadOnly=True)
        try:
            d.ExportAsFixedFormat(str(pdf.resolve()), 17)
            n = d.ComputeStatistics(2)  # wdStatisticPages
        finally:
            d.Close(False)
    finally:
        word.Quit()
    print("PDF", pdf, pdf.stat().st_size, "bytes,", n, "쪽")
    return pdf


if __name__ == "__main__":
    for p in sys.argv[1:]: to_pdf(Path(p))
