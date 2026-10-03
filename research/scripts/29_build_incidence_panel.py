"""
29_build_incidence_panel.py — 코드×원산지×월 수입 패널(논문 D 2단계, 계획서 II.2·VI 2단계).

fact_trade의 수입 행 전부(2007.01~2026.07, 원산지×월×HS10, 금액·중량)에 그 원산지가 그 달에 받는 실행세율(28의 월 세율)을 붙인다.
FTA 열은 02가 이미 무협정·APTA·아세안 가운데 낮은 쪽으로 정해 두었으므로(applied_cn = min(FTA, APTA) 등), 원산지마다 열 하나면 된다.
개정을 건너 잇는 코드(hs2022)는 dim_hs10_to_2022(chain)의 최빈 승계(mode)다. 연계가 없으면 원 코드를 둔다.

원산지 → 세율 열의 대응(2026-10-03 검토 반영으로 다시 만듦): 원산지×월마다 정한다.
  - 일곱 협정은 발효일 기준. 그 달 1일에 발효해 있으면 협정 열, 발효일이 달 중간이면 그 달은 'excl'(두 체제가 섞임).
    세율 DB의 협정세율 구간은 발효 해의 1월 1일부터 잡혀 있다(한-중·한-베트남 2015, 한-미 2012, 한-EU 2011). 발효 전 달은 무협정 세율.
  - 아세안은 회원국별 발효일. 2007년의 아세안 협정세율은 세율 DB에 없으므로 2007년 발효 달부터 12월까지는 'excl'.
  - 세율 DB에 없는 협정(칠레·EFTA·페루·튀르키예·호주·뉴질랜드·콜롬비아·중미·RCEP(일본)·이스라엘 등)의 상대국은 발효 달부터 'excl'.
  - 영국은 2021년부터 한-영 협정이 한-EU 양허 일정을 그대로 이어받았으므로 계속 EU 열.
  - 최빈개발도상국(관세법 제76조 특혜관세 대상, 2007~2026년에 한 번이라도 UN 최빈국 목록에 있던 나라)은 전 기간 'excl'.
  'excl'의 tau·tau_sched는 NULL이다(분석에서 빠진다).

추가 열: tau_sched = 법정 세율(기본·WTO·국제협력관세의 최솟값)과 협정·APTA 세율의 최솟값 — 할당·조정관세를 뺀 「일정 세율」(도구변수용).
        flex = 그 달 무협정 세율이 할당관세(P3)나 조정관세(L)로 정해졌는가.

산출: outputs/panel_incidence/year=YYYY/*.parquet (yyyymm, year, stat_cd, hs10, hs2022, rate_col, imp_dlr, imp_wgt, uv, tau, tau_sched, mfn,
      mfn_base, flex, rate_undetermined, has_W1, hs2)  — uv = imp_dlr/imp_wgt(달러/kg), tau·mfn은 %.
      outputs/패널_귀착_요약.csv (행수·원산지군별 몫·세율 결측), outputs/원산지_월_체제.csv (원산지×월 → 세율 열),
      outputs/panel_incidence_rates.parquet (수입이 있던 연도×원산지×옛 코드의 그해 모든 달 세율 — 연 세율의 단순 평균용, 2026-10-03)
"""
from __future__ import annotations

import os
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
KCSDB2 = Path(os.environ.get("KCSDB2_ROOT", r"C:\Work\Projects\KCSDB2"))
KCS = KCSDB2 / "data" / "processed" / "kcsdb.duckdb"
TARIFF = ROOT.parent / "data" / "processed" / "kcstariff.duckdb"
OUT = ROOT / "outputs"
MONTHLY = OUT / "fct_applied_rate_monthly.parquet"
PAN = OUT / "panel_incidence"

