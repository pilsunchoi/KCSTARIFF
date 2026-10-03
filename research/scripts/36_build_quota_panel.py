"""
36_build_quota_panel.py — 할당관세 귀착 연구의 코드×원산지×월 단가 패널(2026-10-03).

입력: outputs/panel_incidence/(scripts/29: 수입 행 전부, 원산지×월 세율 열 rate_col, 단가 uv, hs2022),
      outputs/fct_applied_rate_monthly.parquet(scripts/28: 달 1일의 협정·APTA 세율 r_*),
      outputs/할당관세_처치_월.parquet(scripts/35: 할당관세 적용 날짜를 반영한 그달 무협정 세율 mfn_month 등).
산출: outputs/panel_quota/year=YYYY/*.parquet — 2007~2026년에 한 번이라도 할당관세가 지정된 코드(865개)의 수입 행.
  yyyymm, year, stat_cd, hs10, hs2022, rate_col, imp_dlr, imp_wgt, uv,
  role      — treated(무협정 원산지: 할당관세가 세율을 바꾼다), control(협정·APTA 세율이 그달 0 — 할당관세의 영향이 없다),
              pref_pos(협정·APTA 세율이 0보다 큼 — 할당관세가 그보다 낮으면 영향을 받는다), excl(29가 뺀 원산지×월)
  pref      — 그 원산지가 받는 협정·APTA 세율(29의 대응과 같다: 중국·인도는 FTA와 APTA, 베트남은 FTA와 아세안 중 낮은 쪽)
  tau       — 그 원산지가 그달 실제로 받는 실행세율(%): treated는 mfn_month, 협정 원산지는 min(pref, mfn_month), excl은 NULL
  tau_noquota — 할당관세가 없었다면 받았을 세율(mfn_month 대신 mfn_noquota)
  d_quota   — tau_noquota − tau (그 원산지에 대한 할당관세 인하 폭, %p)
  p3_days, p3_rate, p1_days, p1_rate, quota_cut, p1_cut, p3_on, p3_start, p3_end, n_fta0 — 처치 월 표(35)에서
  tau_old   — 29 패널의 tau(할당관세를 한 해 전부에 붙인 옛 값, 비교용)
      outputs/패널_할당_요약.csv — 연도별 행수·코드·역할별 수입 몫, 처치·대조가 함께 있는 코드×월 수.
"""

import os
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
PAN_IN = OUT / "panel_incidence"
PAN = OUT / "panel_quota"
MONTHLY = OUT / "fct_applied_rate_monthly.parquet"
TREAT = OUT / "할당관세_처치_월.parquet"

# scripts/29와 같은 대응(원산지 세율 열 → 협정·APTA 세율 열)
PREF = {"cn": ["r_FCN1", "r_E1"], "in": ["r_FIN1", "r_E1"], "eu": ["r_FEU1"], "us": ["r_FUS1"], "ca": ["r_FCA1"], "asean": ["r_FAS1"],
        "vn": ["r_FVN1", "r_FAS1"], "apta": ["r_E1"], "apta_bd": ["r_E2"], "la": ["r_FAS1", "r_E3"]}


