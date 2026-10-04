"""
39_quota_tax_expenditure.py — 할당관세의 관세 지출(세수 감면)을 코드×원산지×월로 추정한다(2026-10-04).

입력: outputs/panel_quota/(scripts/36: 코드×원산지×월 수입, 원산지 역할·협정세율, 처치 월 표의 P1·P3 일수와 세율),
      세율 DB fct_applied_rate(r_W1·r_W2·r_C·r_F·r_L·r_A), outputs/환율_월별_USDKRW.csv(scripts/26),
      scripts/34의 load_classified()(P1 구간과 한계수량 문구).
산출:
  outputs/할당관세_관세지출.csv — 연도별 금액(억 원)과 품목 수. 열 이름의 뜻은 아래 COLS.
  outputs/할당관세_관세지출_코드.csv — 연도×코드별 같은 금액(상위 품목 확인용).
  outputs/할당관세_관세지출_대조.csv — 국회예산정책처 수치와의 대조.
  outputs/할당관세_관세지출_원산지.csv — 연도×원산지×세율 열×HS2별 주 추정·명목·수입액(귀속과 특혜 마진 잠식 분석용).

계산(그달 원산지 o의 감면 폭, %p):
  할당이 없을 때의 세율 base_o — 무협정 원산지는 scripts/35의 mfn_noquota(양허 미추천 W2가 있으면 W2)이고,
    판 「w1」은 W2가 있는 코드에서 W2 대신 추천세율 W1(없으면 조정·기본·WTO 규칙의 세율)을 쓴다.
    협정·APTA 원산지는 min(협정세율, 무협정 base).
  전량 할당(P3): p3_days/ndays × max(0, base_o − min(p3_rate, WTO·국제협력, 협정세율)) — 판 「w2」에서는 36 패널의 d_quota와 같다.
  추천 할당(P1): p1_days/ndays × max(0, (base_o − P3 감면) − p1_rate). 추천받은 수입자에게만 적용되므로
    「상한」은 그 코드의 모든 수입에 적용한 값, 「한계수량」은 별표 한계수량(톤·배럴)까지만 적용한 값이다
    (구간의 수입 중량이 한계수량을 넘으면 비율대로 줄인다; 한계수량이 비었거나 톤·배럴이 아닌 코드는 상한 그대로 두고 따로 센다).
  excl(세율 자료에 없는 협정 상대국·최빈국): 하한 0, 상한은 무협정 원산지처럼 계산한 값.
  금액 = 수입액(CIF 달러) × 월평균 환율 × 감면 폭. 과세가격 대신 CIF 수입액을 쓴다.
  「명목」은 원산지를 가리지 않고 모든 수입에 무협정 감면 폭을 붙인 값이고, 명목 − (무협정+협정 원산지 실제)는
  협정세율이 이미 할당세율 이하라 할당관세가 세율을 바꾸지 못한 몫이다(excl 제외).
"""

import importlib.util
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
DB = REPO / "data" / "processed" / "kcstariff.duckdb"
PAN = ROOT / "outputs" / "panel_quota"
FX = ROOT / "outputs" / "환율_월별_USDKRW.csv"
BBL_T = 0.159 * 0.86                     # 원유 1배럴 ≈ 0.159㎘ × 비중 0.86 → 톤
KCS = Path(__import__("os").environ.get("KCSDB2_ROOT", REPO.parent / "KCSDB2")) / "data" / "processed" / "kcsdb.duckdb"

