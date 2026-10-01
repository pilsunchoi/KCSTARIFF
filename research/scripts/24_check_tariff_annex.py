"""
24_check_tariff_annex.py — 법령 대조 표본 214개의 확인(자료 논문 VI장 다섯째 검증, 2026-09-13).

입력
  data/external/관세법_별표_관세율표/관세율표_개정2022-12-31_시행2025-01-01_lsiSeq17031935.hwp
      관세법 별표 관세율표, 2025-01-01 시행 판본(별표 개정 2022-12-31). 법령센터 별표 페이지의 판본별 주소
      http://www.law.go.kr/BYL/grtFile/law0015562022123119186KC_000000E.hwp 에서 받았다(HWP 5.0, 1.3MB).
  data/external/조정관세_규정_별표/조정관세_별표_개정2024-12-31_2025년적용_flSeq147597553.pdf
      관세법 제69조에 따른 조정관세의 적용에 관한 규정 [별표] <개정 2024.12.31>, 2025년 적용.
      https://www.law.go.kr/LSW/flDownload.do?gubun=&flSeq=147597553&bylClsCd=110201
  outputs/양허관세_별표1_2025.csv (별표 1의 가·나, 2.2절), outputs/실행세율_법령대조.csv (scripts/02가 만든 표본 214개)

하는 일
  1) 관세율표 HWP의 본문 텍스트를 읽어(olefile·zlib, PARA_TEXT) 소호(호 4자리 + 소호 2자리)마다 세율을 뽑는다. 소호 아래에
     "1. …", "가. …", "1) …" 세 단계의 세부 항목이 있으면 항목마다 (라벨 경로, 세율)을 잎으로 둔다 → 관세율표_2025_소호항목_세율.csv
  2) 표본 214개 전부의 기본세율(r_A)을 그 소호의 잎 세율과 맞댄다. 소호에 세율이 하나면 그 값과, 여럿이면 표본 코드 품명에 맞는 항목의
     값과 같은지 본다(항목 라벨을 비고에 남긴다).
  3) 실행세율 규정별로 법령 값을 맞댄다 — W2는 별표 1의 나(또는 가), C는 별표 1의 가, L은 조정관세 별표(2103.90의 45%).
  4) 실행세율_법령대조.csv의 빈 열(법령_확인세율·확인_출처·비고)을 채우고 실행세율_법령대조_요약.csv를 쓴다(노트북 §1b가 읽는다).
"""
from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path

import fitz  # pymupdf
import numpy as np
import olefile
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
HWP = ROOT / "data" / "external" / "관세법_별표_관세율표" / "관세율표_개정2022-12-31_시행2025-01-01_lsiSeq17031935.hwp"
PDF = ROOT / "data" / "external" / "조정관세_규정_별표" / "조정관세_별표_개정2024-12-31_2025년적용_flSeq147597553.pdf"
SRC_A = "관세법 별표 관세율표(개정 2022-12-31, 2025-01-01 시행 판본)"
SRC_L = "관세법 제69조에 따른 조정관세의 적용에 관한 규정 별표(개정 2024-12-31, 2025년 적용)"


def hwp_text(path: Path) -> list[str]:
    ole = olefile.OleFileIO(str(path))
    compressed = bool(ole.openstream("FileHeader").read()[36] & 1)
    out = []
    for entry in sorted(ole.listdir()):
        if entry[0] != "BodyText":
            continue
        data = ole.openstream(entry).read()
        if compressed:
            data = zlib.decompress(data, -15)
        i = 0
        while i + 4 <= len(data):
            head = struct.unpack("<I", data[i:i + 4])[0]
            tag, size = head & 0x3FF, (head >> 20) & 0xFFF
            i += 4
            if size == 0xFFF:
                size = struct.unpack("<I", data[i:i + 4])[0]
                i += 4
            if tag == 67:
                out.append(data[i:i + size].decode("utf-16le", errors="ignore"))
            i += size
    lines = [re.sub(r"[\x00-\x1f]", " ", l).strip() for l in out]
    return [l for l in lines if l]


IS_RATE = re.compile(r"(\d+(\.\d+)?|무세|자유)(\s*\(.*\))?$")
L1, L2, L3 = re.compile(r"^\d+\.\s"), re.compile(r"^[가-힣]\.\s"), re.compile(r"^\d+\)\s")


def parse_leaves(lines: list[str]) -> pd.DataFrame:
    """소호마다 (라벨 경로, 세율) 잎을 뽑는다. 표의 칸이 문단 순서로 나오므로 [호, 소호, 품명, 세율 | 항목·세율의 나열] 꼴이다."""
    is_rate = lambda s: IS_RATE.fullmatch(s) is not None
    is_item = lambda s: bool(L1.match(s) or L2.match(s) or L3.match(s))
    leaves, i, n = [], 0, len(lines)
    while i < n - 1:
        if re.fullmatch(r"\d{4}", lines[i]) and re.fullmatch(r"\d{2}", lines[i + 1]):
            hs6 = lines[i] + lines[i + 1]; j = i + 2; block = []
            while j < n and not (re.fullmatch(r"\d{4}", lines[j]) and j + 1 < n and (re.fullmatch(r"\d{2}", lines[j + 1]) or not is_rate(lines[j + 1]))):
                block.append(lines[j]); j += 1
            name = block[0] if block else ""; rest = block[1:]
            if not rest and is_rate(name):
                leaves.append((hs6, "", name))
            elif rest and not any(is_item(x) for x in rest):
                r = [x for x in rest if is_rate(x)]; leaves.append((hs6, name, r[0] if r else ""))
            else:
                l1 = l2 = ""; k = 0
                while k < len(rest):
                    x = rest[k]
                    if L1.match(x): l1, l2 = x, ""
                    elif L2.match(x): l2 = x
                    if is_item(x):
                        lab = x if L1.match(x) else (l1 + " > " + x if L2.match(x) else l1 + " > " + l2 + " > " + x)
                        if k + 1 < len(rest) and is_rate(rest[k + 1]):
                            leaves.append((hs6, lab, rest[k + 1])); k += 2; continue
                    elif is_rate(x) and k == 0:
                        leaves.append((hs6, name, x))
                    k += 1
            i = j
        else:
            i += 1
    lv = pd.DataFrame(leaves, columns=["hs6", "label", "rate_txt"])
    lv["rate"] = lv.rate_txt.map(rate_num)
    return lv


