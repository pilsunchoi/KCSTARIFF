"""
02_build_applied_rate.py — 연도×HS10의 실행세율(applicable rate)을 만든다.

근거: 관세법 제50조(세율 적용의 우선순위), FTA 관세특례법 제5조, 양허관세 규정 제6조.
조문 원문과 세율 구분 코드의 대응은 docs/applied-rate-legal-basis.md.

규칙(연구 문서 IV.1절):
  기본   = A(기본세율). 잠정세율은 자료에 없다.
  3순위  = P3(할당관세, 수입전량)가 있으면 P3, 아니면 L(조정관세)가 있으면 L, 아니면 기본.
           P1(할당관세 물량이내 추천)은 추천이 있어야 하므로 표시만 한다.
  2순위  = C(WTO 협정세율)·F(국제협력관세)는 3순위보다 낮을 때만 우선(제50조③ 본문).
           W2(농림축산물 양허관세, 별표 1의 나)는 기본세율보다 높아도 우선(제50조③ 단서)하되
           할당관세(P3)가 있으면 그것을 따른다. W1(추천)은 추천이 있어야 하므로 표시만 한다.
  1순위  = I(덤핑방지)·T1·T2(특별긴급)는 원산지·물량 조건이 붙는 추가 관세라 표시만 한다.
  협정   = FTA 일곱 상대(FCN1·FEU1·FUS1·FAS1·FIN1·FVN1·FCA1)와 APTA(E1·E2·E3)는
           무협정 적용세율보다 낮을 때만 적용(특례법 제5조①, 제50조③).
  연중 변경 = 구간별 세율을 그해 유효 일수로 가중평균한다(rate_*), 1월 1일 세율도 둔다(*_jan).
  발효일   = 주요세율보기 화면의 협정세율 기간은 발효 해의 1월 1일부터 잡혀 있다(한-EU 2011, 한-미 2012,
             한-중·한-베트남 2015). 협정마다 한국의 적용 시작일(ENTRY)로 기간을 자르고, 발효 해의 협정 적용세율은
             발효 전 날은 무협정 세율, 발효 뒤 날은 협정 적용세율로 일수 가중한다(2026-10-03). r_*(협정)는 적용 중인
             날의 평균이고, 1월 1일에 아직 적용 전이면 j_*(협정)는 비운다.
  할당관세 = 관세율표 화면의 P3는 그해에 한 번이라도 지정된 품목에 기간 없이 붙어 있다. 할당관세 규정의 판본별 별표로
             만든 P3 적용 구간(data/quota/quota_p3_periods.csv, research/scripts/30~34)으로 P3 행을 바꾸고, 무협정 세율은
             P3가 적용된 날(P3 우선)과 아닌 날(조정·기본·WTO·양허 규칙)의 값을 일수로 가중한다(p3_share = P3 적용 일수 몫;
             mfn_regime은 더 많은 날의 구분, 2026-10-03). 1월 1일에 P3가 적용 중이 아니면 j_P3는 비운다.
  종량 하한 = 선택 세율("N% 또는 M원")이 있는 규정에서 M/N(원/kg). 격차 변수에는 종가세율만 쓴다.

산출:
  outputs/fct_applied_rate.parquet (연도×HS10)
  outputs/dim_origin_regime.csv     (원산지→협정)
  data/processed/kcstariff.duckdb 의 fct_applied_rate, dim_origin_regime (--load 를 주면 적재)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import os
ROOT = Path(__file__).resolve().parent.parent
TARIFF = ROOT / "data" / "processed" / "kcstariff.duckdb"
KCS = Path(os.environ.get("KCSDB2_PATH", ROOT.parent / "KCSDB2" / "data" / "processed" / "kcsdb.duckdb"))   # 있으면 커버리지 검증
OUT = ROOT / "outputs"
P3_PERIODS = ROOT / "data" / "quota" / "quota_p3_periods.csv"

FTA = {"FCN1": "cn", "FEU1": "eu", "FUS1": "us", "FAS1": "asean", "FIN1": "in", "FVN1": "vn", "FCA1": "ca"}

# 협정별 한국의 적용 시작일(아세안은 첫 회원국들의 날짜; 회원국별 날짜는 ORIGIN_REGIME의 from_date)
ENTRY = {"FAS1": "2007-06-01", "FIN1": "2010-01-01", "FEU1": "2011-07-01", "FUS1": "2012-03-15",
         "FCA1": "2015-01-01", "FCN1": "2015-12-20", "FVN1": "2015-12-20"}

# 원산지(관세청 stat_cd = ISO2) → 협정. (regime, from_year, to_year, from_date)
#   from_date = 한국이 그 원산지에 협정세율을 적용하기 시작한 날. from_year = 그 협정세율이 이 자료에서 처음 적용되는 해
#   (발효가 연중이면 발효 해; 한-아세안은 2007년 세율이 포털에 없어 2008년부터).
#   영국은 2021년부터 한-영 협정이 한-EU 양허 일정을 이어받았으므로 EU 세율을 계속 쓴다(2026-10-03).
#   세율 자료에 없는 협정(칠레·EFTA·페루·튀르키예·호주·뉴질랜드·콜롬비아·중미·RCEP·이스라엘·인도네시아/필리핀 양자·UAE)의
#   상대국은 이 표에 없다 — 무협정 원산지로 쓰기 전에 연구 문서 IV.5절을 볼 것.
EU27 = ["AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"]
ASEAN = ["BN", "KH", "ID", "LA", "MY", "MM", "PH", "SG", "TH", "VN"]
APTA_E1 = ["CN", "IN", "LK", "MN"]      # 일반 협정세율
ASEAN_DATE = {"SG": "2007-06-01", "MY": "2007-06-01", "VN": "2007-06-01", "MM": "2007-06-01", "ID": "2007-06-01",
              "PH": "2008-01-01", "BN": "2008-07-01", "LA": "2008-10-01", "KH": "2008-11-01", "TH": "2010-01-01"}
ORIGIN_REGIME = (
    [("CN", "FCN1", 2015, 9999, "2015-12-20"), ("IN", "FIN1", 2010, 9999, "2010-01-01"), ("US", "FUS1", 2012, 9999, "2012-03-15"),
     ("VN", "FVN1", 2015, 9999, "2015-12-20"), ("CA", "FCA1", 2015, 9999, "2015-01-01")]
    + [(c, "FEU1", 2011, 9999, "2011-07-01") for c in EU27 if c != "HR"] + [("HR", "FEU1", 2013, 9999, "2013-07-01"), ("GB", "FEU1", 2011, 9999, "2011-07-01")]
    + [(c, "FAS1", max(2008, int(ASEAN_DATE[c][:4])), 9999, ASEAN_DATE[c]) for c in ASEAN]
    + [(c, "E1", 2007, 9999, "") for c in APTA_E1] + [("BD", "E2", 2007, 9999, ""), ("LA", "E3", 2007, 9999, "")]
)


def load_rates() -> pd.DataFrame:
    con = duckdb.connect()
    con.execute(f"ATTACH '{TARIFF.as_posix()}' AS tr (READ_ONLY)")
    df = con.sql("SELECT year, hs10, rate_cd, rate_txt, adval, specific, valid_from, valid_to FROM tr.tariff_rate").df()
    con.close()
    df["valid_from"] = pd.to_datetime(df.valid_from)
    df["valid_to"] = pd.to_datetime(df.valid_to)
    # 협정세율은 적용 시작일 전으로 잡힌 기간을 자른다
    ent = pd.to_datetime(df.rate_cd.map(ENTRY))
    ystart = pd.to_datetime(df.year.astype(str) + "-01-01"); yend = pd.to_datetime(df.year.astype(str) + "-12-31")
    vt = df.valid_to.fillna(yend)
    drop = ent.notna() & (vt < ent)
    df = df[~drop].copy(); ent = ent[~drop]; ystart = ystart[~drop]
    vf = df.valid_from.fillna(ystart)
    df["valid_from"] = np.where(ent.notna() & (vf < ent), ent, df.valid_from)
    df["valid_from"] = pd.to_datetime(df.valid_from)
    # 할당관세(P3): 포털의 연 단위 행을 별표 기반 적용 구간으로 바꾼다. 구간 파일에 없는 해·코드의 P3는 적용 날이 없다.
    if P3_PERIODS.exists():
        per = pd.read_csv(P3_PERIODS, dtype={"hs10": str})
        txt = df[df.rate_cd == "P3"].drop_duplicates(["year", "hs10"]).set_index(["year", "hs10"]).rate_txt
        per = per.assign(rate_cd="P3", specific=np.nan, valid_from=pd.to_datetime(per.valid_from), valid_to=pd.to_datetime(per.valid_to),
                         rate_txt=[txt.get((y, h), f"{a:g}%") for y, h, a in zip(per.year, per.hs10, per.adval)])
        df = pd.concat([df[df.rate_cd != "P3"], per[df.columns]], ignore_index=True)
    return df


def weight_by_days(df: pd.DataFrame) -> pd.DataFrame:
    """(year, hs10, rate_cd)마다 유효 일수 가중 종가세율, 1월 1일 세율, 종량세(원/kg)를 만든다."""
    ystart = pd.to_datetime(df.year.astype(str) + "-01-01")
    yend = pd.to_datetime(df.year.astype(str) + "-12-31")
    vf = df.valid_from.fillna(ystart).clip(lower=ystart)
    vt = df.valid_to.fillna(yend).clip(upper=yend)
    df = df.assign(days=(vt - vf).dt.days.clip(lower=0) + 1, vf=vf)
    has = df.adval.notna()
    df["wnum"] = np.where(has, df.adval.fillna(0) * df.days, 0.0)
    df["wden"] = np.where(has, df.days, 0)
    keys = ["year", "hs10", "rate_cd"]
    g = df.groupby(keys, sort=False)
    out = g.agg(wnum=("wnum", "sum"), wden=("wden", "sum"), days=("days", "sum"), specific=("specific", "max"), txt=("rate_txt", "first")).reset_index()
    out["rate"] = np.where(out.wden > 0, out.wnum / out.wden.replace(0, np.nan), np.nan)
    # 1월 1일 세율: 시작일이 가장 이른 행(종가 있는 것 우선)
    first = df[has].sort_values(keys + ["vf"]).drop_duplicates(keys)
    first = first.assign(adval=first.adval.where((first.rate_cd != "P3") | (first.vf == ystart[first.index])))   # P3는 1월 1일에 적용 중일 때만
    first = first[keys + ["adval"]].rename(columns={"adval": "rate_jan"})
    out = out.merge(first, on=keys, how="left")
    return out.drop(columns=["wnum", "wden"])


def build(df: pd.DataFrame) -> pd.DataFrame:
    w = weight_by_days(df)
    rate = w.pivot(index=["year", "hs10"], columns="rate_cd", values="rate")
    jan = w.pivot(index=["year", "hs10"], columns="rate_cd", values="rate_jan")
    spec = w.pivot(index=["year", "hs10"], columns="rate_cd", values="specific")
    txt = w.pivot(index=["year", "hs10"], columns="rate_cd", values="txt")
    days = w.pivot(index=["year", "hs10"], columns="rate_cd", values="days")
    t = pd.DataFrame(index=rate.index)
    for cd in ["A", "C", "F", "L", "P3", "W2", "W1", "E1", "E2", "E3"] + list(FTA):
        t[f"r_{cd}"] = rate.get(cd)
        t[f"j_{cd}"] = jan.get(cd)
    for cd in ["A", "C", "W2"]:
        t[f"spec_{cd}"] = spec.get(cd)
        t[f"txt_{cd}"] = txt.get(cd)
    for cd in ["I", "T1", "T2", "P1", "W1", "D", "G1", "G2"]:
        t[f"has_{cd}"] = rate.get(cd).notna() if cd in rate.columns else False

    # ---- 무협정 적용세율(MFN, 제50조) ----
    # P3가 적용된 날(with)과 아닌 날(without)을 따로 계산해 일수로 가중한다.
    yr0 = t.index.get_level_values("year")
    ndays = pd.Series(np.where(yr0 % 4 == 0, 366, 365), index=t.index)
    t["p3_share"] = (days["P3"] / ndays).clip(upper=1).fillna(0.0) if "P3" in days.columns else 0.0
    tier2 = t[["r_C", "r_F"]].min(axis=1)
    reg2 = np.where(t.r_C.notna() & (t.r_C <= t.r_F.fillna(np.inf)), "C", "F")

    def rule(domestic, regime, allow_w2):
        use2 = tier2.notna() & (domestic.isna() | (tier2 < domestic))
        m = domestic.where(~use2, tier2)
        rg = np.where(use2, reg2, regime)
        if allow_w2:                                   # 양허 농림축산물(W2): 기본세율에 우선. 할당관세(P3)가 적용 중이면 그것.
            usew = t.r_W2.notna()
            m = m.where(~usew, t.r_W2)
            rg = np.where(usew, "W2", rg)
        return m, rg
    m_without, rg_without = rule(t.r_L.where(t.r_L.notna(), t.r_A), np.where(t.r_L.notna(), "L", "A"), True)
    m_with, rg_with = rule(t.r_P3, np.full(len(t), "P3", dtype=object), False)
    sh = t.p3_share
    t["mfn"] = np.where(sh >= 1, m_with, np.where(sh > 0, sh * m_with + (1 - sh) * m_without, m_without))
    t["mfn"] = t.mfn.where(t.mfn.notna(), m_without)
    t["mfn_regime"] = np.where(sh >= 0.5, rg_with, rg_without)
    # 1월 1일 기준 MFN(같은 규칙)
    domestic_j = t.j_P3.where(t.j_P3.notna(), t.j_L.where(t.j_L.notna(), t.j_A))
    tier2_j = t[["j_C", "j_F"]].min(axis=1)
    use2_j = tier2_j.notna() & (domestic_j.isna() | (tier2_j < domestic_j))
    mfn_j = domestic_j.where(~use2_j, tier2_j)
    usew_j = t.r_W2.notna() & t.j_P3.isna()
    t["mfn_jan"] = mfn_j.where(~usew_j, t.j_W2)

    # ---- 협정·APTA 적용세율: 무협정보다 낮을 때만. 발효 해는 발효 전 날을 무협정 세율로 일수 가중 ----
    yr = t.index.get_level_values("year")
    for cd, name in FTA.items():
        r = t[f"r_{cd}"]
        a = np.where(r.notna() & (r < t.mfn), r, t.mfn)
        e = pd.Timestamp(ENTRY[cd]); ndays = np.where(pd.Series(yr).astype(int) % 4 == 0, 366, 365)
        share = np.where(yr < e.year, 0.0, np.where(yr > e.year, 1.0, ((pd.Timestamp(f"{e.year}-12-31") - e).days + 1) / ndays))
        t[f"applied_{name}"] = share * a + (1 - share) * t.mfn
        t[f"inforce_{name}"] = share                                    # 그해 협정이 적용된 날의 몫
        if e != pd.Timestamp(f"{e.year}-01-01"):
            t.loc[yr == e.year, f"j_{cd}"] = np.nan                     # 1월 1일에는 아직 적용 전
    for cd, name in [("E1", "apta"), ("E2", "apta_bd"), ("E3", "apta_la")]:
        r = t[f"r_{cd}"]
        t[f"applied_{name}"] = np.where(r.notna() & (r < t.mfn), r, t.mfn)
    # 중국·인도는 FTA와 APTA 중 낮은 쪽, 베트남·라오스는 FTA와 아세안 중 낮은 쪽
    t["applied_cn"] = np.minimum(t.applied_cn, t.applied_apta)
    t["applied_in"] = np.minimum(t.applied_in, t.applied_apta)
    t["applied_vn"] = np.minimum(t.applied_vn, t.applied_asean)
    t["applied_la"] = np.minimum(t.applied_asean, t.applied_apta_la)

    # ---- 종량 하한(원/kg): MFN 규정이 선택 세율이면 종량/종가 ----
    spec_used = np.where(t.mfn_regime == "W2", t.spec_W2, np.where(t.mfn_regime == "C", t.spec_C, np.where(t.mfn_regime == "A", t.spec_A, np.nan)))
    spec_used = np.where(spec_used > 0, spec_used, np.nan)   # "N% 또는 0원"은 종량 대안이 아니다
    t["specific_won_kg"] = spec_used
    t["floor_won_kg"] = np.where((t.mfn > 0) & pd.notna(spec_used), spec_used / (t.mfn / 100.0), np.nan)
    t = t.reset_index()
    # 세율 미확정: 종량세만 있는 코드(영화필름), 두 별표에 함께 오른 코드(인삼 기타),
    # 관세화(2015) 전의 쌀(수입이 시장접근물량으로 제한되어 물량 밖 세율이 없다)
    t["undetermined_reason"] = ""
    t.loc[t.mfn.isna(), "undetermined_reason"] = "specific_only"
    t.loc[t.hs10 == "1211209900", "undetermined_reason"] = "two_annexes"
    t.loc[t.hs10.str.startswith("1006") & (t.year < 2015), "undetermined_reason"] = "rice_pre_tariffication"
    t["rate_undetermined"] = t.undetermined_reason != ""
    return t


def validate(t: pd.DataFrame) -> None:
    known = [  # (year, hs10, column, expected)
        (2025, "2103909050", "mfn", 45.0), (2025, "2103909050", "applied_cn", 44.5),
        (2025, "0904210000", "mfn", 270.0), (2025, "0904210000", "applied_cn", 270.0),
        (2025, "0710807000", "mfn", 27.0),
        (2025, "0910111000", "mfn", 377.3),
        (2025, "0710809090", "mfn", 27.0),
        (2023, "2103909090", "applied_eu", (11.2 * 181 + 8.4 * 184) / 365),
    ]
    bad = []
    for y, h, col, exp in known:
        row = t[(t.year == y) & (t.hs10 == h)]
        got = float(row[col].iloc[0]) if len(row) else np.nan
        if not np.isclose(got, exp, atol=0.05):
            bad.append((y, h, col, exp, got))
    if bad:
        for b in bad:
            print("  FAIL", b)
        raise SystemExit("알려진 값과 어긋난다")
    print(f"검증: 알려진 값 {len(known)}건 통과")
    if not KCS.exists():
        print("수입액 커버리지 검증은 KCSDB2가 없어 건너뛴다"); return
    con = duckdb.connect()
    con.execute(f"ATTACH '{KCS.as_posix()}' AS s (READ_ONLY)")
    con.register("t", t[["year", "hs10", "mfn"]])
    cov = con.sql("""
        WITH imp AS (SELECT yyyymm//100 yr, hs10, sum(imp_dlr) v FROM s.fact_trade GROUP BY 1,2)
        SELECT imp.yr, round(100.0*sum(CASE WHEN t.mfn IS NOT NULL THEN v ELSE 0 END)/sum(v),2) pct_rate,
               round(100.0*sum(CASE WHEN t.hs10 IS NOT NULL THEN v ELSE 0 END)/sum(v),2) pct_code
        FROM imp LEFT JOIN t ON t.year=imp.yr AND t.hs10=imp.hs10 GROUP BY 1 ORDER BY 1""").df()
    print("수입액 커버리지(%): 코드 있음 / 종가 실행세율 있음")
    print(cov.to_string(index=False))
    cov.to_csv(OUT / "실행세율_커버리지.csv", index=False, encoding="utf-8-sig")
    con.close()


def write_legal_sample(t: pd.DataFrame) -> None:
    """법령 대조 표본(2025년): 파일럿 코드 전부 + 별표 43개 항목의 호마다 2개 + 무작위 100개. 사람이 법령과 대조해 채우는 표."""
    import re
    rule = OUT / "분류기준_규칙_별표.csv"   # 연구 저장소의 표. 없으면 무작위 표본만 만든다
    hs4 = set()
    if rule.exists():
        r = pd.read_csv(rule, dtype=str)
        for c in ["충족 시 호", "반대편 호"]:
            for v in r[c].dropna():
                hs4 |= {h[:4] for h in re.findall(r"\d{4}", v)}
    # 파일럿 코드는 전부, 별표의 호마다 무작위 2개
    codes = {"0904210000", "0904220000", "0710807000", "2103909050", "2103909090", "0910111000", "0910112000",
             "0910113000", "0910123000", "0710809090", "0813400000", "0810909000", "0811909000", "1211209900"}
    y = t[t.year == 2025]
    pilot = y[y.hs10.isin(codes)].assign(sample="pilot")
    head = y[y.hs10.str[:4].isin(hs4) & ~y.hs10.isin(codes)].groupby(y.hs10.str[:4], group_keys=False).apply(lambda g: g.sample(min(2, len(g)), random_state=1)).assign(sample="heading")
    rest = y[~y.hs10.isin(codes) & ~y.hs10.isin(head.hs10)].sample(100, random_state=20260912).assign(sample="random")
    pair = pd.concat([pilot, head])
    cols = ["sample", "year", "hs10", "r_A", "r_C", "r_W2", "r_L", "r_P3", "mfn", "mfn_regime", "specific_won_kg", "floor_won_kg",
            "applied_cn", "applied_us", "applied_eu", "applied_asean", "applied_vn", "has_W1", "has_P1", "has_I", "has_T1", "has_T2", "rate_undetermined"]
    out = pd.concat([pair, rest])[cols].sort_values(["sample", "hs10"])
    out["법령_확인세율"] = ""
    out["확인_출처"] = ""
    out["비고"] = ""
    out.to_csv(OUT / "실행세율_법령대조.csv", index=False, encoding="utf-8-sig")
    print(f"법령 대조 표본: 파일럿 {len(pilot)} + 별표 호별 {len(head)} + 무작위 {len(rest)} → outputs/실행세율_법령대조.csv")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true", help="kcstariff.duckdb 에 적재")
    args = ap.parse_args()
    df = load_rates()
    t = build(df)
    validate(t)
    OUT.mkdir(exist_ok=True)
    t.to_parquet(OUT / "fct_applied_rate.parquet", index=False)
    dim = pd.DataFrame(ORIGIN_REGIME, columns=["stat_cd", "regime", "from_year", "to_year", "from_date"])
    dim.to_csv(OUT / "dim_origin_regime.csv", index=False, encoding="utf-8-sig")
    print(f"fct_applied_rate {len(t):,}행, 미확정 {int(t.rate_undetermined.sum()):,}행 {t[t.rate_undetermined].undetermined_reason.value_counts().to_dict()}, 종량 하한 있음 {int(t.floor_won_kg.notna().sum()):,}행")
    print("MFN 규정 분포:", t.mfn_regime.value_counts().to_dict())
    write_legal_sample(t)
    if args.load:
        con = duckdb.connect(str(TARIFF))
        con.execute(f"CREATE OR REPLACE TABLE fct_applied_rate AS SELECT * FROM read_parquet('{(OUT / 'fct_applied_rate.parquet').as_posix()}')")
        con.execute(f"CREATE OR REPLACE TABLE dim_origin_regime AS SELECT * FROM read_csv_auto('{(OUT / 'dim_origin_regime.csv').as_posix()}')")
        con.close()
        print("적재 완료")


if __name__ == "__main__":
    main()