EU27 = "AT BE BG CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
# 일곱 협정: 원산지 → (세율 열, 한국의 적용 시작일)
SEVEN = {**{c: ("eu", date(2011, 7, 1)) for c in EU27}, "HR": ("eu", date(2013, 7, 1)), "GB": ("eu", date(2011, 7, 1)),
         "IN": ("in", date(2010, 1, 1)), "US": ("us", date(2012, 3, 15)), "CA": ("ca", date(2015, 1, 1)),
         "CN": ("cn", date(2015, 12, 20)), "VN": ("vn", date(2015, 12, 20))}
# 한-아세안 상품무역협정의 회원국별 발효일(베트남은 아세안 열을 2015-12-20까지, 그 뒤 vn 열)
ASEAN = {"SG": date(2007, 6, 1), "MY": date(2007, 6, 1), "VN": date(2007, 6, 1), "MM": date(2007, 6, 1), "ID": date(2007, 6, 1),
         "PH": date(2008, 1, 1), "BN": date(2008, 7, 1), "LA": date(2008, 10, 1), "KH": date(2008, 11, 1), "TH": date(2010, 1, 1)}
# 세율 DB에 없는 협정의 상대국과 한국의 적용 시작일 — 그 달부터 'excl'
OTHER = {"CL": date(2004, 4, 1), "SG": date(2006, 3, 2), "CH": date(2006, 9, 1), "LI": date(2006, 9, 1), "NO": date(2006, 9, 1),
         "IS": date(2006, 10, 1), "PE": date(2011, 8, 1), "TR": date(2013, 5, 1), "AU": date(2014, 12, 12), "NZ": date(2015, 12, 20),
         "CO": date(2016, 7, 15), "NI": date(2019, 10, 1), "HN": date(2019, 10, 1), "CR": date(2019, 11, 1), "SV": date(2020, 1, 1),
         "PA": date(2021, 3, 1), "JP": date(2022, 2, 1), "IL": date(2022, 12, 1), "ID": date(2023, 1, 1), "PH": date(2024, 12, 31),
         "AE": date(2026, 5, 1)}
# 싱가포르는 2006-03-02 발효한 양자 협정이 있어 아세안 열로 세율을 정할 수 없다. 인도네시아(2023 CEPA)·필리핀(2024-12-31 양자)도
# 그 발효 달부터 같다. RCEP(2022-02-01)은 일본에만 반영한다 — 중국·아세안·호주·뉴질랜드는 이미 양자 협정이 있다.
# 2007~2026년에 UN 최빈국 목록에 있던 나라(최빈국 특혜관세 대상)
LDC = ("AF AO BD BJ BF BI KH CF TD KM CD DJ ER ET GM GN GW HT KI LA LS LR MG MW ML MR MZ MM NP NE RW ST SN SL SB SO SS SD TL TG "
       "TV UG TZ VU YE ZM BT CV MV WS GQ").split()
APTA_NONFTA = {"LK": "apta", "MN": "apta", "BD": "apta_bd"}


def mstart(d: date) -> int:
    """그 날짜에 발효한 협정이 1일부터 온전히 적용되는 첫 달(yyyymm)과 발효 달이 갈린 달."""
    return d.year * 100 + d.month


def regime_table(origins) -> pd.DataFrame:
    months = [y * 100 + m for y in range(2007, 2027) for m in range(1, 13) if y * 100 + m <= 202607]
    rows = []
    for c in origins:
        for ym in months:
            col = "mfn"
            if c in LDC:
                col = "excl"
            elif c in APTA_NONFTA:
                col = APTA_NONFTA[c]
            if c in ("CN", "IN"):
                col = "apta"
            if c in ASEAN:
                d = ASEAN[c]
                if ym > mstart(d) or (ym == mstart(d) and d.day == 1):
                    col = "asean" if ym >= 200801 else "excl"
                elif ym == mstart(d):
                    col = "excl"
            if c in SEVEN:
                g, d = SEVEN[c]
                if ym > mstart(d) or (ym == mstart(d) and d.day == 1):
                    col = g
                elif ym == mstart(d):
                    col = "excl"
            if c in OTHER:
                d = OTHER[c]
                if ym >= mstart(d):
                    col = "excl"
            if c in LDC:
                col = "excl"
            rows.append((c, ym, col))
    return pd.DataFrame(rows, columns=["stat_cd", "yyyymm", "rate_col"])