# 규격·용도 조건이 붙은 P3의 조건 해당 몫. 조건부 P3 금액(2007~2026년 합)의 89%를 차지하는 상위 40개 코드를 손으로 분류했다.
#   full  — 조건이 그 코드의 수입을 사실상 좁히지 않는다(몫 1).
#   split — 뒤에 HSK가 조건 물품의 전용 코드를 만들었다. 갈라진 첫해의 전용 코드 수입 몫을 쓴다(SPLIT).
#   그 밖(목록에 없는 코드 포함) — 넓은 코드의 일부만 해당하고 몫을 알 수 없다(narrow): 하한 0, 상한 1.
COND_FULL = {
    **{h: "원유: P3는 나프타·LPG 제조용을 뺀 원유, 그 용도는 P1로 따로 계산(보완 조건)" for h in
       ("2709001010", "2709001030", "2709001040", "2709001050", "2709001060", "2709001080", "2709001090")},
    "2711110000": "「액화된 것인지의 여부를 불문한다」(제한 아님)",
    "0803900000": "신선 바나나(이 코드는 건조를 포함하나 건조 수입은 작다)",
    "0804300000": "신선 파인애플(위와 같음)",
    "2841909020": "코드 이름이 조건 물품(니켈코발트망간 산화물의 리튬염)",
    "1507101000": "코드 이름이 「식품용」",
    "2814100000": "무수암모니아 순도 99.5% 이상(상업 등급 대부분)",
    "8486303041": "코드 이름이 조건 물품(건식식각기)",
    "8486305010": "코드 이름이 조건 물품(도포기)",
    "2710194030": "코드 이름이 조건 물품(방카 씨유, 웨이스트오일 포함)",
    "2303200000": "사료용·버섯 재배용(비트펄프·버개스는 대부분 사료)",
    "3901209000": "「펄프의 것은 제외한다」(작은 제외)",
}
# 조건 물품의 전용 코드가 생긴 해와 그 코드들(조건에 해당하는 것만), 같은 옛 코드에서 갈라진 코드 전부의 접두
COND_SPLIT = {
    "2841909000": (2022, ("2841909010", "2841909020", "2841909030"), "2841909"),   # 코발트산·NCM·NCA 리튬(조건 셋)
    "3904690000": (2022, ("3904691000",), "390469"),                              # PVDF(이차전지 제조용)
    "6307909000": (2021, ("6307904010", "6307904020"), ("6307904", "6307909")),   # 수술용·보건용 마스크
}
# 외부 자료로 좁힌 몫(est): 코드 → (하한, 상한). 세계 용도별 수요는 Johnson Matthey, Pgm Market Report May 2021, 표 5·6·7·8·10.
#   팔라듐: 세계 총수요(자동차+산업) 가운데 자동차 촉매 2019~2021년 85.0·84.6·84.8%. 한국은 전자(MLCC)·치과 수요가 커
#     세계 몫을 넘기 어렵다고 보아 상한 0.85, 하한 0.60.
#   로듐: 같은 몫 88.6·92.9·90.8%. 한국은 디스플레이 유리(백금·로듐 부싱) 수요가 커 상한 0.91, 하한 0.70.
COND_EST = {"7110210000": (0.60, 0.85), "7110310000": (0.70, 0.91)}
# 단가로 상한을 좁히는 조건(est_uv): 이차전지용 흑연화합물과 농약원제. 음극재·농약원제는 kg당 3달러 이상이라 보고,
# 원산지×월 흐름의 단가가 3달러 미만이면(대만·중국산 벌크 용제 PGMEA·NMP류 등) 상한에서 뺀다. 하한은 0.
UV_MIN = 3.0
COND_UV_SPEC = ("흑연화합물", "농약원제")

spec = importlib.util.spec_from_file_location("s34", ROOT / "scripts" / "34_build_quota_p3_periods.py")
s34 = importlib.util.module_from_spec(spec); spec.loader.exec_module(s34)


def kor_num(s: str) -> float | None:
    """「2만7천」「20,000」「1.5만」 같은 첫 수량을 수로 바꾼다."""
    m = re.search(r"[\d,.]+(?:\s*[만천백]\s*[\d,.]*)*(?:\s*[만천백])?", s)
    if not m:
        return None
    t = m.group(0).replace(",", "").replace(" ", "")

    def small(s: str) -> float:                       # 만 아래(천·백)
        tot = 0.0
        for unit, mult in (("천", 1e3), ("백", 1e2)):
            if unit in s:
                a, s = s.split(unit, 1)
                tot += (float(a) if a else 1.0) * mult
        return tot + (float(s) if s else 0.0)
    try:
        if "만" in t:
            a, r = t.split("만", 1)
            total = (small(a) if a else 1.0) * 1e4 + small(r)
        else:
            total = small(t)
    except ValueError:
        return None
    return total or None


