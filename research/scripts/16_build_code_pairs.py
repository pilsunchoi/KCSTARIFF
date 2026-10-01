"""
16_build_code_pairs.py — 첫째 질문의 관측 단위인 코드 쌍(물리적으로 비슷하면서 세율이 다른 HS10 두 개)의
목록을 만든다. 연구 문서 III.3절.

두 출처:
  별표  품목분류 적용기준 규칙 별표 43개 항목의 충족 호·반대편 호를 HS10으로 편다(ITEMS에 손으로 적은 범위·키워드).
        조합이 CAP을 넘는 항목은 쌍을 만들지 않고 양쪽 코드 목록만 후보 표에 남긴다(손으로 고른다).
  규칙  같은 HS6 안에서 2025년 실행세율(mfn)이 다른 코드끼리. 품명 어휘를 상태·가공·용도·소매·기타로 표시한다.

쌍마다: 2025년 격차, 원산지별(중국·미국·EU·아세안·베트남·인도) 격차의 연도 표준편차(식별이 작동하는 원산지),
두 코드가 함께 존재한 연도 범위, 세율 미확정 표시, 2022~2025년 수입액과 중국 몫, 신설 연도·사유.
손으로 채우는 열: 확인(Y/N), 변환비, 비고.

산출: research/outputs/코드쌍_목록.csv, 코드쌍_별표_후보.csv
"""
from __future__ import annotations

import itertools
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
BYEOLPYO = BYEOLPYO_DIR / "HSK_별표_2025.csv"
ORIG = ["cn", "us", "eu", "asean", "vn", "in"]
CAP = 40          # 별표 항목 하나의 쌍 조합 상한
CAP_ITEM = {35: 200}   # 항목별 예외
MIN_MUSD = 1.0    # 규칙 쌍: HS6 합계 수입액(2022~25, 백만 달러) 하한
MAX_CODES = 12    # 규칙 쌍: HS6 안 코드 수 상한

# 별표 항목: (번호, 품명, [A쪽 접두 목록], A 키워드(정규식, None=전부), [B쪽 접두], B 키워드)
# A = 충족 시 호, B = 반대편 호. 반대편이 없거나 「구성 성분별」인 항목은 뺐다(12·28·37~41·43).
ITEMS = [
    (1, "소뼈와 돼지뼈", ["0201", "0202", "0203"], "뼈", ["0506"], None),
    (2, "염장·염수장 쇠고기", ["0210"], "소|쇠", ["0201", "0202"], None),
    (3, "염장·염수장 수산물", ["0305", "0306", "0307"], "염장|염수|소금|젓", ["0302", "0303"], None),
    (4, "조기", ["0303"], "조기", ["0305"], "조기"),
    (5, "오징어", ["0307"], "오징어", ["1605"], "오징어"),
    (6, "밀크와 크림(농축·가당)", ["0402"], None, ["1901", "2106"], "분유|밀크|크림|유"),
    (7, "싹을 틔운 대두", ["070999"], None, ["1201"], None),
    (8, "냉동고추", ["0710807000"], None, ["090421", "090422"], None),
    (9, "염수로 일시 보존한 채소", ["0701", "0702", "0703", "0704", "0705", "0706", "0707", "0708", "0709"], None, ["0711"], None),
    (10, "라면스프 제조용 건조채소 혼합물", ["0712"], None, ["0904"], None),
    (11, "냉동대추", ["0811"], "대추", ["0813"], "대추"),
    (13, "카사바 분말과 전분", ["110620"], None, ["110814"], None),
    (14, "고구마 분말과 전분", ["110620"], None, ["1108191000"], None),
    (15, "부순 대두와 가루상 대두", ["120190"], None, ["120810"], None),
    (16, "부순 참깨와 가루상 참깨", ["120740"], None, ["120890"], None),
    (17, "비타민E 첨가 유지", ["1517"], None, ["1507", "1508", "1509", "1510", "1511", "1512", "1513", "1514", "1515"], None),
    (18, "견과류 함유 설탕과자", ["1704"], None, ["2008"], "견과|땅콩|아몬드|호두|밤|캐슈|피스타치오|헤이즐|마카다미아"),
    (19, "감자전분 조제품", ["1901"], None, ["1108130000"], None),
    (20, "전분 조제품(감자 제외)", ["1901"], None, ["1108"], None),
    (21, "찌거나 삶은 곡물", ["1904"], "찌거나|삶", ["1006"], None),
    (22, "볶은 곡물", ["1904", "2101"], "볶", ["1006", "1003", "1005"], None),
    (23, "튀긴 쌀", ["1904"], "튀긴|튀김", ["1006"], None),
    (24, "식초·초산으로 조제한 채소", ["2001"], None, ["0711"], None),
    (25, "감자가루·플레이크 조제품", ["2005"], "감자", ["1105"], None),
    (26, "찌거나 삶아서 건조한 팥", ["2005"], "팥", ["071332"], None),
    (27, "설탕으로 보존처리한 과실", ["2006"], None, ["2008"], None),
    (29, "볶은 땅콩", ["2008"], "땅콩", ["1202"], None),
    (30, "찌거나 삶은 대두", ["2008"], "대두|콩", ["1201"], None),
    (31, "볶거나 튀긴 대두", ["2008"], "대두|콩", ["1201"], None),
    (32, "볶은 헤이즐넛·피스타치오·마카다미아", ["200819"], None, ["080221", "080222", "080251", "080252", "080261", "080262"], None),
    (33, "고추다진양념", ["2103909050", "2103909090"], None, ["090421", "090422"], None),
    (34, "고추장 제조용 고춧가루 혼합조미료", ["2103"], "혼합조미료|고추장", ["0904220000"], None),
    (35, "변성전분 조제품", ["210690"], None, ["3505103000", "3505104010", "3505105010", "3505109010"], None),
    (36, "로열젤리 첨가 천연꿀", ["2106"], "로열|꿀", ["0409"], None),
    (42, "백잠사", ["5002001"], None, ["5002009000"], None),
]

