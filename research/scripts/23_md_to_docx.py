"""
23_md_to_docx.py — 학술 MD → DOCX(→ PDF) 변환(C:\Work\Projects\conventions\research-writing-principles.md §VI의 파이프라인, 2026-09-13).

pandoc <md> -o <docx> --reference-doc=<참조 DOCX> 로 옮긴 뒤 python-docx로 후처리한다:
  검정 글자, 표 괘선(모든 표에 단선 괘선), 2단 병합 머리글(`<!-- Word 변환 지침: 머리글 2단 … -->` 주석이 있는 표),
  블록 간격(문단 뒤 6pt, 표·제목 앞뒤), 장 제목(## ) 앞 페이지 나누기, 본문 양쪽맞춤과 첫줄 들여쓰기(제목·표·목록·수식 단독 문단 제외).
PDF는 --pdf 를 주면 MS Word COM(DispatchEx, DisplayAlerts=0, try/finally Quit)으로 뽑는다 — pywin32가 있는 python(기본 anaconda)으로 돌려야 한다.

사용: python scripts/23_md_to_docx.py <md 파일> [--ref <docx>] [--pdf]
   참조 DOCX 기본값: KCSDB2/research/washer_safeguard/미국의_세탁기_무역조치와_한국_교역구조의_재편.docx
   (프롬프트가 지정한 "트럼프 관세와 한국 무역" DOCX는 저장소에 없다.)
"""
from __future__ import annotations

import argparse
import copy
import os
import re
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

KCSDB2 = Path(os.environ.get("KCSDB2_ROOT", r"C:\Work\Projects\KCSDB2"))
DEFAULT_REF = KCSDB2 / "research" / "washer_safeguard" / "미국의_세탁기_무역조치와_한국_교역구조의_재편.docx"
PANDOC = os.environ.get("PANDOC", "pandoc")


def set_cell_borders(cell, sz=4):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single"); el.set(qn("w:sz"), str(sz)); el.set(qn("w:space"), "0"); el.set(qn("w:color"), "000000")
        borders.append(el)
    for old in tcPr.findall(qn("w:tcBorders")): tcPr.remove(old)
    tcPr.append(borders)


def black_runs(doc):
    for p in doc.paragraphs:
        for r in p.runs: r.font.color.rgb = RGBColor(0, 0, 0)
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    for r in p.runs: r.font.color.rgb = RGBColor(0, 0, 0)


def merge_header(table, spec):
    """spec: '머리글 2단 상단=[(시작열,끝열,라벨),...]' 형태의 지침을 받아 첫 행 위에 병합 머리글 행을 만든다.
    지침 문법(주석 안): 머리글 2단; 상단: 0-0:, 1-2:2022년, 3-4:2025년  (열 번호는 0부터, 라벨이 비면 세로 병합)"""
    m = re.search(r"상단\s*[:：]\s*(.+)$", spec)
    if not m: return
    groups = []
    for part in m.group(1).split(","):
        part = part.strip()
        mm = re.match(r"(\d+)\s*-\s*(\d+)\s*[:：]\s*(.*)$", part)
        if mm: groups.append((int(mm.group(1)), int(mm.group(2)), mm.group(3).strip()))
    if not groups: return
    first = table.rows[0]
    new_tr = copy.deepcopy(first._tr); first._tr.addprevious(new_tr)
    top = table.rows[0]
    for c in top.cells:
        for p in c.paragraphs:
            for r in p.runs: r.text = ""
    ncol = len(top.cells)
    for a, b, label in groups:
        if a >= ncol: continue
        b = min(b, ncol - 1)
        cell = top.cells[a]
        if b > a: cell = cell.merge(top.cells[b])
        if label:
            cell.paragraphs[0].add_run(label).bold = True
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        else:
            # 세로 병합: 위 칸(빈 라벨)과 아래 칸을 합친다
            below = table.rows[1].cells[a]
            txt = below.text
            merged = cell.merge(below)
            for p in merged.paragraphs[1:]:
                p._p.getparent().remove(p._p)
            for r in merged.paragraphs[0].runs: r.text = ""
            merged.paragraphs[0].add_run(txt).bold = True


def is_body(p):
    st = (p.style.name or "").lower()
    if st.startswith("heading") or st.startswith("title") or "list" in st or "caption" in st or st in ("source code", "block text"): return False
    if p._p.getparent().tag.endswith("}tc"): return False
    if p._p.find(".//" + qn("m:oMathPara")) is not None: return False  # 수식 단독 문단
    t = p.text.strip()
    if not t: return False
    if t.startswith("**표 ") or re.match(r"^표 \d", t) or re.match(r"^그림 \d", t): return False
    return True


