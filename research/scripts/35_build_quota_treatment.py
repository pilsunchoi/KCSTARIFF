"""
35_build_quota_treatment.py — 할당관세 귀착 연구의 처치 변수를 만든다(2026-10-03).

입력: outputs/할당관세_시간표_hs10.csv(scripts/33)와 그 P1·P3 분류(scripts/34의 classify),
      ../data/quota/quota_p3_periods.csv(전량 할당 적용 구간), 세율 DB의 fct_applied_rate(연 세율 열),
      KCSDB2 fact_trade(수입액, 요약에만).
산출:
  outputs/할당관세_처치_일.parquet — hs10, date, cls(P1·P3), rate. 지정된 날만(같은 날 같은 구분이 여럿이면 P3는
      quota_p3_periods의 값, P1은 최저 세율).
  outputs/할당관세_처치_월.parquet — 2007~2026년 중 한 번이라도 할당관세가 지정된 코드(10단위 문자열 기준)의
      그해 코드×월 전부(지정이 없는 달도 둔다 — 사건연구의 앞뒤 창).
      ndays, p3_days, p3_rate(P3 적용 날의 평균), p1_days, p1_rate,
      mfn_noquota(할당관세가 없을 때의 무협정 세율: 조정·기본, WTO·국제협력이 낮으면 그것, 양허 미추천 W2 우선),
      mfn_month(그달의 무협정 세율: P3 적용 날은 P3와 WTO·국제협력 중 낮은 값, 나머지 날은 mfn_noquota, 일수 가중),
      quota_cut(= mfn_noquota − mfn_month, 그달 전량 할당이 무협정 세율을 내린 폭, %p),
      p1_cut(P1 적용 날에 추천을 받은 수입자가 얻는 인하 폭의 그달 평균, %p),
      p3_on·p3_start·p3_end(그달 P3가 하루라도 있음, 앞달에 없다가 생김, 다음 달에 사라짐 — 앞달·다음 달이 같은 코드로
      자료에 있을 때만 센다: 2007년 1월이나 코드가 새로 생긴 해의 1월에 이미 지정 중이면 시작이 아니다),
      fta0_cn·…·fta0_ca(그해 그 협정이 1월 1일부터 적용 중이고 협정세율이 0 — 할당관세의 영향을 받지 않는 대조 원산지군),
      n_fta0(그 수).
  outputs/할당관세_처치_요약.csv — 연도별 지정 코드 수, P3 시작·종료 사건 수, quota_cut 분포, 영향받은 수입액.
연 세율 열(r_L·r_A·r_C·r_F·r_W2)은 연 단위 값을 그달에 그대로 쓴다(조정·기본·WTO 세율의 연중 변경은 드물다).
원산지별 처치(무협정 원산지는 quota_cut만큼, 협정세율 0 원산지는 0)는 패널 단계에서 원산지×월 체제 표(scripts/29)와 붙인다.
"""

import importlib.util
import os
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
DB = REPO / "data" / "processed" / "kcstariff.duckdb"
KCS = Path(os.environ.get("KCSDB2_ROOT", REPO.parent / "KCSDB2")) / "data" / "processed" / "kcsdb.duckdb"
FTA = {"FCN1": "cn", "FEU1": "eu", "FUS1": "us", "FAS1": "asean", "FIN1": "in", "FVN1": "vn", "FCA1": "ca"}

spec = importlib.util.spec_from_file_location("s34", ROOT / "scripts" / "34_build_quota_p3_periods.py")
s34 = importlib.util.module_from_spec(spec); spec.loader.exec_module(s34)


def expand(df: pd.DataFrame) -> pd.DataFrame:
    """구간(valid_from~valid_to)을 날마다 한 행으로 편다."""
    vf, vt = pd.to_datetime(df.valid_from), pd.to_datetime(df.valid_to)
    n = (vt - vf).dt.days + 1
    out = df.loc[df.index.repeat(n)].copy()
    out["date"] = np.repeat(vf.values, n) + pd.to_timedelta(np.concatenate([np.arange(k) for k in n]), unit="D")
    return out