VOCAB = [
    ("상태", r"냉동|건조|신선|냉장|염장|염수|훈제|말린|얼린|생|건|살아 있는"),
    ("가공", r"조제|볶|가공|분말|가루|전분|혼합|분획|정제|삶|찌|튀긴|부순|잘게|절단|껍질|탈지|농축|가당|발효"),
    ("용도", r"용(?![가-힣])|용의|용으로|제조용|사료용|식용|공업용|의료용|등록된|한정한다|법률|법에"),
    ("소매", r"소매|포장"),
    ("기타", r"^기타$|^그 밖의"),
]


def tier(v: str) -> int:
    """손 확인 우선순위: 1 상태·가공 어휘(물리적 형태), 2 기타만, 3 용도, 4 없음."""
    if "상태" in v or "가공" in v:
        return 1
    if v == "기타":
        return 2
    if "용도" in v:
        return 3
    return 4


def vocab_tag(a: str, b: str) -> str:
    tags = []
    for name, pat in VOCAB:
        if re.search(pat, a) or re.search(pat, b):
            tags.append(name)
    return "·".join(tags) if tags else "없음"


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect()
    con.execute(f"ATTACH '{TARIFF.as_posix()}' AS tr (READ_ONLY)")
    con.execute(f"ATTACH '{KCS.as_posix()}' AS s (READ_ONLY)")
    rate = con.sql("SELECT year, hs10, mfn, rate_undetermined, " + ", ".join(f"applied_{o}" for o in ORIG) + " FROM tr.fct_applied_rate").df()
    imp = con.sql("""
        SELECT hs10, sum(imp_dlr)/1e6 musd, sum(CASE WHEN stat_cd='CN' THEN imp_dlr ELSE 0 END)/nullif(sum(imp_dlr),0) cn_share,
               sum(imp_wgt)/1e3 ton
        FROM s.fact_trade WHERE yyyymm BETWEEN 202201 AND 202512 GROUP BY 1""").df()
    rev = con.sql("SELECT hs10, rev, effective_ym, reason FROM s.dim_hsk_revision WHERE change='신설'").df()
    rev = rev.sort_values("effective_ym").drop_duplicates("hs10", keep="last")
    con.close()
    names = pd.read_csv(BYEOLPYO, dtype=str).rename(columns={"code": "hs10"})
    names["leaf"] = names.leaf.str.replace(r"\s+", " ", regex=True)
    names["path"] = names.path.fillna("").str.replace(r"\s+", " ", regex=True)
    return rate, imp, rev, names