def postprocess(docx_path: Path, specs: list[str]):
    doc = Document(str(docx_path))
    black_runs(doc)
    # 표 괘선·간격, 머리글 병합, 열 너비 자동(pandoc이 넣은 고정 너비를 풀어 코드 열이 끊기지 않게)
    for i, t in enumerate(doc.tables):
        tblPr = t._tbl.tblPr
        for old in tblPr.findall(qn("w:tblLayout")): tblPr.remove(old)
        lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "autofit"); tblPr.append(lay)
        tblW = tblPr.find(qn("w:tblW"))
        if tblW is None: tblW = OxmlElement("w:tblW"); tblPr.append(tblW)
        tblW.set(qn("w:type"), "pct"); tblW.set(qn("w:w"), "5000")
        for row in t.rows:
            for c in row.cells:
                tcPr = c._tc.get_or_add_tcPr(); tcW = tcPr.find(qn("w:tcW"))
                if tcW is None: tcW = OxmlElement("w:tcW"); tcPr.append(tcW)
                tcW.set(qn("w:type"), "auto"); tcW.set(qn("w:w"), "0")
                set_cell_borders(c)
                for p in c.paragraphs:
                    p.paragraph_format.space_after = Pt(0); p.paragraph_format.space_before = Pt(0)
                    for r in p.runs: r.font.size = Pt(9)
        for c in t.rows[0].cells:
            for p in c.paragraphs:
                for r in p.runs: r.bold = True
        if i < len(specs) and specs[i]:
            merge_header(t, specs[i])
    # 본문 서식
    seen = False
    for p in doc.paragraphs:
        st = (p.style.name or "")
        if st.startswith("Heading 1"):
            # 장 제목 앞 페이지 나누기(첫 장 제외)
            if seen:
                run = p.runs[0] if p.runs else p.add_run("")
                br = OxmlElement("w:br"); br.set(qn("w:type"), "page"); run._r.insert(0, br)
            p.paragraph_format.space_before = Pt(12); p.paragraph_format.space_after = Pt(6)
        elif st.startswith("Heading"):
            p.paragraph_format.space_before = Pt(10); p.paragraph_format.space_after = Pt(4)
        elif is_body(p):
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.first_line_indent = Pt(10)
            p.paragraph_format.space_after = Pt(6)
        else:
            p.paragraph_format.space_after = Pt(6)
        if p.text.strip(): seen = True
    doc.save(str(docx_path))


def table_specs(md_text: str) -> list[str]:
    """표마다(파이프 표 순서대로) 바로 앞 5줄 안의 `<!-- Word 변환 지침: … -->` 주석을 찾아 돌려준다."""
    lines = md_text.splitlines(); specs = []; i = 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|\s*-", lines[i + 1]):
            spec = ""
            for j in range(max(0, i - 6), i):
                m = re.search(r"<!--\s*Word 변환 지침\s*[:：]?\s*(.*?)-->", lines[j])
                if m: spec = m.group(1).strip()
            specs.append(spec)
            while i < len(lines) and lines[i].startswith("|"): i += 1
        else: i += 1
    return specs


def to_pdf(docx_path: Path) -> Path:
    import win32com.client  # 기본 anaconda python(pywin32)
    pdf = docx_path.with_suffix(".pdf")
    word = win32com.client.DispatchEx("Word.Application"); word.Visible = False; word.DisplayAlerts = 0
    try:
        d = word.Documents.Open(str(docx_path.resolve()), ReadOnly=True)
        try: d.ExportAsFixedFormat(str(pdf.resolve()), 17)
        finally: d.Close(False)
    finally:
        word.Quit()
    return pdf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md"); ap.add_argument("--ref", default=str(DEFAULT_REF)); ap.add_argument("--pdf", action="store_true"); ap.add_argument("--out")
    ap.add_argument("--stop-at", help="이 제목(예: '## 부록 B')부터 끝까지 빼고 변환한다 — 학술지 원고는 본문만, 부록은 온라인 부록으로")
    a = ap.parse_args()
    md = Path(a.md); out = Path(a.out) if a.out else md.with_suffix(".docx")
    text = md.read_text(encoding="utf-8")
    if a.stop_at:
        i = text.find("\n" + a.stop_at)
        if i < 0: sys.exit(f"--stop-at 제목을 찾지 못했다: {a.stop_at}")
        text = text[:i].rstrip("\n").rstrip("-").rstrip("\n") + "\n"
        import tempfile
        md = Path(tempfile.gettempdir()) / (md.stem + "_본문.md"); md.write_text(text, encoding="utf-8")
    # pandoc: 주석은 버린다. 수식은 OMML로.
    cmd = [PANDOC, str(md), "-o", str(out), "--from", "markdown+pipe_tables+tex_math_dollars", "--to", "docx"]
    if a.ref and Path(a.ref).exists(): cmd += ["--reference-doc", a.ref]
    else: print("참조 DOCX 없음 — pandoc 기본 서식", file=sys.stderr)
    subprocess.run(cmd, check=True)
    postprocess(out, table_specs(text))
    print("DOCX", out, out.stat().st_size, "bytes")
    if a.pdf:
        pdf = to_pdf(out); print("PDF", pdf, pdf.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
