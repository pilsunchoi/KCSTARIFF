"""
28_build_monthly_applied_rate.py — 코드×월 실행세율(논문 D 1단계, 계획서 IV.1).

`fct_applied_rate`는 연 단위(유효 일수 가중)라 월 분석에 못 쓴다. 여기서는 `tariff_rate`의 적용 기간(valid_from·valid_to)으로
달마다 그 달 1일에 유효한 세율을 고르고, scripts/02와 같은 규칙(관세법 제50조·FTA 특례법 제5조)을 월 단위로 적용한다.
규칙은 바꾸지 않는다 — 02의 build()를 그대로 옮기되 입력이 연 가중 평균이 아니라 달 1일 값이다.

산출: outputs/fct_applied_rate_monthly.parquet
  yyyymm, hs10, mfn, mfn_regime, applied_cn/eu/us/asean/in/vn/ca/apta/apta_bd/apta_la/la, has_W1, has_P1, has_I, has_T1, has_T2,
  rate_undetermined, undetermined_reason, r_A, r_C, r_W2, r_L, r_P3 (원자료 세율 몇 개는 점검용)
검증(outputs/월세율_검증.csv): 1월의 mfn·applied_*가 fct_applied_rate의 mfn_jan·j_*와 같은가(연중 구간이 하나인 코드에서는 연 세율과도 같아야 한다).
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]                      # KCSTARIFF/research
TARIFF = ROOT.parent / "data" / "processed" / "kcstariff.duckdb"
OUT = ROOT / "outputs"
FTA = {"FCN1": "cn", "FEU1": "eu", "FUS1": "us", "FAS1": "asean", "FIN1": "in", "FVN1": "vn", "FCA1": "ca"}
CODES = ["A", "C", "F", "L", "P3", "W2", "W1", "E1", "E2", "E3", "I", "T1", "T2", "P1", "D", "G1", "G2"] + list(FTA)


def monthly_wide() -> pd.DataFrame:
    """달 1일에 유효한 세율을 (yyyymm, hs10) × 구분으로 편다. 기간이 없는 행(관세율표 화면)은 그해 전체."""
    con = duckdb.connect()
    con.execute(f"ATTACH '{TARIFF.as_posix()}' AS tr (READ_ONLY)")
    cols = ", ".join(f"MAX(CASE WHEN rate_cd='{c}' THEN adval END) AS r_{c}" for c in CODES)
    specs = ", ".join(f"MAX(CASE WHEN rate_cd='{c}' THEN specific END) AS spec_{c}" for c in ["A", "C", "W2"])
    has = ", ".join(f"BOOL_OR(rate_cd='{c}') AS has_{c}" for c in ["I", "T1", "T2", "P1", "W1", "D", "G1", "G2"])
    q = f"""
    WITH m AS (SELECT y AS year, y*100+mo AS yyyymm, make_date(y, mo, 1) AS d1
               FROM range(2007, 2027) t(y), range(1, 13) u(mo)),
         r AS (SELECT year, hs10, rate_cd, adval, specific,
                      COALESCE(valid_from, make_date(year, 1, 1)) AS vf, COALESCE(valid_to, make_date(year, 12, 31)) AS vt
               FROM tr.tariff_rate)
    SELECT m.yyyymm, m.year, r.hs10, {cols}, {specs}, {has}
    FROM r JOIN m ON m.year = r.year AND m.d1 BETWEEN r.vf AND r.vt
    GROUP BY 1, 2, 3"""
    t = con.sql(q).df()
    con.close()
    return t


def apply_rules(t: pd.DataFrame) -> pd.DataFrame:
    """scripts/02 build()의 규칙을 월 값에 적용한다(연 가중 r_* 대신 달 1일 값)."""
    base = t.r_A
    domestic = t.r_P3.where(t.r_P3.notna(), t.r_L.where(t.r_L.notna(), base))
    regime = np.where(t.r_P3.notna(), "P3", np.where(t.r_L.notna(), "L", "A"))
    tier2 = t[["r_C", "r_F"]].min(axis=1)
    use2 = tier2.notna() & (domestic.isna() | (tier2 < domestic))
    mfn = domestic.where(~use2, tier2)
    regime = np.where(use2, np.where(t.r_C.notna() & (t.r_C <= t.r_F.fillna(np.inf)), "C", "F"), regime)
    usew = t.r_W2.notna() & t.r_P3.isna()
    mfn = mfn.where(~usew, t.r_W2)
    regime = np.where(usew, "W2", regime)
    t["mfn"] = mfn
    t["mfn_regime"] = regime
    for cd, name in FTA.items():
        r = t[f"r_{cd}"]
        t[f"applied_{name}"] = np.where(r.notna() & (r < t.mfn), r, t.mfn)
    for cd, name in [("E1", "apta"), ("E2", "apta_bd"), ("E3", "apta_la")]:
        r = t[f"r_{cd}"]
        t[f"applied_{name}"] = np.where(r.notna() & (r < t.mfn), r, t.mfn)
    t["applied_cn"] = np.minimum(t.applied_cn, t.applied_apta)
    t["applied_in"] = np.minimum(t.applied_in, t.applied_apta)
    t["applied_vn"] = np.minimum(t.applied_vn, t.applied_asean)
    t["applied_la"] = np.minimum(t.applied_asean, t.applied_apta_la)
    spec_used = np.where(t.mfn_regime == "W2", t.spec_W2, np.where(t.mfn_regime == "C", t.spec_C, np.where(t.mfn_regime == "A", t.spec_A, np.nan)))
    spec_used = np.where(spec_used > 0, spec_used, np.nan)
    t["floor_won_kg"] = np.where((t.mfn > 0) & pd.notna(spec_used), spec_used / (t.mfn / 100.0), np.nan)
    t["undetermined_reason"] = ""
    t.loc[t.mfn.isna(), "undetermined_reason"] = "specific_only"
    t.loc[t.hs10 == "1211209900", "undetermined_reason"] = "two_annexes"
    t.loc[t.hs10.str.startswith("1006") & (t.year < 2015), "undetermined_reason"] = "rice_pre_tariffication"
    t["rate_undetermined"] = t.undetermined_reason != ""
    return t


def validate(t: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    con.execute(f"ATTACH '{TARIFF.as_posix()}' AS tr (READ_ONLY)")
    a = con.sql("SELECT year, hs10, mfn, mfn_jan, mfn_regime, rate_undetermined, "
                + ", ".join(f"applied_{n}, j_{c}" for c, n in FTA.items()) + " FROM tr.fct_applied_rate").df()
    con.close()
    jan = t[t.yyyymm % 100 == 1].merge(a, on=["year", "hs10"], suffixes=("", "_y"))
    rows = [("1월 대조 행", len(jan))]
    ok = np.isclose(jan.mfn, jan.mfn_jan, atol=1e-9) | (jan.mfn.isna() & jan.mfn_jan.isna())
    rows.append(("1월 mfn = mfn_jan", int(ok.sum())))
    rows.append(("1월 mfn ≠ mfn_jan", int((~ok).sum())))
    if (~ok).sum():
        print("mfn_jan 불일치 예:", jan.loc[~ok, ["yyyymm", "hs10", "mfn", "mfn_jan", "mfn_regime", "mfn_regime_y"]].head(8).to_string(index=False))
    # 협정세율: 1월 FTA 원세율 = j_*
    for c, n in FTA.items():
        x = jan[f"r_{c}"]; y = jan[f"j_{c}"]
        okk = np.isclose(x.fillna(-1), y.fillna(-1), atol=1e-9)
        rows.append((f"1월 {c} = j_{c}", int(okk.sum()))); rows.append((f"1월 {c} ≠ j_{c}", int((~okk).sum())))
    # 미확정 표시 일치
    rows.append(("1월 미확정 표시 일치", int((jan.rate_undetermined == jan.rate_undetermined_y).sum())))
    # 연중 변경 규모: 그해 안에서 applied_*가 달라지는 코드 수(원산지군별)
    for c, n in FTA.items():
        g = t.groupby(["year", "hs10"])[f"applied_{n}"].nunique()
        rows.append((f"연중 변경 코드-연도 {n}", int((g > 1).sum())))
    g = t.groupby(["year", "hs10"]).mfn.nunique()
    rows.append(("연중 변경 코드-연도 mfn", int((g > 1).sum())))
    return pd.DataFrame(rows, columns=["item", "value"])


def main() -> None:
    t = monthly_wide()
    print("월×코드 행:", len(t), "코드:", t.hs10.nunique(), "월:", t.yyyymm.nunique())
    t = apply_rules(t)
    keep = ["yyyymm", "year", "hs10", "mfn", "mfn_regime", "floor_won_kg", "rate_undetermined", "undetermined_reason",
            "has_W1", "has_P1", "has_I", "has_T1", "has_T2"] + [f"applied_{n}" for n in list(FTA.values()) + ["apta", "apta_bd", "apta_la", "la"]] \
           + ["r_A", "r_C", "r_W2", "r_L", "r_P3", "r_F"] + [f"r_{c}" for c in FTA]
    t = t[keep].sort_values(["yyyymm", "hs10"]).reset_index(drop=True)
    OUT.mkdir(exist_ok=True)
    t.to_parquet(OUT / "fct_applied_rate_monthly.parquet", index=False)
    v = validate(t)
    v.to_csv(OUT / "월세율_검증.csv", index=False, encoding="utf-8-sig")
    print(v.to_string(index=False))
    print("→", OUT / "fct_applied_rate_monthly.parquet")


if __name__ == "__main__":
    main()