def code_table(rate: pd.DataFrame, imp: pd.DataFrame, rev: pd.DataFrame, names: pd.DataFrame) -> pd.DataFrame:
    r25 = rate[rate.year == 2025][["hs10", "mfn", "rate_undetermined"]]
    span = rate.groupby("hs10").agg(first_year=("year", "min"), last_year=("year", "max"), undet_any=("rate_undetermined", "max")).reset_index()
    t = names.merge(r25, on="hs10", how="left").merge(span, on="hs10", how="left").merge(imp, on="hs10", how="left").merge(rev, on="hs10", how="left")
    t["musd"] = t.musd.fillna(0).round(2)
    t["ton"] = t.ton.fillna(0).round(1)
    t["cn_share"] = t.cn_share.round(3)
    return t


def gap_by_origin(rate: pd.DataFrame, h: str, l: str) -> dict:
    a = rate[rate.hs10 == h].set_index("year")
    b = rate[rate.hs10 == l].set_index("year")
    yrs = a.index.intersection(b.index)
    out = {"years_both": f"{yrs.min()}~{yrs.max()}" if len(yrs) else "", "n_years": len(yrs)}
    for o in ORIG:
        g = (a.loc[yrs, f"applied_{o}"] - b.loc[yrs, f"applied_{o}"]).dropna()
        out[f"gap_{o}_2025"] = round(float(g.get(2025, np.nan)), 1) if 2025 in g.index else np.nan
        out[f"gap_{o}_sd"] = round(float(g.std()), 1) if len(g) > 1 else np.nan
    out["origins_varying"] = "·".join(o for o in ORIG if pd.notna(out[f"gap_{o}_sd"]) and out[f"gap_{o}_sd"] > 1.0)
    return out


def make_pair(t: pd.DataFrame, rate: pd.DataFrame, h: str, l: str, source: str, item_no, item_name) -> dict:
    H = t.set_index("hs10").loc[h]
    L = t.set_index("hs10").loc[l]
    d = {"source": source, "item_no": item_no, "item": item_name,
         "hs10_high": h, "name_high": H.leaf, "path_high": H.path[:60], "mfn_high": H.mfn,
         "hs10_low": l, "name_low": L.leaf, "path_low": L.path[:60], "mfn_low": L.mfn,
         "gap_mfn_2025": round(float(H.mfn - L.mfn), 1) if pd.notna(H.mfn) and pd.notna(L.mfn) else np.nan,
         "same_hs6": h[:6] == l[:6], "vocab": vocab_tag(str(H.leaf), str(L.leaf)), "tier": tier(vocab_tag(str(H.leaf), str(L.leaf))),
         "musd_high": H.musd, "musd_low": L.musd, "cn_share_high": H.cn_share, "cn_share_low": L.cn_share,
         "undetermined": bool(H.undet_any) or bool(L.undet_any),
         "new_high": f"{H.rev}({H.reason})" if pd.notna(H.rev) else "", "new_low": f"{L.rev}({L.reason})" if pd.notna(L.rev) else ""}
    d.update(gap_by_origin(rate, h, l))
    d.update({"확인": "", "변환비": "", "비고": ""})
    return d


def side_codes(t: pd.DataFrame, prefixes: list[str], kw: str | None) -> pd.DataFrame:
    m = t[t.hs10.str.startswith(tuple(prefixes))]
    if kw:
        m = m[m.leaf.str.contains(kw, regex=True) | m.path.str.contains(kw, regex=True)]
    return m