def main() -> None:
    con = duckdb.connect()
    pref = "CASE p.rate_col " + " ".join(
        f"WHEN '{c}' THEN LEAST(" + ", ".join(f"COALESCE(m.{x}, 1e9)" for x in v) + ")" for c, v in PREF.items()) + " ELSE NULL END"
    con.execute(f"""
      CREATE TEMP TABLE q AS
      WITH p AS (SELECT * FROM read_parquet('{PAN_IN.as_posix()}/**/*.parquet', hive_partitioning=1)
                 WHERE hs10 IN (SELECT DISTINCT hs10 FROM read_parquet('{TREAT.as_posix()}'))),
      j AS (
        SELECT p.yyyymm, p.yyyymm // 100 AS year, p.stat_cd, p.hs10, p.hs2022, p.rate_col, p.imp_dlr, p.imp_wgt, p.uv, p.tau AS tau_old,
               {pref} AS pref0, t.mfn_month, t.mfn_noquota, t.p3_days, t.p3_rate, t.p1_days, t.p1_rate, t.quota_cut, t.p1_cut,
               t.p3_on, t.p3_start, t.p3_end, t.n_fta0
        FROM p
        LEFT JOIN read_parquet('{MONTHLY.as_posix()}') m ON m.hs10 = p.hs10 AND m.yyyymm = p.yyyymm
        LEFT JOIN read_parquet('{TREAT.as_posix()}') t ON t.hs10 = p.hs10 AND t.yyyymm = p.yyyymm)
      SELECT * EXCLUDE (pref0),
             CASE WHEN pref0 >= 1e8 THEN NULL ELSE pref0 END AS pref,
             CASE WHEN rate_col = 'excl' THEN 'excl' WHEN rate_col = 'mfn' THEN 'treated'
                  WHEN pref0 = 0 THEN 'control' ELSE 'pref_pos' END AS role,
             CASE WHEN rate_col = 'excl' THEN NULL WHEN rate_col = 'mfn' THEN mfn_month
                  ELSE LEAST(pref0, mfn_month) END AS tau,
             CASE WHEN rate_col = 'excl' THEN NULL WHEN rate_col = 'mfn' THEN mfn_noquota
                  ELSE LEAST(pref0, mfn_noquota) END AS tau_noquota
      FROM j""")
    con.execute("ALTER TABLE q ADD COLUMN d_quota DOUBLE; UPDATE q SET d_quota = tau_noquota - tau")
    if PAN.exists():
        shutil.rmtree(PAN)
    con.execute(f"COPY (SELECT * FROM q ORDER BY yyyymm, hs10, stat_cd) TO '{PAN.as_posix()}' (FORMAT PARQUET, PARTITION_BY (year))")
    s = con.execute("""
      WITH r AS (SELECT year, role, sum(imp_dlr) v FROM q GROUP BY 1, 2),
      t AS (SELECT year, sum(v) tot FROM r GROUP BY 1),
      cm AS (SELECT year, hs10, yyyymm, bool_or(role='treated') tr, bool_or(role='control') ct, any_value(quota_cut) qc FROM q GROUP BY 1, 2, 3)
      SELECT t.year,
             (SELECT count(*) FROM q WHERE q.year = t.year) AS rows_,
             (SELECT count(DISTINCT hs10) FROM q WHERE q.year = t.year) AS codes,
             round(100 * (SELECT v FROM r WHERE r.year = t.year AND role = 'treated') / tot, 1) AS treated_pct,
             round(100 * (SELECT v FROM r WHERE r.year = t.year AND role = 'control') / tot, 1) AS control_pct,
             round(100 * (SELECT v FROM r WHERE r.year = t.year AND role = 'pref_pos') / tot, 1) AS pref_pos_pct,
             round(100 * (SELECT v FROM r WHERE r.year = t.year AND role = 'excl') / tot, 1) AS excl_pct,
             (SELECT count(*) FROM cm WHERE cm.year = t.year AND tr AND ct) AS cells_both,
             (SELECT count(*) FROM cm WHERE cm.year = t.year AND tr AND ct AND qc > 1e-9) AS cells_both_cut
      FROM t ORDER BY t.year""").df()
    s.to_csv(OUT / "패널_할당_요약.csv", index=False, encoding="utf-8-sig")
    print(s.to_string(index=False))
    tot = con.execute("SELECT count(*), count(DISTINCT hs10), sum(CASE WHEN abs(coalesce(tau,0)-coalesce(tau_old,0))>1e-9 THEN 1 ELSE 0 END), "
                      "sum(CASE WHEN d_quota>1e-9 THEN 1 ELSE 0 END) FROM q").fetchone()
    print(f"패널 {tot[0]:,}행, 코드 {tot[1]}, 29 패널과 tau가 다른 행 {tot[2]:,}, 할당관세 인하가 있는 행 {tot[3]:,} → {PAN}")


if __name__ == "__main__":
    main()