def cap_tonnes(q: str) -> float | None:
    """한계수량 문구 → 톤(톤·메트릭톤·십메트릭톤·배럴만; 그 밖은 None)."""
    q = str(q).replace(" ", "")
    if not q or "수입전량" in q:
        return None
    v = kor_num(q)
    if v is None:
        return None
    m = re.search(r"[\d,.만천백]+(십메트릭톤|메트릭톤|톤|배럴)", q)
    if not m:
        return None
    u = m.group(1)
    return v * (10 if u == "십메트릭톤" else BBL_T if u == "배럴" else 1)


def main() -> None:
    con = duckdb.connect()
    db = duckdb.connect(str(DB), read_only=True)
    ar = db.execute("select year, hs10, r_W1, r_W2, r_C, r_F, r_L, r_A from fct_applied_rate").df()
    db.close()
    con.register("ar", ar)
    con.execute(f"""
      CREATE TEMP TABLE b AS
      WITH p AS (SELECT p.*, fx.krw_per_usd AS fx,
                        day(last_day(make_date(p.year::INT, (p.yyyymm % 100)::INT, 1))) AS ndays
                 FROM read_parquet('{PAN.as_posix()}/**/*.parquet', hive_partitioning=1) p
                 JOIN read_csv_auto('{FX.as_posix()}') fx USING (yyyymm)),
      r AS (SELECT p.*, least(coalesce(ar.r_C, 1e9), coalesce(ar.r_F, 1e9)) AS tier2,
                   CASE WHEN ar.r_W2 IS NOT NULL
                        THEN least(coalesce(ar.r_W1, 1e9), least(coalesce(ar.r_L, ar.r_A, 1e9), coalesce(ar.r_C, 1e9), coalesce(ar.r_F, 1e9)))
                        ELSE p.mfn_noquota END AS mfn_w1,
                   ar.r_W2 IS NOT NULL AS has_w2
            FROM p LEFT JOIN ar ON ar.year = p.year AND ar.hs10 = p.hs10)
      SELECT yyyymm, year, hs10, stat_cd, rate_col, role, has_w2, imp_dlr * fx AS krw, imp_dlr, imp_wgt, ndays, p3_days, p3_rate, p1_days, p1_rate,
             mfn_noquota AS base_mfn_w2, least(mfn_w1, mfn_noquota) AS base_mfn_w1, tier2, pref
      FROM r""")
    b = con.execute("SELECT * FROM b").df()
    for c in ["krw", "imp_wgt", "ndays", "p3_days", "p3_rate", "p1_days", "p1_rate", "base_mfn_w2", "base_mfn_w1", "tier2", "pref"]:
        b[c] = b[c].astype("float64")
    b["has_w2"] = b.has_w2.fillna(False).astype(bool)
    p3eff_mfn = np.minimum(b.p3_rate.fillna(np.inf), b.tier2)
    pref = b.pref.fillna(np.inf)
    f3 = b.p3_days / b.ndays
    f1 = b.p1_days / b.ndays
    for v in ("w2", "w1"):
        base_mfn = b[f"base_mfn_{v}"]
        # 원산지별 base: 무협정·excl(상한)은 무협정 세율, 협정 원산지는 협정세율과 중 낮은 쪽
        base_o = np.where(b.role.isin(["control", "pref_pos"]), np.minimum(pref, base_mfn), base_mfn)
        p3_o = np.where(b.role.isin(["control", "pref_pos"]), np.minimum(pref, p3eff_mfn), p3eff_mfn)
        cut3 = np.where(b.p3_days > 0, f3 * np.clip(base_o - p3_o, 0, None), 0.0)
        cut1 = np.where(b.p1_days > 0, f1 * np.clip(base_o - cut3 - b.p1_rate.fillna(np.inf), 0, None), 0.0)
        cut3_mfn = np.where(b.p3_days > 0, f3 * np.clip(base_mfn - p3eff_mfn, 0, None), 0.0)
        b[f"e3_{v}"] = b.krw * np.nan_to_num(cut3) / 100
        b[f"e1_{v}"] = b.krw * np.nan_to_num(cut1) / 100
        b[f"e3nom_{v}"] = b.krw * np.nan_to_num(cut3_mfn) / 100
        b[f"bp1_{v}"] = np.nan_to_num(base_o - cut3, posinf=0.0)       # P3 감면 뒤의 세율(P1 감면의 기준)

    # --- P1 한계수량: 별표 행(구간)마다 그 행의 세율로 감면을 계산하고, 행에 묶인 코드의 구간 내 수입 중량이
    # 한계수량을 넘으면 비율대로 줄인다. 용도별로 한계수량이 다른 행이 한 코드에 겹치면(원유의 나프타·LPG·항공유용 등)
    # 행마다 따로 계산해 더하되, 코드×월의 합은 모든 수입에 가장 낮은 세율을 붙인 상한을 넘지 않게 한다.
    # 한계수량이 있는 행이 있는 코드는 빈 한계수량 행(10단위 대응의 동점 등)을 무시하고, 없는 코드는 상한 그대로 둔다.
    o, _ = s34.load_classified()
    p1 = o[o.cls == "P1"].copy()
    p1["cap_t"] = [cap_tonnes(q) for q in p1.quota]
    p1["rate_v"] = [min(s34.nums(r)) if s34.nums(r) else np.nan for r in p1.rate]
    # 연중 개정 판본마다 같은 연간 한계수량이 구간별로 다시 적히므로(2023년 나프타 제조용 원유 1억 배럴이 세 구간),
    # 한계수량 하나 = 같은 해·품명·규격·한계수량 문구. 그 안의 구간마다 세율이 다를 수 있다.
    p1["key"] = p1.year.astype(str) + "|" + p1.name_path.astype(str) + "|" + p1.spec.astype(str) + "|" + p1.quota.astype(str)
    capped = p1[p1.cap_t.notna() & p1.rate_v.notna()]
    # 한계수량 행이 하나도 대응되지 않은 P1 코드는 같은 해 같은 HS6의 한계수량 묶음에 넣는다(2015년 원유: 한계수량 행이
    # 2709001020에만 대응되고 다른 원유 코드에는 빈 한계수량 행만 붙었다). 그 코드의 구간은 묶음의 구간을 따른다.
    has_cap = set(zip(capped.year, capped.hs10))
    orphan = p1[[(y, h) not in has_cap for y, h in zip(p1.year, p1.hs10)]][["year", "hs10"]].drop_duplicates()
    orphan["hs6"] = orphan.hs10.str[:6]
    cap6 = capped.assign(hs6=capped.hs10.str[:6]).drop(columns="hs10")
    adopt = orphan.merge(cap6, on=["year", "hs6"])
    n_adopt = adopt[["year", "hs10"]].drop_duplicates().shape[0]
    capped = pd.concat([capped, adopt[capped.columns]], ignore_index=True)
    ex = []
    for key, g in capped.groupby("key"):
        for (vf, vt, rv), gi in g.groupby(["valid_from", "valid_to", "rate_v"]):
            vf, vt = pd.Timestamp(vf), pd.Timestamp(vt)
            for m in pd.period_range(vf, vt, freq="M"):
                d0, d1 = max(vf, m.start_time), min(vt, m.end_time.normalize())
                for h in gi.hs10.unique():
                    ex.append((key, h, m.year * 100 + m.month, ((d1 - d0).days + 1) / m.days_in_month, rv, g.cap_t.iloc[0]))
    ex = pd.DataFrame(ex, columns=["key", "hs10", "yyyymm", "w", "rate_row", "cap_t"])
    ne = b.loc[b.role != "excl", ["hs10", "yyyymm", "krw", "imp_wgt", "bp1_w2", "bp1_w1"]]
    x = ex.merge(ne, on=["hs10", "yyyymm"])
    for v in ("w2", "w1"):
        cut = x.w * np.clip(x[f"bp1_{v}"] - x.rate_row, 0, None)
        x[f"eu_{v}"] = x.krw * cut / 100
        x[f"kg_{v}"] = np.where(cut > 0, x.imp_wgt * x.w, 0.0)
        k = x.groupby("key")[[f"eu_{v}", f"kg_{v}"]].transform("sum")
        x[f"ec_{v}"] = x[f"eu_{v}"] * np.where(k[f"kg_{v}"] > 0, np.minimum(1.0, x.cap_t * 1000 / k[f"kg_{v}"].where(k[f"kg_{v}"] > 0, 1)), 1.0)
    cm = x.groupby(["hs10", "yyyymm"])[["ec_w2", "ec_w1"]].sum()
    ub = b[b.role != "excl"].groupby(["hs10", "yyyymm"])[["e1_w2", "e1_w1"]].sum()
    cm = cm.join(ub, how="left")
    for v in ("w2", "w1"):
        cm[f"sc_{v}"] = np.where(cm[f"e1_{v}"] > 0, np.minimum(cm[f"ec_{v}"], cm[f"e1_{v}"]) / cm[f"e1_{v}"].where(cm[f"e1_{v}"] > 0, 1), 1.0)
    b = b.merge(cm[["sc_w2", "sc_w1"]].reset_index(), on=["hs10", "yyyymm"], how="left")
    for v in ("w2", "w1"):
        b[f"e1cap_{v}"] = b[f"e1_{v}"] * b[f"sc_{v}"].fillna(1.0)
        b[f"e1unc_{v}"] = np.where(b[f"sc_{v}"].isna(), b[f"e1_{v}"], 0.0)   # 한계수량을 못 붙인 몫
    # 규격·용도 조건이 붙은 P3(별표 「규격」 칸이 빈칸이 아님): 10단위 코드의 수입 전부가 조건을 채우지는 않으므로 과대 쪽
    sp = o.spec.fillna("").astype(str).str.strip()
    cond = o[(o.cls == "P3") & (sp != "") & (sp.str.lower() != "nan")][["year", "hs10"]].drop_duplicates()
    cond["cond3"] = True
    b = b.merge(cond, on=["year", "hs10"], how="left")
    b["cond3"] = b.cond3.fillna(False).astype(bool)
    # 조건 해당 몫: full 1, split은 갈라진 첫해의 전용 코드 몫, narrow는 하한 0·상한 1
    kc = duckdb.connect(str(KCS), read_only=True)
    split_share = {}
    for h, (y, ded, pre) in COND_SPLIT.items():
        pre = pre if isinstance(pre, tuple) else (pre,)
        t = kc.execute(f"SELECT hs10, sum(imp_dlr) v FROM fact_trade WHERE yyyymm // 100 = {y} AND ("
                       + " OR ".join(f"hs10 LIKE '{p}%'" for p in pre) + ") GROUP BY 1").df()
        split_share[h] = t[t.hs10.isin(ded)].v.sum() / t.v.sum()
    kc.close()
    b["cond_cls"] = np.where(~b.cond3, "", np.where(b.hs10.isin(list(COND_FULL)), "full",
                             np.where(b.hs10.isin(list(COND_SPLIT)), "split", "narrow")))
    # 단가 상한 조건: 그해 P3 규격 문구에 흑연화합물·농약원제가 있는 코드×연도
    spx = o[(o.cls == "P3")].assign(sp=sp)
    uvc = spx[spx.sp.str.contains("|".join(COND_UV_SPEC))][["year", "hs10"]].drop_duplicates().assign(uvc=True)
    b = b.merge(uvc, on=["year", "hs10"], how="left")
    b["uvc"] = b.uvc.fillna(False).astype(bool)
    est = b.hs10.isin(list(COND_EST))
    b.loc[b.cond3 & ~b.hs10.isin(list(COND_FULL)) & ~b.hs10.isin(list(COND_SPLIT)) & est, "cond_cls"] = "est"
    b.loc[(b.cond_cls == "narrow") & b.uvc, "cond_cls"] = "est_uv"
    uv = b.imp_dlr.astype("float64") / b.imp_wgt.where(b.imp_wgt > 0)
    lo_est = b.hs10.map({k: v[0] for k, v in COND_EST.items()})
    hi_est = b.hs10.map({k: v[1] for k, v in COND_EST.items()})
    b["cond_share_lo"] = np.select([b.cond_cls == "split", b.cond_cls == "est", b.cond_cls.isin(["narrow", "est_uv"])],
                                   [b.hs10.map(split_share), lo_est, 0.0], 1.0)
    b["cond_share_hi"] = np.select([b.cond_cls == "split", b.cond_cls == "est", b.cond_cls == "est_uv"],
                                   [b.hs10.map(split_share), hi_est, (uv.fillna(np.inf) >= UV_MIN).astype(float)], 1.0)

    # --- 연도별 합계(억 원)
    EOK = 1e8
    trt, prf, exc = b.role == "treated", b.role.isin(["control", "pref_pos"]), b.role == "excl"
    rows = []
    for y, g in b.groupby("year"):
        t, pf, ex = trt[g.index], prf[g.index], exc[g.index]
        r = {"year": y}
        for v in ("w2", "w1"):
            r[f"p3_mfn_{v}"] = g.loc[t, f"e3_{v}"].sum() / EOK
            r[f"p3_pref_{v}"] = g.loc[pf, f"e3_{v}"].sum() / EOK
            r[f"p3_excl_ub_{v}"] = g.loc[ex, f"e3_{v}"].sum() / EOK
            r[f"p3_nominal_{v}"] = g.loc[~ex, f"e3nom_{v}"].sum() / EOK
            r[f"p3_ineffective_{v}"] = r[f"p3_nominal_{v}"] - r[f"p3_mfn_{v}"] - r[f"p3_pref_{v}"]
            r[f"p1_ub_{v}"] = g.loc[~ex, f"e1_{v}"].sum() / EOK
            r[f"p1_cap_{v}"] = g.loc[~ex, f"e1cap_{v}"].sum() / EOK
            r[f"p1_uncapped_{v}"] = g.loc[~ex, f"e1unc_{v}"].sum() / EOK
            r[f"p1_excl_ub_{v}"] = g.loc[ex, f"e1_{v}"].sum() / EOK
            r[f"w2codes_p3_{v}"] = g.loc[g.has_w2 & (g[f"e3_{v}"] > 0)].hs10.nunique()
        r["p3_cond_w1"] = g.loc[~ex & g.cond3, "e3_w1"].sum() / EOK
        gc = g[~ex & g.cond3]
        for cl in ("full", "split", "est", "est_uv", "narrow"):
            m = gc.cond_cls == cl
            r[f"p3_cond_{cl}"] = gc.loc[m, "e3_w1"].sum() / EOK
            r[f"p3_cond_{cl}_lo"] = (gc.loc[m, "e3_w1"] * gc.loc[m, "cond_share_lo"]).sum() / EOK
            r[f"p3_cond_{cl}_hi"] = (gc.loc[m, "e3_w1"] * gc.loc[m, "cond_share_hi"]).sum() / EOK
        base = r["p3_mfn_w1"] + r["p3_pref_w1"] + r["p1_cap_w1"]
        cut_lo = (gc.e3_w1 * (1 - gc.cond_share_lo)).sum() / EOK
        cut_hi = (gc.e3_w1 * (1 - gc.cond_share_hi)).sum() / EOK
        r["main_uncorrected"] = base
        r["main_lo"] = base - cut_lo
        r["main_hi"] = base - cut_hi
        r["imp_p3_eok"] = g.loc[g.p3_days > 0, "krw"].sum() / EOK
        r["imp_p1_eok"] = g.loc[g.p1_days > 0, "krw"].sum() / EOK
        rows.append(r)
    out = pd.DataFrame(rows)

    # 품목 수: HS10(P1·P3 구분)과 별표 행(HS6·호·품명·규격 단위), 그해 1월 1일 뒤에 처음 지정된 별표 행(연중 지정)
    sch = pd.read_csv(ROOT / "outputs" / "할당관세_시간표.csv", dtype={"hs6": str, "hs4": str, "sub": str})
    sch["item"] = sch.hs6 + "|" + sch["sub"].astype(str) + "|" + sch.name_path.fillna("").astype(str) + "|" + sch.spec.fillna("").astype(str)
    cnt = []
    for y in out.year:
        y0, y1 = f"{y}-01-01", f"{y}-12-31"
        s = sch[(sch.valid_from <= y1) & (sch.valid_to >= y0)]
        first = s.groupby("item").valid_from.min()
        first4 = s.groupby("hs4").valid_from.min()
        oy = o[o.year == y]
        cnt.append({"year": y, "items_annex": s.item.nunique(), "items_hs6": s.hs6.nunique(), "items_hs4": s.hs4.nunique(),
                    "items_hs4_midyear": int((first4 > y0).sum()),
                    "items_midyear": int((first > y0).sum()), "codes_hs10": oy.hs10.nunique(),
                    "codes_p3": oy[oy.cls == "P3"].hs10.nunique(), "codes_p1": oy[oy.cls == "P1"].hs10.nunique()})
    out = out.merge(pd.DataFrame(cnt), on="year")
    num = out.columns.difference(["year"])
    out[num] = out[num].round(1)
    out.to_csv(ROOT / "outputs" / "할당관세_관세지출.csv", index=False, encoding="utf-8-sig")

    code = b.groupby(["year", "hs10"]).agg(
        krw_eok=("krw", lambda x: x.sum() / EOK), has_w2=("has_w2", "max"),
        p3_w2=("e3_w2", lambda x: x[~exc[x.index]].sum() / EOK), p3_w1=("e3_w1", lambda x: x[~exc[x.index]].sum() / EOK),
        p3_excl_ub=("e3_w1", lambda x: x[exc[x.index]].sum() / EOK),
        p1_ub_w1=("e1_w1", lambda x: x[~exc[x.index]].sum() / EOK), p1_cap_w1=("e1cap_w1", lambda x: x[~exc[x.index]].sum() / EOK),
        p1_ub_w2=("e1_w2", lambda x: x[~exc[x.index]].sum() / EOK), cond3=("cond3", "max"), cond_cls=("cond_cls", "max"),
        cond_share_lo=("cond_share_lo", "max"), cond_share_hi=("cond_share_hi", "max")).reset_index()
    code = code[(code[["p3_w2", "p3_w1", "p3_excl_ub", "p1_ub_w1", "p1_cap_w1", "p1_ub_w2"]].abs().sum(axis=1) > 0)]
    code.round(3).to_csv(ROOT / "outputs" / "할당관세_관세지출_코드.csv", index=False, encoding="utf-8-sig")

    # --- 국회예산정책처(장설희 2025, NABO Focus 114, 표 1·2; 원자료 기재부 「할당관세 부과 실적 및 결과 보고」)와 대조
    # 주 추정 = P3(무협정+협정 원산지, w1) + P1(한계수량, w1), excl은 0(하한)과 상한을 따로.
    b["main"] = np.where(exc, 0.0, b.e3_w1 + b.e1cap_w1)
    b["main_lo"] = np.where(exc, 0.0, b.e3_w1 * np.where(b.cond3, b.cond_share_lo, 1.0) + b.e1cap_w1)
    b["main_hi"] = np.where(exc, 0.0, b.e3_w1 * np.where(b.cond3, b.cond_share_hi, 1.0) + b.e1cap_w1)
    b["excl_ub"] = np.where(exc, b.e3_w1 + b.e1_w1, 0.0)
    b["p1_ub"] = np.where(exc, 0.0, b.e3_w1 + b.e1_w1)
    groups = {"LNG": ("2711110000",), "원유": ("2709",), "LPG": ("271112", "271113"), "옥수수": ("1005",), "설탕": ("1701",),
              "바나나": ("080390",), "망고": ("08045020",), "그 밖": None, "합계": ("",)}
    named = tuple(x for k, v in groups.items() if k not in ("그 밖", "합계") for x in v)
    nabo = {"합계": [3742, 6758, 19694, 10753, 14301], "LNG": [598.3, 1357.2, 7383.0, 2388.5, 5249.0],
            "원유": [1622.5, 1796.8, 2494.2, 1878.9, 2623.8], "LPG": [346.9, 597.3, 690.7, 1020.4, 321.8],
            "옥수수": [294.7, 762.1, 1415.4, 806.9, 592.3], "설탕": [124.6, 149.9, 197.2, 265.2, 282.2],
            "바나나": [None, None, 104.9, 120.4, 1108.9], "망고": [None, None, 13.2, 38.4, 416.1]}
    nabo["그 밖"] = [t - sum(nabo[k][i] or 0 for k in groups if k not in ("그 밖", "합계")) for i, t in enumerate(nabo["합계"])]
    nabo_items = {2020: 79, 2021: 92, 2022: 119, 2023: 117, 2024: 125}
    cmp_rows = []
    for gname, pre in groups.items():
        sel = ~b.hs10.str.startswith(named) if pre is None else b.hs10.str.startswith(pre)
        for i, y in enumerate(range(2020, 2025)):
            g = b[sel & (b.year == y)]
            cmp_rows.append({"item": gname, "year": y, "nabo": nabo[gname][i], "est_main": g.main.sum() / EOK,
                             "est_p3": g.loc[~exc[g.index], "e3_w1"].sum() / EOK, "est_p1_cap": g.loc[~exc[g.index], "e1cap_w1"].sum() / EOK,
                             "est_p1_ub": g.loc[~exc[g.index], "e1_w1"].sum() / EOK, "est_excl_ub": g.excl_ub.sum() / EOK,
                             "est_p3_cond": g.loc[~exc[g.index] & g.cond3, "e3_w1"].sum() / EOK,
                             "est_lo": g.main_lo.sum() / EOK, "est_hi": g.main_hi.sum() / EOK,
                             "nabo_items": nabo_items[y] if gname == "합계" else None})
    cmp_ = pd.DataFrame(cmp_rows)
    cmp_["ratio_main"] = cmp_.est_main / cmp_.nabo
    cmp_["ratio_lo"] = cmp_.est_lo / cmp_.nabo
    cmp_["ratio_hi"] = cmp_.est_hi / cmp_.nabo
    cmp_.round(3).to_csv(ROOT / "outputs" / "할당관세_관세지출_대조.csv", index=False, encoding="utf-8-sig")
    # 원산지별 귀속: 연도×원산지×세율 열×HS2(억 원). main_lo·main_hi(주 추정), nominal(무협정 감면 폭을 모든 수입에 붙인 P3 명목),
    # krw(수입액). excl 원산지는 main이 0이고 nominal만 있다.
    b["nominal"] = b.e3nom_w1
    b["p3_act"] = np.where(exc, 0.0, b.e3_w1)
    b["hs2"] = b.hs10.str[:2]
    org = b.groupby(["year", "stat_cd", "rate_col", "role", "hs2"])[["main_lo", "main_hi", "nominal", "p3_act", "krw"]].sum() / EOK
    org = org[(org.abs().sum(axis=1) > 0)].reset_index()
    org.round(4).to_csv(ROOT / "outputs" / "할당관세_관세지출_원산지.csv", index=False, encoding="utf-8-sig")
    print(cmp_.round(2).to_string(index=False))

    # 36의 d_quota와 w2 P3 감면 폭이 같은지
    d = con.execute(f"SELECT sum(imp_dlr * fx.krw_per_usd * d_quota / 100) FROM read_parquet('{PAN.as_posix()}/**/*.parquet', hive_partitioning=1) p "
                    f"JOIN read_csv_auto('{FX.as_posix()}') fx USING (yyyymm) WHERE role <> 'excl'").fetchone()[0]
    print(f"검증: 36 d_quota 합 {d / EOK:,.1f}억 대 w2 P3 합 {b.loc[~exc, 'e3_w2'].sum() / EOK:,.1f}억")
    print("조건부 P3 분할 몫:", {k: round(v, 4) for k, v in split_share.items()})
    print(f"P1 한계수량 묶음에 HS6로 넣은 코드×연도 {n_adopt}")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 50)
    print(out[["year", "p3_mfn_w1", "p3_pref_w1", "p3_excl_ub_w1", "p3_ineffective_w1", "p1_cap_w1", "p1_ub_w1", "p1_uncapped_w1",
               "p3_mfn_w2", "p1_ub_w2", "items_annex", "items_midyear", "codes_hs10"]].to_string(index=False))


if __name__ == "__main__":
    main()