def annex_pairs(t: pd.DataFrame, rate: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    pairs, cands = [], []
    for no, name, pa, ka, pb, kb in ITEMS:
        A, B = side_codes(t, pa, ka), side_codes(t, pb, kb)
        n = len(A) * len(B)
        for side, df in (("A", A), ("B", B)):
            for _, r in df.iterrows():
                cands.append({"item_no": no, "item": name, "side": side, "hs10": r.hs10, "leaf": r.leaf, "path": r.path[:60],
                              "mfn": r.mfn, "musd": r.musd, "cn_share": r.cn_share, "n_combos": n, "paired": n <= CAP_ITEM.get(no, CAP)})
        if n == 0 or n > CAP_ITEM.get(no, CAP):
            continue
        for a, b in itertools.product(A.hs10, B.hs10):
            ma, mb = t.set_index("hs10").mfn.get(a), t.set_index("hs10").mfn.get(b)
            if pd.isna(ma) or pd.isna(mb) or ma == mb:
                continue
            h, l = (a, b) if ma > mb else (b, a)
            pairs.append(make_pair(t, rate, h, l, "별표", no, name))
    return pairs, cands


def rule_pairs(t: pd.DataFrame, rate: pd.DataFrame) -> list[dict]:
    x = t[t.mfn.notna()].assign(hs6=t.hs10.str[:6])
    g = x.groupby("hs6").agg(n=("hs10", "size"), nr=("mfn", "nunique"), musd=("musd", "sum"))
    keep = g[(g.nr > 1) & (g.n <= MAX_CODES) & (g.musd >= MIN_MUSD)].index
    out = []
    for hs6, grp in x[x.hs6.isin(keep)].groupby("hs6"):
        for a, b in itertools.combinations(grp.itertuples(index=False), 2):
            if a.mfn == b.mfn:
                continue
            h, l = (a, b) if a.mfn > b.mfn else (b, a)
            out.append(make_pair(t, rate, h.hs10, l.hs10, "규칙", "", ""))
    return out


def main() -> None:
    rate, imp, rev, names = load()
    t = code_table(rate, imp, rev, names)
    ap, cands = annex_pairs(t, rate)
    rp = rule_pairs(t, rate)
    pairs = pd.DataFrame(ap + rp)
    # 별표 쌍과 겹치는 규칙 쌍은 별표 쪽만 남긴다
    key = pairs.hs10_high + "-" + pairs.hs10_low
    dup = key.duplicated(keep="first") & (pairs.source == "규칙")
    pairs = pairs[~dup].reset_index(drop=True)
    pairs.insert(0, "pair_id", [f"P{i+1:04d}" for i in range(len(pairs))])
    OUT.mkdir(exist_ok=True)
    pairs.to_csv(OUT / "코드쌍_목록.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(cands).to_csv(OUT / "코드쌍_별표_후보.csv", index=False, encoding="utf-8-sig")
    print(f"쌍 {len(pairs)}개: 별표 {int((pairs.source=='별표').sum())}, 규칙 {int((pairs.source=='규칙').sum())} (규칙 중복 제거 {int(dup.sum())})")
    print("별표 항목별 쌍 수:", pairs[pairs.source == "별표"].groupby("item_no").size().to_dict())
    big = pd.DataFrame(cands).drop_duplicates(["item_no"]).query("n_combos > @CAP")[["item_no", "item", "n_combos"]]
    print("조합이 상한을 넘어 손으로 고를 항목:", big.to_dict("records"))
    print("규칙 쌍 우선순위(1 상태·가공/2 기타/3 용도/4 없음):", pairs[pairs.source == "규칙"].tier.value_counts().sort_index().to_dict())
    print("규칙 쌍 어휘 분포:", pairs[pairs.source == "규칙"].vocab.value_counts().head(12).to_dict())
    print("격차 ≥100%p 쌍:", int((pairs.gap_mfn_2025 >= 100).sum()), " 격차 움직이는 원산지 있음:", int((pairs.origins_varying != "").sum()))
    print("미확정 포함 쌍:", int(pairs.undetermined.sum()))


if __name__ == "__main__":
    main()
