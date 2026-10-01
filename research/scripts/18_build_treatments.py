"""
18_build_treatments.py — 셋째 질문의 처리군 표를 만든다(연구 문서 III.2절).

신설 코드(2022·2025 개정)를 세 유형으로 나눈다.
  감시형   개정 사유가 감시 목적(관계부처 요청, 관리·모니터링·둔갑 방지·수입량 관리)이고
           실행세율(mfn)이 분리한 코드(전신)와 같은 것.
  세율형   신설 코드의 mfn이 전신 코드의 mfn(가중평균)과 다른 것. 사유와 무관. 감시형과 겹치면 세율형.
  기계적 짝  세분이 분리한 뒤 남은 몫을 받은 기타호. 처리군이 아니라 감시형·세율형의 짝.
전신 코드: 2022년은 dim_hs10_concordance(revision 2022)의 hs_from, 2025년은 같은 8단위 안에서
2025년에 폐지된 코드, 없으면 같은 8단위(없으면 6단위)에 남은 기타 코드.
집행 지정(사전세액심사·유통이력)은 별도 파일이 이미 있어 여기서는 코드별 지정일만 붙인다.

산출: research/outputs/처리군_목록.csv
"""
from __future__ import annotations

import re
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
BY = BYEOLPYO_DIR
WATCH = r"관계부처|관리|모니터링|둔갑|수입량|언론|기준규칙|관세청"
NOT_WATCH = r"신성장|현행화|범위수정|업계|기타호 신설|세분류체계"


def load():
    con = duckdb.connect()
    con.execute(f"ATTACH '{KCS.as_posix()}' AS s (READ_ONLY)")
    con.execute(f"ATTACH '{TARIFF.as_posix()}' AS tr (READ_ONLY)")
    rev = con.sql("SELECT rev, effective_ym, hs10, change, reason, name_ko FROM s.dim_hsk_revision WHERE rev IN ('2022','2025')").df()
    conc = con.sql("SELECT hs_from, hs_to, weight FROM s.dim_hs10_concordance WHERE revision='2022'").df()
    rate = con.sql("SELECT year, hs10, mfn, rate_undetermined FROM tr.fct_applied_rate WHERE year BETWEEN 2021 AND 2026").df()
    imp = con.sql("""
        WITH t AS (SELECT hs10, stat_cd, sum(imp_dlr) v, min(yyyymm) first_ym FROM s.fact_trade WHERE yyyymm BETWEEN 202201 AND 202607 AND imp_dlr>0 GROUP BY 1,2),
        tot AS (SELECT hs10, sum(v) v, min(first_ym) first_ym FROM t GROUP BY 1),
        top AS (SELECT hs10, stat_cd, v, row_number() OVER (PARTITION BY hs10 ORDER BY v DESC) rn FROM t)
        SELECT tot.hs10, round(tot.v/1e6,2) musd, tot.first_ym, top.stat_cd top_origin, round(top.v/tot.v,3) top_share
        FROM tot JOIN top ON top.hs10=tot.hs10 AND rn=1""").df()
    con.close()
    names = {y: pd.read_csv(BY / f"HSK_별표_{y}.csv", dtype=str).set_index("code").leaf.to_dict() for y in (2021, 2022, 2024, 2025)}
    pre = pd.read_csv(OUT / "사전세액심사_대상_이력_2016_2026.csv", dtype=str)
    dist = pd.read_csv(OUT / "유통이력_신고물품_코드요약_2009_2026.csv", dtype=str)
    return rev, conc, rate, imp, names, pre, dist


