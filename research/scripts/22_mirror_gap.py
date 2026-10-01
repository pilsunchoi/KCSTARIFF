"""
22_mirror_gap.py — 미러 갭 회귀(연구 문서 IV.3절). 상대국이 보고한 대한국 수출(21의 Comtrade)과 한국 수입(fact_trade)을
HS6 집단×원산지×연도로 맞대 갭 = ln X − ln M 을 금액·물량·단가로 나누고, 그 집단의 실행세율 수준과
집단 안 최대 격차에 회귀한다(집단 고정효과, 원산지×연도 고정효과, 집단 군집).

HS6 집단: 2012·2017·2022 개정으로 갈라지거나 합쳐진 HS6를 dim_hs6_concordance의 연결 성분으로 묶는다.
산출: outputs/미러_갭_패널.csv, outputs/미러_갭_회귀.csv, outputs/미러_건조생강.csv
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import os
ROOT = Path(__file__).resolve().parents[1]                      # KCSTARIFF/research
REPO = ROOT.parent                                               # KCSTARIFF
KCSDB2 = Path(os.environ.get("KCSDB2_ROOT", r"C:\Work\Projects\KCSDB2"))  # 무역통계 저장소(읽기 전용 의존)
TAR = REPO / "data" / "processed" / "kcstariff.duckdb"
KCS = KCSDB2 / "data" / "processed" / "kcsdb.duckdb"
OUT = ROOT / "outputs"
BYEOLPYO_DIR = KCSDB2 / "data" / "external" / "HSK_별표"


def fe_ols(df, y, xcols, fe, cluster, tol=1e-9, maxit=200):
    d = df[list(dict.fromkeys([y] + xcols + fe + [cluster]))].dropna().copy()
    Z = d[[y] + xcols].to_numpy(dtype=float)
    groups = [d[f].astype("category").cat.codes.to_numpy() for f in fe]
    for _ in range(maxit):
        Z0 = Z.copy()
        for g in groups:
            m = np.zeros((g.max() + 1, Z.shape[1])); n = np.bincount(g)
            np.add.at(m, g, Z); Z = Z - m[g] / n[g][:, None]
        if np.abs(Z - Z0).max() < tol:
            break
    yv, X = Z[:, 0], Z[:, 1:]
    XtX_inv = np.linalg.pinv(X.T @ X); b = XtX_inv @ X.T @ yv; e = yv - X @ b
    cl = d[cluster].astype("category").cat.codes.to_numpy(); G = cl.max() + 1
    S = np.zeros((G, X.shape[1])); np.add.at(S, cl, X * e[:, None]); meat = S.T @ S
    n, k = X.shape; V = XtX_inv @ meat @ XtX_inv * (G / (G - 1)) * ((n - 1) / (n - k))
    se = np.sqrt(np.diag(V))
    return pd.DataFrame({"coef": b, "se": se, "t": b / se}, index=xcols).assign(n=n, clusters=G)


def main() -> None:
    cm = pd.read_csv(OUT / "comtrade_mirror_hs6_2012_2024.csv", dtype={"cmdCode": str})
    con = duckdb.connect(); con.execute(f"ATTACH '{KCS.as_posix()}' AS s (READ_ONLY)"); con.execute(f"ATTACH '{TAR.as_posix()}' AS tr (READ_ONLY)")
    conc = con.sql("SELECT hs2022, hs_past, past_version FROM s.dim_hs6_concordance").df()
    # 집단: 범위 안 hs2022와 그 옛 코드의 연결 성분
    scope = set(cm.cmdCode)
    sub = conc[conc.hs2022.isin(scope) | conc.hs_past.isin(scope)]
    par = {}
    def find(x):
        while par.setdefault(x, x) != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for a, b in zip(sub.hs2022, sub.hs_past):
        par[find("N" + a)] = find("P" + b)
    def gid(code, version):
        key = ("N" if version == "2022" else "P") + code
        return find(key) if key in par else "N" + code
    grp_name = {}
    for n in list(par):
        r = find(n); grp_name.setdefault(r, set()).add(n[1:])
    label = {r: min(v) for r, v in grp_name.items()}
    def ver_of(year): return "2012" if year <= 2016 else "2017" if year <= 2021 else "2022"
    cm["grp"] = [label.get(gid(c, ver_of(y)), c) for c, y in zip(cm.cmdCode, cm.year)]
    X = cm.groupby(["reporter", "year", "grp"]).agg(x_usd=("value_usd", "sum"), x_kg=("net_kg", "sum")).reset_index()
    # 한국 수입
    con.register("rep", pd.DataFrame({"stat_cd": sorted(cm.reporter.unique())}))
    M = con.sql("""SELECT stat_cd AS reporter, yyyymm//100 AS year, substr(hs10,1,6) hs6, sum(imp_dlr) m_usd, sum(imp_wgt) m_kg
                   FROM s.fact_trade JOIN rep USING (stat_cd) WHERE yyyymm BETWEEN 201201 AND 202412 GROUP BY 1,2,3""").df()
    M["grp"] = [label.get(gid(c, ver_of(y)), c) for c, y in zip(M.hs6, M.year)]
    M = M[M.grp.isin(set(X.grp))].groupby(["reporter", "year", "grp"]).agg(m_usd=("m_usd", "sum"), m_kg=("m_kg", "sum")).reset_index()
    P = X.merge(M, on=["reporter", "year", "grp"], how="outer")
    P = P[(P.x_usd > 0) & (P.m_usd > 0)].copy()
    P["gap_v"] = np.log(P.x_usd / P.m_usd); P["gap_q"] = np.where((P.x_kg > 0) & (P.m_kg > 0), np.log(P.x_kg / P.m_kg), np.nan); P["gap_uv"] = P.gap_v - P.gap_q
    # 세율: 집단 안 HS10의 mfn(수입 가중 평균)과 최대 격차
    rt = con.sql("SELECT year, hs10, substr(hs10,1,6) hs6, mfn FROM tr.fct_applied_rate WHERE year BETWEEN 2012 AND 2024 AND mfn IS NOT NULL").df()
    w = con.sql("SELECT yyyymm//100 AS year, hs10, sum(imp_dlr) v FROM s.fact_trade WHERE yyyymm BETWEEN 201201 AND 202412 GROUP BY 1,2").df()
    rt = rt.merge(w, on=["year", "hs10"], how="left"); rt["v"] = rt.v.fillna(0) + 1.0
    rt["grp"] = [label.get(gid(c, ver_of(y)), c) for c, y in zip(rt.hs6, rt.year)]
    T = rt[rt.grp.isin(set(P.grp))].groupby(["year", "grp"]).apply(lambda g: pd.Series(dict(mfn_mean=np.average(g.mfn, weights=g.v), mfn_max=g.mfn.max(), mfn_min=g.mfn.min()))).reset_index()
    T["mfn_gap"] = T.mfn_max - T.mfn_min
    P = P.merge(T, on=["year", "grp"], how="left"); P["ry"] = P.reporter + "|" + P.year.astype(str)
    P.to_csv(OUT / "미러_갭_패널.csv", index=False, encoding="utf-8-sig")
    print(f"패널 {len(P):,} (집단 {P.grp.nunique()}, 보고국 {P.reporter.nunique()}, 연도 {P.year.min()}~{P.year.max()}); 갭 중위 금액 {P.gap_v.median():.2f} 물량 {P.gap_q.median():.2f} 단가 {P.gap_uv.median():.2f}")
    res = []
    for y in ["gap_v", "gap_q", "gap_uv"]:
        r = fe_ols(P, y, ["mfn_mean", "mfn_gap"], ["grp", "ry"], "grp")
        for x in ["mfn_mean", "mfn_gap"]:
            res.append(dict(dep=y, var=x, coef=r.loc[x, "coef"], se=r.loc[x, "se"], t=r.loc[x, "t"], n=int(r.n.iloc[0]), clusters=int(r.clusters.iloc[0])))
        # 중국만
        rc = fe_ols(P[P.reporter == "CN"].assign(ry=lambda d: d.year.astype(str)), y, ["mfn_mean", "mfn_gap"], ["grp", "ry"], "grp")
        for x in ["mfn_mean", "mfn_gap"]:
            res.append(dict(dep=y + "(중국)", var=x, coef=rc.loc[x, "coef"], se=rc.loc[x, "se"], t=rc.loc[x, "t"], n=int(rc.n.iloc[0]), clusters=int(rc.clusters.iloc[0])))
    R = pd.DataFrame(res).round(4); R.to_csv(OUT / "미러_갭_회귀.csv", index=False, encoding="utf-8-sig"); print(R.to_string(index=False))
    # 집단화 없이 HS6 그대로(2017~2024, HS2017·HS2022에서 코드가 같은 것만): 건조생강 0910.12 등
    F = cm[cm.year >= 2017].groupby(["reporter", "year", "cmdCode"]).agg(x_usd=("value_usd", "sum"), x_kg=("net_kg", "sum")).reset_index().rename(columns={"cmdCode": "hs6"})
    M6 = con.sql("""SELECT stat_cd AS reporter, yyyymm//100 AS year, substr(hs10,1,6) hs6, sum(imp_dlr) m_usd, sum(imp_wgt) m_kg
                    FROM s.fact_trade JOIN rep USING (stat_cd) WHERE yyyymm BETWEEN 201701 AND 202412 GROUP BY 1,2,3""").df()
    F = F.merge(M6, on=["reporter", "year", "hs6"], how="inner"); F = F[(F.x_usd > 0) & (F.m_usd > 0) & (F.x_kg > 0) & (F.m_kg > 0)].copy()
    F["gap_v"] = np.log(F.x_usd / F.m_usd); F["gap_q"] = np.log(F.x_kg / F.m_kg); F["gap_uv"] = F.gap_v - F.gap_q
    F["uv_x"] = F.x_usd / F.x_kg; F["uv_m"] = F.m_usd / F.m_kg
    F.to_csv(OUT / "미러_갭_HS6_2017_2024.csv", index=False, encoding="utf-8-sig")
    g = F[(F.reporter == "CN") & (F.hs6.isin({"091012", "091011"}))].sort_values(["hs6", "year"])
    g.to_csv(OUT / "미러_건조생강.csv", index=False, encoding="utf-8-sig")
    print("건조생강·신선생강 중국(HS6 그대로, 2017~):")
    print(g[["hs6", "year", "x_usd", "x_kg", "m_usd", "m_kg", "uv_x", "uv_m", "gap_uv"]].round(2).to_string(index=False))
    # 단가 갭이 가장 큰 HS6×원산지(2017~2024 평균, 수입 100만 달러 이상)
    top = F[F.m_usd >= 1e6].groupby(["reporter", "hs6"]).agg(gap_uv=("gap_uv", "mean"), n=("year", "size"), m_usd=("m_usd", "sum")).reset_index()
    top = top[top.n >= 4].sort_values("gap_uv", ascending=False)
    top["agri"] = top.hs6.str[:2].astype(int) <= 24
    print("단가 갭 상위, 농식품(1~24류) HS6×원산지(2017~2024 평균, 4년 이상, 수입 100만 달러 이상):")
    print(top[top.agri].head(15).round(2).to_string(index=False))
    print("농식품 단가 갭 분위:", top[top.agri].gap_uv.describe(percentiles=[.1, .5, .9]).round(2).to_dict())
    top.to_csv(OUT / "미러_단가갭_HS6원산지.csv", index=False, encoding="utf-8-sig")
    # 농식품만 갭 회귀
    Pa = P[P.grp.str[:2].astype(int) <= 24]
    ra = []
    for y in ["gap_v", "gap_q", "gap_uv"]:
        r = fe_ols(Pa, y, ["mfn_mean", "mfn_gap"], ["grp", "ry"], "grp")
        for x in ["mfn_mean", "mfn_gap"]:
            ra.append(dict(dep=y + "(농식품)", var=x, coef=r.loc[x, "coef"], se=r.loc[x, "se"], t=r.loc[x, "t"], n=int(r.n.iloc[0]), clusters=int(r.clusters.iloc[0])))
    Ra = pd.DataFrame(ra).round(4); print(Ra.to_string(index=False))
    pd.concat([R, Ra]).to_csv(OUT / "미러_갭_회귀.csv", index=False, encoding="utf-8-sig")
    con.close()


if __name__ == "__main__":
    main()