def main() -> None:
    con = duckdb.connect()
    con.execute(f"ATTACH '{KCS.as_posix()}' AS s (READ_ONLY)")
    origins = [r[0] for r in con.sql("SELECT DISTINCT stat_cd FROM s.fact_trade WHERE imp_dlr > 0").fetchall()]
    rt = regime_table(origins)
    OUT.mkdir(exist_ok=True)
    rt.to_csv(OUT / "원산지_월_체제.csv", index=False, encoding="utf-8-sig")
    con.register("om", rt)
    link = con.sql("SELECT hs_past, past_version, hs2022, weight FROM s.dim_hs10_to_2022 WHERE method='chain'").df()
    link = link.sort_values("weight", ascending=False).drop_duplicates(["hs_past", "past_version"])[["hs_past", "past_version", "hs2022"]]
    con.register("lk", link)
    cols = ["cn", "eu", "us", "asean", "in", "vn", "ca", "apta", "apta_bd", "la"]
    tau_expr = "CASE r.rate_col " + " ".join(f"WHEN '{c}' THEN m.applied_{c}" for c in cols) + " WHEN 'mfn' THEN m.mfn ELSE NULL END"
    base = "LEAST(COALESCE(m.r_A, 1e9), COALESCE(m.r_C, 1e9), COALESCE(m.r_F, 1e9))"
    sched = {"cn": "m.r_FCN1, m.r_E1", "in": "m.r_FIN1, m.r_E1", "eu": "m.r_FEU1", "us": "m.r_FUS1", "ca": "m.r_FCA1", "asean": "m.r_FAS1",
             "vn": "m.r_FVN1, m.r_FAS1", "apta": "m.r_E1", "apta_bd": "m.r_E2", "la": "m.r_FAS1, m.r_E3"}
    sched_expr = ("CASE r.rate_col " + " ".join(
        f"WHEN '{c}' THEN LEAST({base}, " + ", ".join(f"COALESCE({x.strip()}, 1e9)" for x in v.split(",")) + ")" for c, v in sched.items())
        + f" WHEN 'mfn' THEN {base} ELSE NULL END")
    if PAN.exists():
        shutil.rmtree(PAN)
    PAN.mkdir(parents=True)
    q = f"""
    COPY (
      WITH f AS (
        SELECT yyyymm, yyyymm//100 AS year, stat_cd, hs10, imp_dlr, imp_wgt,
               CASE WHEN yyyymm//100 <= 2011 THEN '2007' WHEN yyyymm//100 <= 2016 THEN '2012' WHEN yyyymm//100 <= 2021 THEN '2017' ELSE '2022' END AS past_version
        FROM s.fact_trade WHERE imp_dlr > 0),
      j AS (
      SELECT f.yyyymm, f.year, f.stat_cd, f.hs10,
             CASE WHEN f.past_version = '2022' THEN f.hs10 ELSE COALESCE(lk.hs2022, f.hs10) END AS hs2022,
             COALESCE(r.rate_col, 'mfn') AS rate_col,
             f.imp_dlr, f.imp_wgt, CASE WHEN f.imp_wgt > 0 THEN f.imp_dlr::DOUBLE / f.imp_wgt ELSE NULL END AS uv,
             {tau_expr} AS tau, {sched_expr} AS tau_sched, m.mfn,
             CASE WHEN {base} < 1e8 THEN {base} END AS mfn_base, m.mfn_regime IN ('P3', 'L') AS flex,
             m.rate_undetermined, m.has_W1, substr(f.hs10, 1, 2) AS hs2
      FROM f
      LEFT JOIN om r ON r.stat_cd = f.stat_cd AND r.yyyymm = f.yyyymm
      LEFT JOIN read_parquet('{MONTHLY.as_posix()}') m ON m.yyyymm = f.yyyymm AND m.hs10 = f.hs10
      LEFT JOIN lk ON lk.hs_past = f.hs10 AND lk.past_version = f.past_version)
      SELECT * REPLACE (CASE WHEN tau_sched >= 1e8 OR tau IS NULL THEN NULL ELSE tau_sched END AS tau_sched) FROM j
    ) TO '{PAN.as_posix()}' (FORMAT PARQUET, PARTITION_BY (year), OVERWRITE_OR_IGNORE)"""
    con.execute(q)
    # 세율 달력(2026-10-03 재검토 A6): 수입이 있던 (연도, 원산지, 옛 코드)마다 그해 모든 달의 세율. 연 세율은 이 달력의 단순 평균으로
    # 만든다 — 수입액 가중 평균은 수입 시점이 세율에 반응하면 세율이 물량에 오염된다.
    con.execute(f"""
    COPY (
      WITH c AS (SELECT DISTINCT year, stat_cd, hs10, hs2022 FROM read_parquet('{PAN.as_posix()}/*/*.parquet', hive_partitioning=true)),
      j AS (
      SELECT c.year, c.stat_cd, c.hs10, c.hs2022, r.yyyymm, r.rate_col,
             {tau_expr} AS tau, {sched_expr} AS tau_sched
      FROM c
      JOIN om r ON r.stat_cd = c.stat_cd AND r.yyyymm // 100 = c.year
      LEFT JOIN read_parquet('{MONTHLY.as_posix()}') m ON m.yyyymm = r.yyyymm AND m.hs10 = c.hs10)
      SELECT * REPLACE (CASE WHEN tau_sched >= 1e8 OR tau IS NULL THEN NULL ELSE tau_sched END AS tau_sched) FROM j
    ) TO '{(OUT / "panel_incidence_rates.parquet").as_posix()}' (FORMAT PARQUET)""")
    p = f"read_parquet('{PAN.as_posix()}/*/*.parquet', hive_partitioning=true)"
    summ = con.sql(f"""
      SELECT 'rows' AS item, '' AS key, count(*)::DOUBLE AS value FROM {p}
      UNION ALL SELECT 'codes', '', count(DISTINCT hs10) FROM {p}
      UNION ALL SELECT 'origins', '', count(DISTINCT stat_cd) FROM {p}
      UNION ALL SELECT 'tau missing pct (excl 제외)', '', 100.0*sum((tau IS NULL)::INT)/count(*) FROM {p} WHERE rate_col <> 'excl'
      UNION ALL SELECT 'excl rows pct', '', 100.0*sum((rate_col='excl')::INT)/count(*) FROM {p}
      UNION ALL SELECT 'excl value pct', '', 100.0*sum(imp_dlr*(rate_col='excl')::INT)/sum(imp_dlr) FROM {p}
      UNION ALL SELECT 'uv missing pct', '', 100.0*sum((uv IS NULL)::INT)/count(*) FROM {p}
      UNION ALL SELECT 'value share 2025', rate_col, 100.0*sum(imp_dlr)/(SELECT sum(imp_dlr) FROM {p} WHERE year=2025) FROM {p} WHERE year=2025 GROUP BY rate_col
      UNION ALL SELECT 'hs2022 changed pct (pre-2022)', '', 100.0*sum((hs2022<>hs10)::INT)/count(*) FROM {p} WHERE year<2022
    """).df()
    summ.to_csv(OUT / "패널_귀착_요약.csv", index=False, encoding="utf-8-sig")
    print(summ.to_string(index=False))
    print("→", PAN)


if __name__ == "__main__":
    main()