def main() -> None:
    rev, conc, rate, imp, names, pre, dist = load()
    mfn = {y: rate[rate.year == y].set_index("hs10").mfn.to_dict() for y in (2021, 2022, 2024, 2025)}
    new22 = rev[(rev.rev == "2022") & (rev.change == "신설")]
    new25 = rev[(rev.rev == "2025") & (rev.change == "신설")]
    dead25 = set(rev[(rev.rev == "2025") & (rev.change == "폐지")].hs10)
    codes24 = set(names[2024]); codes25 = set(names[2025])
    succ = conc.groupby("hs_from").hs_to.apply(set).to_dict()
    pred = conc.groupby("hs_to").apply(lambda g: list(zip(g.hs_from, g.weight))).to_dict()
    rows = []
    for _, r in pd.concat([new22, new25]).iterrows():
        h = r.hs10
        if r.rev == "2022":
            ps = [(p, w) for p, w in pred.get(h, []) if p != h]
            y_new, y_old = 2022, 2021
            sibs = set().union(*[succ.get(p, set()) for p, _ in ps]) - {h} if ps else set()
        else:
            y_new, y_old = 2025, 2024
            ps = [(p, 1.0) for p in dead25 if p[:8] == h[:8]] or [(p, 1.0) for p in dead25 if p[:6] == h[:6]]
            if not ps:
                cont = [c for c in codes24 & codes25 if c[:8] == h[:8] and names[2024].get(c) == "기타"]
                if not cont:
                    cont = [c for c in codes24 & codes25 if c[:6] == h[:6] and names[2024].get(c) == "기타"]
                ps = [(c, 1.0) for c in cont]
            sibs = {c for c in codes25 if c[:8] == h[:8] and c != h}
        wsum = sum(w for _, w in ps)
        pm = [(mfn[y_old].get(p), w) for p, w in ps if mfn[y_old].get(p) is not None and not np.isnan(mfn[y_old].get(p))]
        mfn_pred = sum(m * w for m, w in pm) / sum(w for _, w in pm) if pm else np.nan
        mfn_new = mfn[y_new].get(h, np.nan)
        pred_rates = sorted({round(m, 2) for m, _ in pm})
        sib_rates = sorted({round(mfn[y_new].get(c), 2) for c in sibs if mfn[y_new].get(c) is not None and not np.isnan(mfn[y_new].get(c))})
        reason = str(r.reason) if pd.notna(r.reason) else ""
        watch = bool(re.search(WATCH, reason)) and not re.search(NOT_WATCH, reason)
        if pd.isna(mfn_new) or pd.isna(mfn_pred):
            typ = "전신 불명" if not ps else "세율 불명"
        elif not any(abs(mfn_new - pr) <= 0.05 for pr in pred_rates):
            typ = "세율형"          # 신설 코드의 세율이 어느 전신 코드의 세율과도 다르다
        elif len(pred_rates) > 1 and watch:
            typ = "감시형(혼합 전신)"   # 세율이 다른 전신 여럿을 합쳐 나눈 것. 세율 변화인지 손으로 확인
        elif len(pred_rates) > 1:
            typ = "혼합 전신"
        elif watch:
            typ = "감시형"
        else:
            typ = "해당 없음"
        # 기계적 짝: 같은 전신을 나눈 형제 가운데 기타, 2025년은 이어지는 기타 전신
        mate = ""
        nm = names[y_new]
        cands = [c for c in sibs if nm.get(c) == "기타" and c[:6] == h[:6]] or ([p for p, _ in ps if p in codes25 and nm.get(p) == "기타"] if r.rev == "2025" else [])
        if cands:
            mate = sorted(cands, key=lambda c: -imp.set_index("hs10").musd.get(c, 0))[0]
        rows.append(dict(hs10=h, rev=r.rev, effective_ym=r.effective_ym, name=nm.get(h, r.name_ko), reason=reason, watch_reason=watch, type=typ,
                         mfn_new=mfn_new, mfn_pred=round(mfn_pred, 2) if pd.notna(mfn_pred) else np.nan, pred_rates="·".join(map(str, pred_rates)),
                         pred_codes="·".join(p for p, _ in ps[:6]) + ("…" if len(ps) > 6 else ""), n_pred=len(ps), pred_wsum=round(wsum, 3),
                         sibling_rates="·".join(map(str, sib_rates)), n_sib=len(sibs), mate_hs10=mate, mate_mfn=mfn[y_new].get(mate, np.nan) if mate else np.nan,
                         undetermined=bool(rate[(rate.hs10 == h) & (rate.year == y_new)].rate_undetermined.any())))
    t = pd.DataFrame(rows).merge(imp, on="hs10", how="left")
    pre_d = pre.groupby("hs10").agg(pre_assess_from=("aplyStrtDt", "min"), pre_assess_last=("last_month_seen", "max")).reset_index()
    t = t.merge(pre_d, on="hs10", how="left")
    d = dist.groupby("hs10").agg(dist_from=("first_start", "min"), dist_to=("last_end", "max")).reset_index()
    t = t.merge(d, on="hs10", how="left")
    t["sub_type"] = ""   # 경계 감시 / 협정 감시 — 손으로
    t["확인"] = ""
    t = t.sort_values(["type", "rev", "hs10"])
    t.to_csv(OUT / "처리군_목록.csv", index=False, encoding="utf-8-sig")
    print("유형별:", t.groupby(["rev", "type"]).size().to_dict())
    print("감시 사유 중 유형:", t[t.watch_reason].groupby(["rev", "type"]).size().to_dict())
    print("세율형 중 수입 있음:", int((t[t.type == "세율형"].musd.fillna(0) > 0).sum()), " 감시형 중 수입 있음:", int((t[t.type == "감시형"].musd.fillna(0) > 0).sum()))
    print("짝 있음:", int((t.mate_hs10 != "").sum()))


if __name__ == "__main__":
    main()
