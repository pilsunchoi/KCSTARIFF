"""
20_build_panel.py — 3단계 통관 패널(연구 문서 VI 3단계).

대상 코드 = 확정 코드 쌍(확인 Y 또는 별표)의 코드 + 처리군(감시형·세율형·혼합 전신·짝)과 그 전신·후신.
1) 원산지×월×코드 패널: fact_trade 수입액·중량, 연도별 원산지별 실행세율(쌍 코드는 19의 원산지별 표, 그 밖은
   fct_applied_rate의 일곱 상대 세율), 개정을 건너 잇는 hs2022(dim_hs10_to_2022 최빈 승계, chain만).
2) 쌍×원산지×월 표: 높은 쪽·낮은 쪽의 금액·중량·단가·세율·격차.
3) 점검: 세분 전후 합의 연속성(전신 12개월 대 신설+형제 12개월), 잔여 통관 창(폐지 코드가 개정 뒤에도 잡히는 달 수),
   2022년 개정으로 코드를 옮긴 수입액, 표 4의 2022년 수입액 몫 하락이 어느 HS6에서 왔는가.

산출: outputs/panel/panel_codes.parquet, panel_pairs.parquet, 패널_연속성_그룹.csv, 패널_표4_HS6.csv

--link {raw,mode,apportion}(2026-09-13, 논문 B 강건성): 쌍×원산지×월 표에서 2022년 전 계열을 잇는 방법.
  raw(기본) = 2022년 판 코드 번호 그대로(같은 번호의 옛 계열을 그대로 쓰고 신설 코드는 2022년 전 행이 없다. 기존 산출과 같다).
  mode = dim_hs10_to_2022(chain)의 최빈 승계 — 전신 코드의 금액·중량을 가중치가 가장 큰 후신 하나에 전부 배정.
  apportion = 안분 — 전신 코드의 금액·중량을 후신들에 weight 비례로 나눈다.
  raw가 아니면 산출은 outputs/panel_<link>/ 에 쓰고 기존 outputs/panel/ 은 건드리지 않는다.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import os
ROOT = Path(__file__).resolve().parents[1]                      # KCSTARIFF/research
REPO = ROOT.parent                                               # KCSTARIFF
KCSDB2 = Path(os.environ.get("KCSDB2_ROOT", r"C:\Work\Projects\KCSDB2"))  # 무역통계 저장소(읽기 전용 의존)
TARIFF = REPO / "data" / "processed" / "kcstariff.duckdb"
KCS = KCSDB2 / "data" / "processed" / "kcsdb.duckdb"
OUT = ROOT / "outputs"
BYEOLPYO_DIR = KCSDB2 / "data" / "external" / "HSK_별표"
PAN = OUT / "panel"
EU27 = set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split())
ASEAN = set("BN KH ID LA MY MM PH SG TH VN".split())


def regime_col(o: str) -> str:
    if o == "CN": return "applied_cn"
    if o == "US": return "applied_us"
    if o in EU27: return "applied_eu"
    if o == "VN": return "applied_vn"
    if o in ASEAN: return "applied_asean"
    if o == "IN": return "applied_in"
    if o == "CA": return "applied_ca"
    return "mfn"


def main(link: str = "raw") -> None:
    out_dir = OUT if link == "raw" else OUT / f"panel_{link}"
    pan = PAN if link == "raw" else out_dir
    pan.mkdir(parents=True, exist_ok=True)
    pairs = pd.read_csv(OUT / "코드쌍_목록.csv", dtype={"hs10_high": str, "hs10_low": str})
    pairs = pairs[(pairs.확인.fillna("") == "Y") | pairs.source.isin(["별표", "별표(선택)"])].copy()
    treat = pd.read_csv(OUT / "처리군_목록.csv", dtype={"hs10": str, "mate_hs10": str, "pred_codes": str})
    tr = treat[treat.type.isin(["감시형", "감시형(혼합 전신)", "세율형"])].copy()
    pred_codes = {c for s in tr.pred_codes.fillna("") for c in s.replace("…", "").split("·") if c}
    codes = set(pairs.hs10_high) | set(pairs.hs10_low) | set(tr.hs10) | set(tr.mate_hs10.dropna()) | pred_codes
    codes = sorted(c for c in codes if isinstance(c, str) and len(c) == 10)
    print(f"대상 코드 {len(codes)} (쌍 {pairs.hs10_high.nunique() + pairs.hs10_low.nunique()}, 처리군 {len(tr)}, 전신 {len(pred_codes)})")

    con = duckdb.connect()
    con.execute(f"ATTACH '{KCS.as_posix()}' AS s (READ_ONLY)")
    con.execute(f"ATTACH '{TARIFF.as_posix()}' AS tr (READ_ONLY)")
    con.register("codes", pd.DataFrame({"hs10": codes}))
    # 1) 원산지×월×코드
    f = con.sql("""
        SELECT f.yyyymm, f.stat_cd, f.hs10, f.imp_dlr, f.imp_wgt
        FROM s.fact_trade f JOIN codes USING (hs10) WHERE f.imp_dlr > 0 OR f.imp_wgt > 0""").df()
    f["year"] = f.yyyymm // 100
    # 최빈 승계 hs2022
    m = con.sql("SELECT hs_past, past_version, hs2022, weight FROM s.dim_hs10_to_2022 WHERE method='chain'").df()
    m = m.sort_values("weight", ascending=False).drop_duplicates(["hs_past", "past_version"])
    ver = np.where(f.year <= 2011, "2007", np.where(f.year <= 2016, "2012", np.where(f.year <= 2021, "2017", "2022")))
    f["past_version"] = ver
    f = f.merge(m[["hs_past", "past_version", "hs2022"]], left_on=["hs10", "past_version"], right_on=["hs_past", "past_version"], how="left").drop(columns=["hs_past"])
    f["hs2022"] = np.where(f.past_version == "2022", f.hs10, f.hs2022)
    # 세율: 쌍 코드는 원산지별 표, 나머지는 일곱 상대
    ext = pd.read_csv(OUT / "실행세율_원산지별_쌍코드_2012_2026.csv", dtype={"hs10": str})
    ext = ext.rename(columns={"applied_last": "tau_ext", "mfn": "mfn_ext"})[["year", "hs10", "stat_cd", "tau_ext", "regime"]]
    base = con.sql("SELECT year, hs10, mfn, applied_cn, applied_us, applied_eu, applied_asean, applied_vn, applied_in, applied_ca, floor_won_kg, rate_undetermined FROM tr.fct_applied_rate").df()
    base = base[base.hs10.isin(codes)]
    f = f.merge(base, on=["year", "hs10"], how="left").merge(ext, on=["year", "hs10", "stat_cd"], how="left")
    cols = f[["applied_cn", "applied_us", "applied_eu", "applied_asean", "applied_vn", "applied_in", "applied_ca", "mfn"]].to_numpy()
    idx = {"applied_cn": 0, "applied_us": 1, "applied_eu": 2, "applied_asean": 3, "applied_vn": 4, "applied_in": 5, "applied_ca": 6, "mfn": 7}
    f["tau_seven"] = [cols[i, idx[regime_col(o)]] for i, o in enumerate(f.stat_cd)]
    f["tau"] = f.tau_ext.where(f.tau_ext.notna(), f.tau_seven)
    f["uv"] = f.imp_dlr / f.imp_wgt.replace(0, np.nan)
    f = f.drop(columns=["applied_cn", "applied_us", "applied_eu", "applied_asean", "applied_vn", "applied_in", "applied_ca", "tau_seven"])
    f.to_parquet(pan / "panel_codes.parquet", index=False)
    print(f"panel_codes {len(f):,}행, 코드 {f.hs10.nunique()}, 원산지 {f.stat_cd.nunique()}, 세율 결측 {f.tau.isna().mean():.1%}, hs2022 결측(2022 전) {f[f.past_version!='2022'].hs2022.isna().mean():.1%}")

    # 2) 쌍×원산지×월
    key = ["yyyymm", "stat_cd", "hs10"]
    g = f[key + ["imp_dlr", "imp_wgt", "uv", "floor_won_kg"]]
    if link != "raw":
        # 2022년 전 계열을 연계표로 잇는다: 쌍 코드(2022년 판)의 전신 코드 전부를 가져와 mode(최빈, 가중치 1)·apportion(weight 비례)으로 배정
        pc_ = sorted(set(pairs.hs10_high) | set(pairs.hs10_low))
        lk = con.sql("SELECT hs_past, past_version, hs2022, weight FROM s.dim_hs10_to_2022 WHERE method='chain'").df()
        lk = lk[lk.hs2022.isin(pc_)].copy()
        if link == "mode":
            best = con.sql("SELECT hs_past, past_version, hs2022 FROM s.dim_hs10_to_2022 WHERE method='chain'").df().merge(m[["hs_past", "past_version", "hs2022"]], on=["hs_past", "past_version", "hs2022"])
            lk = lk.merge(best, on=["hs_past", "past_version", "hs2022"]); lk["weight"] = 1.0
        con.register("pastc", pd.DataFrame({"hs10": sorted(lk.hs_past.unique())}))
        old = con.sql("SELECT f.yyyymm, f.stat_cd, f.hs10, f.imp_dlr, f.imp_wgt FROM s.fact_trade f JOIN pastc USING (hs10) WHERE f.yyyymm < 202201 AND (f.imp_dlr > 0 OR f.imp_wgt > 0)").df()
        old["year"] = old.yyyymm // 100
        old["past_version"] = np.where(old.year <= 2011, "2007", np.where(old.year <= 2016, "2012", "2017"))
        old = old.merge(lk, left_on=["hs10", "past_version"], right_on=["hs_past", "past_version"], how="inner")
        old["imp_dlr"] = old.imp_dlr * old.weight; old["imp_wgt"] = old.imp_wgt * old.weight
        old = old.groupby(["yyyymm", "stat_cd", "hs2022"]).agg(imp_dlr=("imp_dlr", "sum"), imp_wgt=("imp_wgt", "sum")).reset_index().rename(columns={"hs2022": "hs10"})
        old["uv"] = old.imp_dlr / old.imp_wgt.replace(0, np.nan)
        fl_ = f[["year", "hs10", "floor_won_kg"]].drop_duplicates(["year", "hs10"]); old["year"] = old.yyyymm // 100
        old = old.merge(fl_, on=["year", "hs10"], how="left").drop(columns="year")
        g = pd.concat([g[(g.yyyymm >= 202201) | ~g.hs10.isin(pc_)], old[key + ["imp_dlr", "imp_wgt", "uv", "floor_won_kg"]]], ignore_index=True)
        print(f"연계({link}): 전신 코드 {lk.hs_past.nunique()}개 → 쌍 코드 {lk.hs2022.nunique()}개, 2022년 전 행 {len(old):,}")
    origins = sorted(f.stat_cd.unique())
    rl = base[["year", "hs10", "mfn", "applied_cn", "applied_us", "applied_eu", "applied_asean", "applied_vn", "applied_in", "applied_ca"]].merge(pd.DataFrame({"stat_cd": origins}), how="cross")
    rc = np.array([regime_col(o) for o in rl.stat_cd])
    arr = rl[["applied_cn", "applied_us", "applied_eu", "applied_asean", "applied_vn", "applied_in", "applied_ca", "mfn"]].to_numpy()
    rl["tau"] = arr[np.arange(len(rl)), [idx[c] for c in rc]]
    rl = rl[["year", "hs10", "stat_cd", "tau"]].merge(ext[["year", "hs10", "stat_cd", "tau_ext"]], on=["year", "hs10", "stat_cd"], how="left")
    rl["tau"] = rl.tau_ext.where(rl.tau_ext.notna(), rl.tau)
    rl = rl.drop(columns="tau_ext")
    rows = []
    for r in pairs.itertuples(index=False):
        H = g[g.hs10 == r.hs10_high].drop(columns="hs10").rename(columns=lambda c: c if c in ("yyyymm", "stat_cd") else c + "_H")
        L = g[g.hs10 == r.hs10_low].drop(columns="hs10").rename(columns=lambda c: c if c in ("yyyymm", "stat_cd") else c + "_L")
        x = H.merge(L, on=["yyyymm", "stat_cd"], how="outer")
        x.insert(0, "pair_id", r.pair_id); x.insert(1, "hs10_high", r.hs10_high); x.insert(2, "hs10_low", r.hs10_low)
        rows.append(x)
    pp = pd.concat(rows, ignore_index=True)
    pp["year"] = pp.yyyymm // 100
    pp = pp.merge(rl.rename(columns={"hs10": "hs10_high", "tau": "tau_H"}), on=["year", "hs10_high", "stat_cd"], how="left")
    pp = pp.merge(rl.rename(columns={"hs10": "hs10_low", "tau": "tau_L"}), on=["year", "hs10_low", "stat_cd"], how="left")
    pp["gap"] = pp.tau_H - pp.tau_L
    pp["share_L_v"] = pp.imp_dlr_L.fillna(0) / (pp.imp_dlr_L.fillna(0) + pp.imp_dlr_H.fillna(0)).replace(0, np.nan)
    pp.to_parquet(pan / "panel_pairs.parquet", index=False)
    print(f"panel_pairs {len(pp):,}행, 쌍 {pp.pair_id.nunique()}, 격차 결측 {pp.gap.isna().mean():.1%}")

    # 3) 점검 ① 세분 전후 합의 연속성 — 전신·후신 그래프의 연결 성분(닫힌 집단) 단위로 2021년 합과 2022년 합을 비교한다.
    #    2022년에도 남은 전신 코드는 후신에도 넣는다(연계표의 moved 관계에는 일부만 옮긴 코드가 있다).
    conc22 = con.sql("SELECT hs_from, hs_to FROM s.dim_hs10_concordance WHERE revision='2022' AND hs_from<>hs_to").df()
    dead = set(con.sql("SELECT hs10 FROM s.dim_hsk_revision WHERE change='폐지' AND rev IN ('2022','2025')").df().hs10)
    alive22 = set(pd.read_csv(BYEOLPYO_DIR / "HSK_별표_2022.csv", dtype=str).code)
    par = {}
    def find(x):
        while par.setdefault(x, x) != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for a_, b_ in zip(conc22.hs_from, conc22.hs_to):
        par[find("F" + a_)] = find("T" + b_)
    tr22 = tr[tr.rev == 2022]
    targets = {find("T" + h) for h in tr22.hs10 if "T" + h in par}
    groups = {}
    for n in list(par):
        r = find(n)
        if r in targets:
            groups.setdefault(r, {"F": set(), "T": set()})[n[0]].add(n[1:])
    for g in groups.values():
        g["T"] |= {h for h in g["F"] if h in alive22}
    # 2025년은 전신(폐지 또는 이어지는 기타)과 신설+짝
    for r in tr[tr.rev == 2025].itertuples(index=False):
        ps = {c for c in str(r.pred_codes or "").replace("…", "").split("·") if c}
        if ps:
            groups[("2025", r.hs10)] = {"F": ps, "T": {r.hs10} | ({r.mate_hs10} if isinstance(r.mate_hs10, str) else set()) | {c for c in ps if c not in dead}}
    need = sorted(set().union(*[g["F"] | g["T"] for g in groups.values()]))
    con.register("need", pd.DataFrame({"hs10": need}))
    mon = con.sql("SELECT yyyymm, hs10, sum(imp_dlr) v FROM s.fact_trade JOIN need USING (hs10) GROUP BY 1,2").df()
    rows = []
    for cid, g in groups.items():
        rev = 2025 if isinstance(cid, tuple) else 2022
        y0 = rev
        bsum = mon[(mon.yyyymm // 100 == y0 - 1)].groupby("hs10").v.sum(); asum = mon[(mon.yyyymm // 100 == y0)].groupby("hs10").v.sum()
        bf = sum(bsum.get(h, 0) for h in g["F"]); af = sum(asum.get(h, 0) for h in g["T"])
        deadF = g["F"] & dead
        resid = mon[mon.hs10.isin(deadF) & (mon.yyyymm >= y0 * 100 + 1)]
        rows.append(dict(rev=rev, n_from=len(g["F"]), n_to=len(g["T"]), treat="·".join(sorted(set(tr.hs10) & g["T"]))[:60],
                         before_musd=round(bf / 1e6, 2), after_musd=round(af / 1e6, 2), ratio=round(af / bf, 2) if bf > 0 else np.nan,
                         residual_months=int(resid.yyyymm.nunique()), residual_musd=round(resid.v.sum() / 1e6, 3)))
    cont = pd.DataFrame(rows).sort_values(["rev", "before_musd"], ascending=[True, False])
    cont.to_csv(out_dir / "패널_연속성_그룹.csv", index=False, encoding="utf-8-sig")
    big = cont[cont.before_musd >= 1]
    tot = con.sql("SELECT sum(CASE WHEN yyyymm>=202201 THEN imp_dlr END)/sum(CASE WHEN yyyymm<=202112 THEN imp_dlr END) FROM s.fact_trade WHERE yyyymm BETWEEN 202101 AND 202212").fetchone()[0]
    print(f"연속성(집단 {len(cont)}개, 전신 수입 1백만 달러 이상 {len(big)}개): 비율 분위 {big.ratio.describe(percentiles=[.1,.25,.5,.75,.9]).round(2)[['10%','25%','50%','75%','90%']].to_dict()}, 0.5~2.0 안 {int(big.ratio.between(0.5,2.0).sum())}, 총액 비율 {big.after_musd.sum()/big.before_musd.sum():.2f}(전체 수입 2022/2021 {tot:.2f})")
    print(f"잔여 통관: 폐지 전신이 있는 집단 {int((cont.residual_months>0).sum())}개, 최대 {int(cont.residual_months.max())}개월, 잔여 수입액 합 {cont.residual_musd.sum():.1f}백만 달러")

    # 점검 ② 2022년 개정으로 코드를 옮긴 수입액 (전체 자료)
    mv = con.sql("""
        WITH d AS (SELECT hs10 FROM s.dim_hsk_revision WHERE rev='2022' AND change='폐지'),
        t AS (SELECT sum(imp_dlr) v FROM s.fact_trade WHERE yyyymm BETWEEN 201701 AND 202112),
        x AS (SELECT sum(imp_dlr) v FROM s.fact_trade f JOIN d USING (hs10) WHERE yyyymm BETWEEN 201701 AND 202112)
        SELECT x.v/t.v pct FROM x, t""").fetchone()[0]
    print(f"2022년 개정으로 코드를 옮긴 수입액: 2017~2021년 총수입의 {100*mv:.2f}%")

    # 점검 ③ 표 4 HS6 몫: 기본세율이 다른 HS6의 수입액 몫, 2021 대 2022 (어느 HS6가 빠졌나)
    h6 = con.sql("""
        WITH r AS (SELECT year, hs10, substr(hs10,1,6) hs6, adval FROM tr.tariff_rate WHERE rate_cd='A' AND adval IS NOT NULL AND year IN (2021,2022)),
        g AS (SELECT year, hs6 FROM r GROUP BY 1,2 HAVING count(DISTINCT adval)>1),
        imp AS (SELECT yyyymm//100 AS year, substr(hs10,1,6) hs6, sum(imp_dlr) v FROM s.fact_trade WHERE yyyymm BETWEEN 202101 AND 202212 GROUP BY 1,2),
        tot AS (SELECT year, sum(v) tv FROM imp GROUP BY 1)
        SELECT imp.hs6, imp.year, imp.v/tot.tv*100 pct, CASE WHEN g.hs6 IS NULL THEN 0 ELSE 1 END diff
        FROM imp JOIN tot USING (year) LEFT JOIN g ON g.year=imp.year AND g.hs6=imp.hs6""").df()
    w = h6.pivot_table(index="hs6", columns="year", values=["pct", "diff"]).fillna(0)
    w.columns = [f"{a}_{b}" for a, b in w.columns]
    lost = w[(w.diff_2021 == 1) & (w.diff_2022 == 0)].sort_values("pct_2021", ascending=False)
    lost.to_csv(out_dir / "패널_표4_HS6.csv", encoding="utf-8-sig")
    print(f"표 4: 기본세율 다른 HS6 몫 2021 {w[w.diff_2021==1].pct_2021.sum():.1f}% → 2022 {w[w.diff_2022==1].pct_2022.sum():.1f}%; 2022에 빠진 HS6 {len(lost)}개, 그 2021 몫 합 {lost.pct_2021.sum():.1f}%p")
    print(lost.head(8)[["pct_2021", "pct_2022"]].round(2).to_string())
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--link", choices=["raw", "mode", "apportion"], default="raw", help="2022년 전 계열의 연계 방법(raw=기존, mode=최빈 승계, apportion=안분)")
    a = ap.parse_args()
    main(a.link)
