"""
27_fill_wto_ita_gap.py — 2017~2019년에 포털 두 화면 모두에서 빠진 정보기술협정(ITA) 품목의 WTO 협정세율(C)을
양허관세 규정 별표 1의 다(정보기술협정 확대 대상물품)에서 읽어 채움표를 만든다.

배경(2026-09-13 발견): 관세율표·주요세율보기 화면이 2017·2018·2019년에 ITA 확대 협정 품목(85·90·84·37류 등)의 C를
싣지 않아 `tariff_rate`에 그 세 해의 C가 없다. 2016년과 2020년에는 있다. 그 결과 `fct_applied_rate`의 무협정 세율(mfn)이
기본세율로 잘못 잡혔다(무협정 원산지 실행세율 약 8%p 과대, 협정 원산지 특혜 몫 15%p 과대).

근거 자료(법령센터, 2026-09-13 내려받음, data/external/양허관세_규정_별표1/):
  시행2019-10-01_개정20191001_제30100호/별표 1의 다.xlsx — 코드마다 2017~2023년 열이 있는 연차별 세율표. 2020~2023년 열이
      포털의 그 해 C와 겹치는 코드 전부에서 일치하므로 2017~2019년 열을 그대로 쓴다.
  시행2016-12-01_개정20161201_제27651호/…(별표1의다).xls — 세율 열 하나(2016-12-01 시행 세율). 2017년 열보다 한 단계 위인지 대조.
  2017-01-01(제27760호)·2018-07-01(제28949호) 판본은 별표 3만 개정해 별표 1 파일이 없다(KC_000300E = 별표 3).

채움 대상 = 그해 tariff_code에 있고 C가 없으며 2016년이나 2020년에는 C가 있던 코드(세 해 각 822개). 전부 별표 1의 다에 있다.
  코드 행(세율이 코드 전체에 붙은 것) 741개 → 그해 열 값.
  부분 양허 코드(「- …」 세부 품목 행만 있는 것) 81개 → 2020년 포털 C와 같은 세부 행 가운데 「- 기타」 행, 없으면 값이 가장 작은 행을
      골라 그 행의 2017~2019년 값(partial_pick). 고른 행의 2021~2023년 값이 포털과 같은지로 검증한다.

산출:
  KCSTARIFF/data/fill/wto_c_ita_2017_2019.csv   (year, hs10, rate_cd, rate_txt, adval, method, note) — 공개 저장소, scripts/01이 읽는다
  research/outputs/WTO세율_ITA_채움_검증.csv         (item, key, value)
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]                  # KCSTARIFF/research
EXT = ROOT / "data" / "external" / "양허관세_규정_별표1"
A19 = EXT / "시행2019-10-01_개정20191001_제30100호" / "별표 1의 다.xlsx"
A16 = EXT / "시행2016-12-01_개정20161201_제27651호" / "세계무역기구협정 등에 의한 양허관세 규정 일부개정령안(별표1의다).xls"
DB = ROOT.parent / "data" / "processed" / "kcstariff.duckdb"
OUT_FILL = ROOT.parent / "data" / "fill" / "wto_c_ita_2017_2019.csv"
OUT_CHK = ROOT / "outputs" / "WTO세율_ITA_채움_검증.csv"
YEARS = (2017, 2018, 2019)


def cell(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    s = str(v).strip()
    return s[:-2] if re.fullmatch(r"\d+\.0", s) else s


def code3(r) -> tuple[str, str, str]:
    c0, c1, c2 = (cell(x) for x in r[:3])
    c1 = c1.zfill(2) if re.fullmatch(r"\d{1,2}", c1) else c1
    c2 = c2.zfill(4) if re.fullmatch(r"\d{1,4}", c2) else c2
    return c0, c1, c2


def parse_annex(path: Path, rate_cols: list[str]) -> pd.DataFrame:
    """코드 행과 부분 양허(「- …」) 행. 부분 행은 바로 위 코드의 hs10을 물려받는다."""
    rows, last = [], None
    for r in pd.read_excel(path, header=None, dtype=object).itertuples(index=False):
        c0, c1, c2 = code3(r)
        name = cell(r[3])
        vals = {col: pd.to_numeric(cell(r[4 + i]), errors="coerce") for i, col in enumerate(rate_cols)}
        if re.fullmatch(r"\d{4}", c0) and re.fullmatch(r"\d{2}", c1) and re.fullmatch(r"\d{4}", c2):
            last = c0 + c1 + c2
            rows.append(dict(hs10=last, name=name, partial=False, **vals))
        elif name.startswith("-") and last:
            rows.append(dict(hs10=last, name=name, partial=True, **vals))
    return pd.DataFrame(rows)


def partial_pick(g: pd.DataFrame, portal2020: float | None) -> pd.Series:
    """부분 양허 코드에서 세 해에 같이 쓸 세부 행 하나를 고른다.

    포털은 부분 양허 코드에 세부 행 가운데 하나의 세율을 C로 보이는데 어느 행인지 규칙이 일정하지 않다
    (2020년 81개 중 「- 기타」 행이면 그것, 아니면 최솟값인 것이 77개, 최댓값인 것이 4개). 그래서 2020년 포털 값과
    같은 세부 행으로 후보를 좁힌 뒤(포털 값이 없으면 전체) 「- 기타」 행, 없으면 2020년 값이 가장 작은 행(같으면 2017년 값이
    가장 작은 행)을 고른다. 같은 행의 2017~2019년 값을 쓰므로 코드마다 2020년과 이어지는 계열이 된다.
    """
    cands = g
    if portal2020 is not None and not np.isnan(portal2020):
        hit = g[np.isclose(g.y2020, portal2020, atol=0.051)]
        if len(hit):
            cands = hit
    gita = cands[cands.name.str.strip().str.match(r"^-\s*기타")]
    if len(gita):
        return gita.iloc[0]
    return cands.sort_values(["y2020", "y2017"]).iloc[0]


def main() -> None:
    chk = []
    a19 = parse_annex(A19, [f"y{y}" for y in range(2017, 2024)])
    a16 = parse_annex(A16, ["y2016"])
    full19 = a19[~a19.partial & a19.y2017.notna()]
    part19 = a19[a19.partial]
    chk += [("별표1의다 2019판", "행", len(a19)), ("별표1의다 2019판", "코드 행(세율 있음)", len(full19)),
            ("별표1의다 2019판", "부분 양허 행", len(part19)), ("별표1의다 2016판", "행", len(a16))]

    con = duckdb.connect(str(DB), read_only=True)
    c = con.sql("SELECT year, hs10, MAX(adval) AS c FROM tariff_rate WHERE rate_cd='C' AND adval IS NOT NULL GROUP BY 1, 2").df()
    code = con.sql("SELECT year, hs10 FROM tariff_code").df()
    con.close()
    cw = c.pivot(index="hs10", columns="year", values="c")

    # 1) 검증: 코드 행의 2020~2023년 열 = 포털 C
    for y in range(2020, 2024):
        m = full19.merge(c[c.year == y][["hs10", "c"]], on="hs10")
        ok = int(np.isclose(m[f"y{y}"], m.c, atol=0.051).sum())
        chk.append(("코드 행 대조", f"{y} 겹침", len(m))); chk.append(("코드 행 대조", f"{y} 일치", ok))
        assert ok == len(m), f"{y}년 코드 행 불일치 {len(m) - ok}건"
    # 2) 검증: 부분 양허 코드에서 고른 세부 행의 2020~2023년 값 = 포털 C (2020년은 고르는 데 썼으므로 2021~2023년이 검증)
    picked = {}
    for h, g in part19.groupby("hs10"):
        p20 = cw.loc[h][2020] if h in cw.index and 2020 in cw.columns else None
        picked[h] = partial_pick(g, p20)
    for y in range(2020, 2024):
        n = ok = 0
        for h, row in picked.items():
            if h in cw.index and not np.isnan(cw.loc[h].get(y, np.nan)):
                n += 1; ok += int(abs(row[f"y{y}"] - cw.loc[h][y]) < 0.051)
        chk.append(("부분 양허 행 대조", f"{y} 겹침", n)); chk.append(("부분 양허 행 대조", f"{y} 일치", ok))
        print(f"부분 양허 행 {y}: {ok}/{n}")
    # 3) 검증: 2016판 세율이 2017년 열보다 한 단계(2017-2018 차) 위인 코드 수
    m = full19.merge(a16[~a16.partial][["hs10", "y2016"]], on="hs10")
    step = (m.y2017 - m.y2018)
    staged = m[step > 0]
    one_up = int(np.isclose(staged.y2016 - staged.y2017, step[step > 0], atol=0.01).sum())
    chk += [("2016판 대조", "단계 인하 코드", len(staged)), ("2016판 대조", "2017년보다 한 단계 위", one_up)]

    # 4) 채움표
    rows = []
    for y in YEARS:
        cy = code[code.year == y].hs10
        has = set(c[c.year == y].hs10)
        ever = set(c[c.year == 2016].hs10) | set(c[c.year == 2020].hs10)
        gap = cy[~cy.isin(has) & cy.isin(ever)]
        chk.append(("채움 대상", f"{y} 코드", len(gap)))
        col = f"y{y}"
        fmap = full19.set_index("hs10")[col]
        for h in gap:
            if h in fmap.index:
                v, method, note = float(fmap[h]), "코드 행", ""
            elif h in picked:
                row = picked[h]
                v, method = float(row[col]), "부분 양허"
                note = row["name"].strip().replace("\n", " ")[:60]
            else:
                raise SystemExit(f"{y} {h}: 별표 1의 다에 없다")
            v = round(v, 3)
            txt = f"{v:g}%"
            rows.append(dict(year=y, hs10=h, rate_cd="C", rate_txt=txt, adval=v, method=method, note=note))
    fill = pd.DataFrame(rows).sort_values(["year", "hs10"])
    OUT_FILL.parent.mkdir(exist_ok=True)
    fill.to_csv(OUT_FILL, index=False, encoding="utf-8-sig")
    chk += [("채움표", "행", len(fill)), ("채움표", "코드 행", int((fill.method == "코드 행").sum())),
            ("채움표", "부분 양허", int((fill.method == "부분 양허").sum())), ("채움표", "0%인 행", int((fill.adval == 0).sum()))]
    pd.DataFrame(chk, columns=["item", "key", "value"]).to_csv(OUT_CHK, index=False, encoding="utf-8-sig")
    print(pd.DataFrame(chk, columns=["item", "key", "value"]).to_string(index=False))
    print("→", OUT_FILL)


if __name__ == "__main__":
    main()