def rate_num(x) -> float:
    m = re.match(r"^(\d+(\.\d+)?)", str(x))
    return float(m.group(1)) if m else (0.0 if str(x).startswith(("무세", "자유")) else np.nan)


def main() -> None:
    lines = hwp_text(HWP)
    lv = parse_leaves(lines)
    lv.to_csv(HWP.parent / "관세율표_2025_소호항목_세율.csv", index=False, encoding="utf-8-sig")
    print(f"관세율표: 소호 {lv.hs6.nunique():,}개, 세율 항목 {len(lv):,}개, 세율 결측 {int(lv.rate.isna().sum())}")

    d = pd.read_csv(OUT / "실행세율_법령대조.csv", dtype=str, keep_default_na=False)
    by = pd.read_csv(OUT / "양허관세_별표1_2025.csv", dtype={"hs10": str})
    adj = "\n".join(p.get_text() for p in fitz.open(str(PDF)))
    adj_2103 = adj[adj.find("2103"):][:600]
    assert "45%" in adj_2103 and "고추" in adj_2103, "조정관세 별표에서 2103.90 45%를 찾지 못했다"

    status_a = {}
    for r in d.itertuples():
        hs6 = r.hs10[:6]; rA = float(r.r_A); g = lv[lv.hs6 == hs6]; rates = sorted(set(g.rate.dropna()))
        hit = g[np.isclose(g.rate, rA, atol=0.01)]
        st = "일치(단일)" if len(rates) == 1 and np.isclose(rates[0], rA, atol=0.01) else ("항목 일치" if len(hit) else "불일치")
        status_a[r.hs10] = (st, " | ".join(hit.label.tolist())[:60])
    n_single = sum(1 for s, _ in status_a.values() if s == "일치(단일)"); n_item = sum(1 for s, _ in status_a.values() if s == "항목 일치")
    n_bad = sum(1 for s, _ in status_a.values() if s == "불일치")

    for i, r in d.iterrows():
        st, lab = status_a[r.hs10]; note_a = f"기본세율 {float(r.r_A):g} {st}" + (f"({lab})" if st == "항목 일치" else "")
        if r.mfn_regime == "A":
            d.at[i, "법령_확인세율"] = f"{float(r.r_A):g}"; d.at[i, "확인_출처"] = SRC_A; d.at[i, "비고"] = note_a + "(2026-09-13)"
        elif r.mfn_regime in ("W2", "C"):
            col = "r_W2" if r.mfn_regime == "W2" else "r_C"; rows = by[by.hs10 == r.hs10]
            hit = rows[np.isclose(rows.adval.astype(float), float(r[col]), atol=0.01)]
            assert len(hit), r.hs10
            d.at[i, "법령_확인세율"] = f"{float(r[col]):g}"; d.at[i, "확인_출처"] = f"양허관세 규정 별표 {hit.byeolpyo.iloc[0]}(2024-12-31 개정, 2025년 적용); " + SRC_A
            d.at[i, "비고"] = ("양허 세율 일치" if r.mfn_regime == "W2" else "WTO 협정세율 일치") + "(2026-09-13); " + note_a
        elif r.mfn_regime == "L":
            assert r.hs10.startswith("210390") and float(r.r_L) == 45.0, r.hs10
            d.at[i, "법령_확인세율"] = "45"; d.at[i, "확인_출처"] = SRC_L + "; " + SRC_A
            d.at[i, "비고"] = "조정관세 45%(2103.90 중 고추·마늘·양파·생강 함량 각 20% 이상 또는 합 40% 이상인 것) 일치; " + note_a + "(2026-09-13)"
        else:
            raise ValueError(r.mfn_regime)
    d.to_csv(OUT / "실행세율_법령대조.csv", index=False, encoding="utf-8-sig")
    vc = d.mfn_regime.value_counts()
    summ = pd.DataFrame([("표본", len(d)), ("확인", int((d.법령_확인세율 != "").sum())), ("양허 W2 일치", int(vc.get("W2", 0))), ("WTO C 일치", int(vc.get("C", 0))), ("기본세율 A 일치", int(vc.get("A", 0))), ("조정관세 L 일치", int(vc.get("L", 0))),
                         ("기본세율 단일 소호 일치", n_single), ("기본세율 세부 항목 일치", n_item), ("어긋남", n_bad), ("관세율표 소호 수", lv.hs6.nunique()), ("관세율표 세율 항목 수", len(lv))], columns=["item", "value"])
    summ.to_csv(OUT / "실행세율_법령대조_요약.csv", index=False, encoding="utf-8-sig")
    print(summ.to_string(index=False))


if __name__ == "__main__":
    main()
