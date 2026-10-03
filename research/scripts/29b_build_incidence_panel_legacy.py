"""
29b_build_incidence_panel_legacy.py — 논문 D 초고(2026-09-14)의 코드×원산지×월 패널을 그대로 다시 만든다(2026-10-03).

논문 D가 「측정 선택의 사다리」(초고 방식에서 시작해 한 가지씩 고친 추정)의 첫 칸을 재현하려고 둔다. 분석용 패널은 29가 만든다.
초고 방식의 결함: 원산지 → 세율 열을 dim_origin_regime의 연도 단위로 정해 협정세율이 발효 해의 1월부터 붙고(한-EU 2011, 한-미 2012,
한-중·한-베트남 2015), 세율 자료에 없는 협정의 상대국(칠레·호주·RCEP의 일본 등)과 최빈국을 무협정으로, 영국을 2021년부터 무협정으로 둔다.
아래는 초고 당시의 29와 같고 산출 경로만 다르다.

fact_trade의 수입 행 전부(2007.01~2026.07, 원산지×월×HS10, 금액·중량)에 그 원산지가 그 달에 받는 실행세율(28의 월 세율)을 붙인다.
원산지 → 세율 열의 대응은 dim_origin_regime(협정·적용 연도)에서 만든다. FTA 열은 02가 이미 무협정·APTA·아세안 가운데 낮은 쪽으로
정해 두었으므로(applied_cn = min(FTA, APTA) 등), 원산지마다 열 하나면 된다. 협정이 없는 원산지는 mfn.
개정을 건너 잇는 코드(hs2022)는 dim_hs10_to_2022(chain)의 최빈 승계(mode)다. 연계가 없으면 원 코드를 둔다.

산출: outputs/panel_incidence_v0/year=YYYY/*.parquet (yyyymm, year, stat_cd, hs10, hs2022, rate_col, imp_dlr, imp_wgt, uv, tau, mfn,
      rate_undetermined, has_W1, hs2)  — uv = imp_dlr/imp_wgt(달러/kg), tau·mfn은 %.
      outputs/패널_귀착_요약_v0.csv (행수·원산지군별 몫·세율 결측)
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
KCSDB2 = Path(os.environ.get("KCSDB2_ROOT", r"C:\Work\Projects\KCSDB2"))
KCS = KCSDB2 / "data" / "processed" / "kcsdb.duckdb"
TARIFF = ROOT.parent / "data" / "processed" / "kcstariff.duckdb"
OUT = ROOT / "outputs"
MONTHLY = OUT / "fct_applied_rate_monthly.parquet"
PAN = OUT / "panel_incidence_v0"
REGIME_COL = {"FCN1": "cn", "FEU1": "eu", "FUS1": "us", "FAS1": "asean", "FIN1": "in", "FVN1": "vn", "FCA1": "ca",
              "E1": "apta", "E2": "apta_bd", "E3": "apta_la"}


def origin_map(con) -> pd.DataFrame:
    """(stat_cd, from_year, to_year, rate_col). 한 원산지에 협정이 여럿이면 FTA 열을 쓴다(그 열이 이미 낮은 쪽을 담는다)."""
    o = con.sql("SELECT stat_cd, regime, from_year, to_year FROM tr.dim_origin_regime").df()
    o["col"] = o.regime.map(REGIME_COL)
    o["pri"] = o.regime.str.startswith("F").astype(int)
    rows = []
    for cd, g in o.groupby("stat_cd"):
        # 연도마다 우선순위가 가장 높은 협정 열
        for y in range(2007, 2027):
            gy = g[(g.from_year <= y) & (y <= g.to_year)]
            if len(gy):
                col = gy.sort_values("pri", ascending=False).col.iloc[0]
                if cd == "LA":
                    col = "la"
                rows.append((cd, y, col))
    return pd.DataFrame(rows, columns=["stat_cd", "year", "rate_col"])


def main() -> None:
    con = duckdb.connect()
    con.execute(f"ATTACH '{KCS.as_posix()}' AS s (READ_ONLY)")
    con.execute(f"ATTACH '{TARIFF.as_posix()}' AS tr (READ_ONLY)")
    om = origin_map(con)
    con.register("om", om)
    link = con.sql("SELECT hs_past, past_version, hs2022, weight FROM s.dim_hs10_to_2022 WHERE method='chain'").df()
    link = link.sort_values("weight", ascending=False).drop_duplicates(["hs_past", "past_version"])[["hs_past", "past_version", "hs2022"]]
    con.register("lk", link)
    cols = sorted(set(REGIME_COL.values()) | {"la"})
    tau_expr = "CASE r.rate_col " + " ".join(f"WHEN '{c}' THEN m.applied_{c}" for c in cols) + " ELSE m.mfn END"
    if PAN.exists():
        shutil.rmtree(PAN)
    PAN.mkdir(parents=True)
    q = f"""
    COPY (
      WITH f AS (
        SELECT yyyymm, yyyymm//100 AS year, stat_cd, hs10, imp_dlr, imp_wgt,
               CASE WHEN yyyymm//100 <= 2011 THEN '2007' WHEN yyyymm//100 <= 2016 THEN '2012' WHEN yyyymm//100 <= 2021 THEN '2017' ELSE '2022' END AS past_version
        FROM s.fact_trade WHERE imp_dlr > 0)
      SELECT f.yyyymm, f.year, f.stat_cd, f.hs10,
             CASE WHEN f.past_version = '2022' THEN f.hs10 ELSE COALESCE(lk.hs2022, f.hs10) END AS hs2022,
             COALESCE(r.rate_col, 'mfn') AS rate_col,
             f.imp_dlr, f.imp_wgt, CASE WHEN f.imp_wgt > 0 THEN f.imp_dlr::DOUBLE / f.imp_wgt ELSE NULL END AS uv,
             {tau_expr} AS tau, m.mfn, m.rate_undetermined, m.has_W1, substr(f.hs10, 1, 2) AS hs2
      FROM f
      LEFT JOIN om r ON r.stat_cd = f.stat_cd AND r.year = f.year
      LEFT JOIN read_parquet('{MONTHLY.as_posix()}') m ON m.yyyymm = f.yyyymm AND m.hs10 = f.hs10
      LEFT JOIN lk ON lk.hs_past = f.hs10 AND lk.past_version = f.past_version
    ) TO '{PAN.as_posix()}' (FORMAT PARQUET, PARTITION_BY (year), OVERWRITE_OR_IGNORE)"""
    con.execute(q)
    p = f"read_parquet('{PAN.as_posix()}/*/*.parquet', hive_partitioning=true)"
    summ = con.sql(f"""
      SELECT 'rows' AS item, '' AS key, count(*)::DOUBLE AS value FROM {p}
      UNION ALL SELECT 'codes', '', count(DISTINCT hs10) FROM {p}
      UNION ALL SELECT 'origins', '', count(DISTINCT stat_cd) FROM {p}
      UNION ALL SELECT 'tau missing pct', '', 100.0*sum((tau IS NULL)::INT)/count(*) FROM {p}
      UNION ALL SELECT 'tau missing value pct', '', 100.0*sum(imp_dlr*(tau IS NULL)::INT)/sum(imp_dlr) FROM {p}
      UNION ALL SELECT 'uv missing pct', '', 100.0*sum((uv IS NULL)::INT)/count(*) FROM {p}
      UNION ALL SELECT 'value share 2025', rate_col, 100.0*sum(imp_dlr)/(SELECT sum(imp_dlr) FROM {p} WHERE year=2025) FROM {p} WHERE year=2025 GROUP BY rate_col
      UNION ALL SELECT 'hs2022 changed pct (pre-2022)', '', 100.0*sum((hs2022<>hs10)::INT)/count(*) FROM {p} WHERE year<2022
    """).df()
    summ.to_csv(OUT / "패널_귀착_요약_v0.csv", index=False, encoding="utf-8-sig")
    print(summ.to_string(index=False))
    print("→", PAN)


if __name__ == "__main__":
    main()
