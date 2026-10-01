"""
19_extend_applied_rate.py — 코드 쌍에 든 코드에 대해 품목 상세에서 받은 그 밖 FTA 세율까지 넣어
원산지(ISO2)별 실행세율을 만든다(2012~2026). 규칙은 15와 같다: 협정세율(선택1)은 무협정 세율(mfn)보다
낮을 때만 적용하고, 한 원산지에 협정이 여럿이면(베트남: 한-베·한-아세안·RCEP) 가장 낮은 것.
선택2 이상·추천 세율은 조건부라 표시만 한다(`n_alt`). 최빈국 특혜(R)·북한산(U)은 원산지 목록 밖이라 뺀다.

입력: outputs/품목상세_세율_2012_2026.csv, kcstariff.duckdb fct_applied_rate
산출: outputs/실행세율_원산지별_쌍코드_2012_2026.csv (year, hs10, stat_cd, regime, applied_jan, applied_last, mfn, n_alt)
      outputs/실행세율_원산지별_검증.csv (일곱 상대 세율의 두 출처 대조)
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]                      # KCSTARIFF/research
TARIFF = ROOT.parent / "data" / "processed" / "kcstariff.duckdb"
OUT = ROOT / "outputs"
import os
KCS = Path(os.environ.get("KCSDB2_ROOT", r"C:\Work\Projects\KCSDB2")) / "data" / "processed" / "kcsdb.duckdb"   # 무역통계(읽기 전용)

EU27 = ["AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"]
ASEAN = ["BN", "KH", "ID", "LA", "MY", "MM", "PH", "SG", "TH", "VN"]
# 구분기호(선택1) → 적용 원산지. 발효 전 연도에는 상세 화면에 기호가 없으므로 연도 조건은 두지 않는다.
REGIME = {
    "FCN1": ["CN"], "FRCCN1": ["CN"], "FEU1": EU27, "FUS1": ["US"], "FCA1": ["CA"], "FIN1": ["IN"], "FVN1": ["VN"],
    "FAS1": ASEAN, "FRCAS1": ASEAN, "FAU1": ["AU"], "FRCAU1": ["AU"], "FNZ1": ["NZ"], "FRCNZ1": ["NZ"], "FRCJP1": ["JP"],
    "FCL1": ["CL"], "FPE1": ["PE"], "FCO1": ["CO"], "FTR1": ["TR"], "FGB1": ["GB"], "FIL1": ["IL"], "FKH1": ["KH"],
    "FPH1": ["PH"], "FSG1": ["SG"], "FID1": ["ID"], "FAE1": ["AE"], "FEF1": ["CH", "NO", "IS", "LI"],
    "FCECR1": ["CR"], "FCEHN1": ["HN"], "FCENI1": ["NI"], "FCEPA1": ["PA"], "FCESV1": ["SV"],
    "E1": ["CN", "IN", "LK", "MN"], "E2": ["BD"], "E3": ["LA"],
}
SEVEN = {"FCN1", "FEU1", "FUS1", "FAS1", "FIN1", "FVN1", "FCA1"}


def import_share_by_regime(year: int = 2025) -> None:
    """그해 수입액에서 FTA 일곱 상대·그 밖 협정 상대(일본 따로)·무협정 원산지의 몫(%). outputs/수입몫_원산지군_<year>.csv"""
    seven = set(["CN", "US", "CA", "IN", "VN"] + EU27 + ASEAN)
    other = set(sum([v for k, v in REGIME.items() if k not in SEVEN and not k.startswith("E")], [])) - seven
    con = duckdb.connect(); con.execute(f"ATTACH '{KCS.as_posix()}' AS s (READ_ONLY)")
    imp = con.sql(f"SELECT stat_cd, sum(imp_dlr) v FROM s.fact_trade WHERE yyyymm BETWEEN {year}01 AND {year}12 GROUP BY 1").df(); con.close()
    tot = imp.v.sum()
    grp = np.where(imp.stat_cd.isin(seven), "일곱 상대", np.where(imp.stat_cd.isin(other), "그 밖 협정", "무협정"))
    out = imp.assign(grp=grp).groupby("grp").v.sum().reindex(["일곱 상대", "그 밖 협정", "무협정"]).fillna(0)
    out = pd.concat([out, pd.Series({"일본": imp[imp.stat_cd == "JP"].v.sum()})])
    t = (100 * out / tot).round(1).rename("share_pct").reset_index().rename(columns={"index": "group"}); t["year"] = year
    t.to_csv(OUT / f"수입몫_원산지군_{year}.csv", index=False, encoding="utf-8-sig")
    print(f"{year}년 수입 몫(%):", t.set_index("group").share_pct.to_dict())


def main() -> None:
    d = pd.read_csv(OUT / "품목상세_세율_2012_2026.csv", dtype={"hs10": str})
    con = duckdb.connect()
    con.execute(f"ATTACH '{TARIFF.as_posix()}' AS tr (READ_ONLY)")
    base = con.sql("SELECT year, hs10, mfn, mfn_jan, j_FCN1, j_FEU1, j_FUS1, j_FAS1, j_FIN1, j_FVN1, j_FCA1 FROM tr.fct_applied_rate WHERE year>=2012").df()
    con.close()
    codes = sorted(d.hs10.unique())
    base = base[base.hs10.isin(codes)]
    # 검증: 일곱 상대의 1월 1일 세율이 두 출처(주요세율보기 대 품목 상세)에서 같은가
    chk = d[d.rate_cd.isin(SEVEN)].merge(base, on=["year", "hs10"], how="inner")
    chk["main_src"] = [r[f"j_{c}"] for c, r in zip(chk.rate_cd, chk.to_dict("records"))]
    chk["diff"] = (chk.adval_first - chk.main_src).abs()
    bad = chk[(chk["diff"] > 0.05) | chk.main_src.isna()]
    bad[["year", "hs10", "rate_cd", "rate_txt", "adval_first", "main_src"]].to_csv(OUT / "실행세율_원산지별_검증.csv", index=False, encoding="utf-8-sig")
    print(f"일곱 상대 대조: {len(chk):,}행 중 어긋남 {len(bad):,} ({100*len(bad)/max(len(chk),1):.2f}%)")
    pd.DataFrame([("일곱 상대 대조 행", len(chk)), ("일곱 상대 어긋남", len(bad))], columns=["item", "value"]).to_csv(OUT / "실행세율_원산지별_검증_요약.csv", index=False, encoding="utf-8-sig")
    import_share_by_regime()

    # 원산지별 적용
    sel = d[d.rate_cd.isin(REGIME) & d.adval_first.notna()]
    alt = d[d.rate_cd.str.match(r"^F[A-Z]+[2-9]$|^F[A-Z]+1[0-9]$|^FEFIS$|^FCE[A-Z]{2}7$")].groupby(["year", "hs10"]).size().rename("n_alt")
    rows = []
    for (y, h), g in sel.groupby(["year", "hs10"]):
        b = base[(base.year == y) & (base.hs10 == h)]
        if b.empty or pd.isna(b.mfn.iloc[0]):
            continue
        mfn, mfn_jan = float(b.mfn.iloc[0]), float(b.mfn_jan.iloc[0])
        per = {}
        for r in g.itertuples(index=False):
            for o in REGIME[r.rate_cd]:
                per.setdefault(o, []).append((r.rate_cd, r.adval_first, r.adval_last))
        for o, lst in per.items():
            jan = min([mfn_jan] + [a for _, a, _ in lst if pd.notna(a)])
            last = min([mfn] + [a for _, _, a in lst if pd.notna(a)])
            used = min(lst, key=lambda x: x[1] if pd.notna(x[1]) else np.inf)
            rows.append(dict(year=y, hs10=h, stat_cd=o, regime=used[0] if used[1] < mfn_jan else "MFN", applied_jan=jan, applied_last=last, mfn=mfn))
    t = pd.DataFrame(rows).merge(alt, on=["year", "hs10"], how="left")
    t["n_alt"] = t.n_alt.fillna(0).astype(int)
    t.to_csv(OUT / "실행세율_원산지별_쌍코드_2012_2026.csv", index=False, encoding="utf-8-sig")
    print(f"원산지별 실행세율: {len(t):,}행, 코드 {t.hs10.nunique()}, 원산지 {t.stat_cd.nunique()}, 협정 적용 몫 {100*(t.regime!='MFN').mean():.1f}%")
    print("규정 분포:", t.regime.value_counts().head(12).to_dict())


if __name__ == "__main__":
    main()
