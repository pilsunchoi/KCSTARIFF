"""
25_parse_concession_annex.py — 세계무역기구협정 등에 의한 양허관세 규정 별표 1(가·나) XLSX → 코드별 표(자료 논문 부록 A2.2).

2026-09-12에 대화형으로 만든 outputs/양허관세_별표1_2025.csv 를 2026-09-13에 스크립트로 복원했다. 복원본은 옛 CSV와 10,222행 전부 같다
(열 12개 값 비교, 부분 양허 155·종량 대안 92·두 별표 겹침 1211209900).

입력: data/external/양허관세_규정_별표1/ 의 XLSX 둘(법령센터 ZIP 안, 2024-12-31 개정본).
  가: 열 0~4 = 호(4자리)·소호(2)·세분(4)·품명·세율. 세 칸이 다 있는 행이 10단위 코드 행이고, 품명이 「-」로 시작하는 행은 바로 위 코드의
      세부 품목에만 양허한 「부분 양허」(품명 : 세율)다. 호·소호만 있는 행은 제목이라 버린다.
  나: 열 0~6 = 앞 6자리·2·2·품명·시장접근물량·물량 이내 세율·물량 초과 세율. 뒤 두 칸이 다 있는 행이 10단위 코드 행이다.
세율 문구는 그대로 두고(rate_txt) 종가(%)·종량(원/kg)·「양자 중 고액」 여부를 따로 읽는다. 가·나 양쪽에 있는 코드는 미확정으로 표시한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "data" / "external" / "양허관세_규정_별표1"
GA = EXT / "1-1. 세계무역기구협정 등에 의한 양허관세 규정 별표 1의 가.xlsx"
NA = EXT / "1-2. 세계무역기구협정 등에 의한 양허관세 규정 별표 1의 나.xlsx"
OUT = ROOT / "outputs" / "양허관세_별표1_2025.csv"


def cell(v, code=False) -> str:
    """code=True: 코드 칸(숫자 셀 1000.0 → '1000'). 세율 칸은 숫자 셀을 '18.0' 꼴 그대로 둔다."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    s = str(v).strip()
    return s[:-2] if (code and re.fullmatch(r"\d+\.0", s)) else s


def parse_rate(txt: str):
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", txt)
    adval = float(m.group(1)) if m else (float(txt) if re.fullmatch(r"\d+(\.\d+)?", txt) else np.nan)
    m2 = re.search(r"([\d,]+(?:\.\d+)?)\s*원", txt)
    spec = float(m2.group(1).replace(",", "")) if m2 else np.nan
    return adval, spec, ("양자 중 고액" in txt)


def parse_ga() -> list[dict]:
    rows = []
    for r in pd.read_excel(GA, header=None, dtype=object).itertuples(index=False):
        c0, c1, c2 = (cell(v, code=True) for v in r[:3]); name, rate = (cell(v) for v in r[3:5])
        if re.fullmatch(r"\d{4}", c0) and re.fullmatch(r"\d{2}", c1) and re.fullmatch(r"\d{4}", c2):
            rows.append(dict(byeolpyo="1의 가", hs10=c0 + c1 + c2, name_ko=name, trq="", in_quota="", rate_txt=rate, partial=[]))
        elif name.startswith("-") and rows:
            rows[-1]["partial"].append(f"{name} : {rate}")   # 세율 칸이 비면 「품명 : 」로 남긴다(옛 산출과 같은 꼴)
    return rows


def parse_na() -> list[dict]:
    rows = []
    for r in pd.read_excel(NA, header=None, dtype=object).itertuples(index=False):
        c0, c1, c2 = (cell(v, code=True) for v in r[:3]); name, trq, inq, rate = (cell(v) for v in r[3:7])
        if re.fullmatch(r"\d{6}", c0) and re.fullmatch(r"\d{2}", c1) and re.fullmatch(r"\d{2}", c2):
            rows.append(dict(byeolpyo="1의 나", hs10=c0 + c1 + c2, name_ko=name, trq=trq, in_quota=inq, rate_txt=rate, partial=[]))
    return rows


def build() -> pd.DataFrame:
    out = []
    for d in parse_ga() + parse_na():
        adval, spec, hi = parse_rate(d["rate_txt"])
        out.append(dict(byeolpyo=d["byeolpyo"], hs10=d["hs10"], name_ko=d["name_ko"], trq=d["trq"], in_quota=d["in_quota"], rate_txt=d["rate_txt"],
                        adval=adval, specific_won_kg=spec, higher_of=hi, partial=" | ".join(d["partial"])))
    df = pd.DataFrame(out)
    both = set(df[df.byeolpyo == "1의 가"].hs10) & set(df[df.byeolpyo == "1의 나"].hs10)
    df["rate_undetermined"] = np.where(df.hs10.isin(both), "Y", "")
    df["undetermined_reason"] = np.where(df.hs10.isin(both), "별표 1의 가와 나에 모두 있어 물품 정의에 따라 세율이 갈림", "")
    return df


def main() -> None:
    df = build()
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"{OUT.name}: {len(df):,}행 {df.byeolpyo.value_counts().to_dict()}, 부분 양허 {int((df.partial != '').sum())}, 종량 대안 코드 {df[df.higher_of].hs10.nunique()}, 두 별표 겹침 {int((df.rate_undetermined == 'Y').sum())}행")


if __name__ == "__main__":
    main()