def main() -> None:
    o, _ = s34.load_classified()
    p1 = o[o.cls == "P1"].copy()
    p1["rate_v"] = [min(s34.nums(r)) if s34.nums(r) else np.nan for r in p1.rate]
    p1 = p1[p1.rate_v.notna()]
    d1 = expand(p1[["hs10", "valid_from", "valid_to", "rate_v"]]).groupby(["hs10", "date"]).rate_v.min().reset_index()
    d1["cls"] = "P1"
    p3 = pd.read_csv(REPO / "data" / "quota" / "quota_p3_periods.csv", dtype={"hs10": str})
    d3 = expand(p3[["hs10", "valid_from", "valid_to", "adval"]]).rename(columns={"adval": "rate_v"})[["hs10", "date", "rate_v"]]
    d3["cls"] = "P3"
    daily = pd.concat([d3, d1], ignore_index=True).rename(columns={"rate_v": "rate"})
    daily.to_parquet(ROOT / "outputs" / "할당관세_처치_일.parquet", index=False)

    # 코드×월 합계
    daily["yyyymm"] = daily.date.dt.year * 100 + daily.date.dt.month
    m = daily.groupby(["hs10", "yyyymm", "cls"]).agg(days=("rate", "size"), rate=("rate", "mean")).unstack("cls")
    m.columns = [f"{c[1].lower()}_{'days' if c[0] == 'days' else 'rate'}" for c in m.columns]
    m = m.reset_index()

    con = duckdb.connect(str(DB), read_only=True)
    cols = ", ".join(["year", "hs10", "r_A", "r_L", "r_C", "r_F", "r_W2"] + [f"r_{c}" for c in FTA] + [f"inforce_{v}" for v in FTA.values()])
    ar = con.execute(f"select {cols} from fct_applied_rate").df()
    con.close()
    ever = set(daily.hs10)
    ar = ar[ar.hs10.isin(ever)].copy()
    tier2 = ar[["r_C", "r_F"]].min(axis=1)
    dom = ar.r_L.where(ar.r_L.notna(), ar.r_A)
    noq = dom.where(~(tier2.notna() & (dom.isna() | (tier2 < dom))), tier2)
    ar["mfn_noquota"] = noq.where(ar.r_W2.isna(), ar.r_W2)
    ar["tier2"] = tier2
    for cd, v in FTA.items():
        ar[f"fta0_{v}"] = (ar[f"r_{cd}"] == 0) & (ar[f"inforce_{v}"] >= 1)
    ar["n_fta0"] = ar[[f"fta0_{v}" for v in FTA.values()]].sum(axis=1)

    mon = ar.loc[ar.index.repeat(12)].copy()
    mon["month"] = np.tile(np.arange(1, 13), len(ar))
    mon["yyyymm"] = mon.year * 100 + mon.month
    mon["ndays"] = pd.to_datetime(dict(year=mon.year, month=mon.month, day=1)).dt.days_in_month
    mon = mon.merge(m, on=["hs10", "yyyymm"], how="left")
    for c in ["p3_days", "p1_days"]:
        mon[c] = mon.get(c, 0).fillna(0).astype(int)
    with_q = np.where(mon.tier2.notna() & (mon.tier2 < mon.p3_rate), mon.tier2, mon.p3_rate)
    mon["mfn_month"] = np.where(mon.p3_days > 0, (mon.p3_days * with_q + (mon.ndays - mon.p3_days) * mon.mfn_noquota) / mon.ndays, mon.mfn_noquota)
    mon["quota_cut"] = mon.mfn_noquota - mon.mfn_month
    p1c = (mon.mfn_noquota - np.minimum(mon.p1_rate, mon.mfn_noquota)).clip(lower=0)
    mon["p1_cut"] = np.where(mon.p1_days > 0, p1c * mon.p1_days / mon.ndays, 0.0)
    mon = mon.sort_values(["hs10", "yyyymm"]).reset_index(drop=True)
    mon["p3_on"] = mon.p3_days > 0
    # 앞달·다음 달이 같은 코드로 자료에 있을 때만 사건으로 센다(2007년 1월, 코드가 새로 생기거나 없어지는 해는 관측 밖)
    g = mon.groupby("hs10")
    ym = mon.year * 12 + mon.month
    prev_ok = g.yyyymm.shift(1).notna() & ((ym - (g.year.shift(1) * 12 + g.month.shift(1))) == 1)
    next_ok = g.yyyymm.shift(-1).notna() & (((g.year.shift(-1) * 12 + g.month.shift(-1)) - ym) == 1)
    prev = g.p3_on.shift(1, fill_value=False).astype(bool)
    nxt = g.p3_on.shift(-1, fill_value=False).astype(bool)
    mon["p3_start"] = mon.p3_on & ~prev & prev_ok
    mon["p3_end"] = mon.p3_on & ~nxt & next_ok
    keep = ["hs10", "year", "month", "yyyymm", "ndays", "p3_days", "p3_rate", "p1_days", "p1_rate", "mfn_noquota", "mfn_month",
            "quota_cut", "p1_cut", "p3_on", "p3_start", "p3_end"] + [f"fta0_{v}" for v in FTA.values()] + ["n_fta0"]
    mon = mon[keep]
    mon.to_parquet(ROOT / "outputs" / "할당관세_처치_월.parquet", index=False)

    # 요약
    summ = mon.groupby("year").agg(codes=("hs10", "nunique"), p3_codes=("p3_on", lambda x: mon.loc[x.index][x].hs10.nunique()),
                                   p3_starts=("p3_start", "sum"), p3_ends=("p3_end", "sum"),
                                   cut_mean=("quota_cut", lambda x: x[x > 0].mean()), cut_p50=("quota_cut", lambda x: x[x > 0].median()),
                                   cut_max=("quota_cut", "max"))
    if KCS.exists():
        kc = duckdb.connect(str(KCS), read_only=True)
        imp = kc.execute("select yyyymm, hs10, sum(imp_dlr) imp from fact_trade group by 1, 2").df()
        tot = imp.groupby(imp.yyyymm // 100).imp.sum()
        kc.close()
        x = mon[mon.p3_on].merge(imp, on=["yyyymm", "hs10"], how="left")
        summ["imp_p3_bn"] = x.groupby("year").imp.sum() / 1e9
        summ["imp_p3_pct"] = 100 * x.groupby("year").imp.sum() / tot
    summ.round(3).to_csv(ROOT / "outputs" / "할당관세_처치_요약.csv", encoding="utf-8-sig")
    print(summ.round(2).to_string())
    print(f"일 {len(daily):,}행(P3 {int((daily.cls == 'P3').sum()):,}·P1 {int((daily.cls == 'P1').sum()):,}), "
          f"월 {len(mon):,}행(코드 {mon.hs10.nunique():,}), P3 시작 {int(mon.p3_start.sum())}·종료 {int(mon.p3_end.sum())}, "
          f"quota_cut>0 코드×월 {int((mon.quota_cut > 1e-9).sum()):,}, 대조군 있는(n_fta0≥1) P3 코드×월 {int(((mon.n_fta0 >= 1) & mon.p3_on).sum()):,}")


if __name__ == "__main__":
    main()
