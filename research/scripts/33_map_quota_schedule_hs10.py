"""
33_map_quota_schedule_hs10.py — 할당관세 시간표(scripts/32)의 구간을 HSK 10단위 코드에 대응시킨다(2026-10-03).

입력: outputs/할당관세_시간표.csv, 세율 DB(../data/processed/kcstariff.duckdb)의 tariff_rate(P1·P3)·tariff_code(품명).
산출: outputs/할당관세_시간표_hs10.csv — 코드×구간 한 행.
  year, hs10, valid_from, valid_to(그해 안으로 자름), rate, rate_num, quota, spec, name_path, rate_cd(그해 세율 DB의 P1·P3),
  db_adval(그해 세율 DB의 할당 세율), method(single·scored·tie), score, spell(시간표 행 번호)
      outputs/할당관세_시간표_hs10_검증.csv — 연도별 대응 결과 요약.
방법: 세율 DB의 할당 코드가 기준이다(연 단위 표의 할당 HS6 집합이 그해 별표의 합집합과 같다는 것을 확인했다 — 기록 6·9절).
해마다 별표 구간의 소호(한 자리 소호면 호+그 자리)로 그해 세율 DB의 P1·P3 코드를 후보로 모으고, 그 소호 안의 별표 품목
(품명 경로·규격이 같은 구간의 묶음)이 하나면 후보 전부를 그 품목에 붙인다(single). 품목이 여럿이면 코드마다 품목을 점수로
고른다(scored): 세율이 세율 DB의 그해 할당 세율과 같으면 1, 그리고 코드 품명(말단)과 품명 경로의 각 단계·규격 사이 문자열
유사도의 최댓값(0~1). 최고점이 같은 품목이 여럿이면 모두 붙이고 tie로 둔다. 어느 코드에도 붙지 않은 품목은 그 소호에서 점수가 가장 높은 코드에
붙인다(item_best; 한 코드 안에 별표 품목이 여럿인 경우). 같은 코드에 날짜가 겹치고 세율이 다른 구간은 conflict로 표시한다. 구간은 연도 경계에서 자른다(코드가 해마다 바뀐다).
P1·P3 구분은 별표의 한계수량이 아니라 세율 DB에서 가져온다 — 한계수량이 빈 행이 P1·P3 어느 쪽도 될 수 있다(기록 9절).
"""

import re
from difflib import SequenceMatcher
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT.parent / "data" / "processed" / "kcstariff.duckdb"


def norm(s: str) -> str:
    s = re.sub(r"\([^)]*[一-鿿][^)]*\)", "", s)            # 한자 병기 괄호
    return re.sub(r"[\s·ㆍ,\.]", "", s)


def nums(rate: str) -> set:
    return {float(x) for x in re.findall(r"\d+(?:\.\d+)?", rate)}


def sim(code_name: str, path: str, spec: str) -> float:
    c = norm(code_name)
    if not c:
        return 0.0
    parts = [p for p in path.split(" > ") if p] + ([spec] if spec else [])
    best = 0.0
    for p in parts:
        p = norm(re.sub(r"^(\d+\.|[가-힣]\.|\(\d+\)|\([가-힣]\)|\d+\)|[가-힣]\))\s*", "", p))
        if p:
            best = max(best, SequenceMatcher(None, c, p).ratio())
    return best


def main() -> None:
    s = pd.read_csv(ROOT / "outputs" / "할당관세_시간표.csv", dtype=str).fillna("")
    s["spell"] = s.index
    s["vf"], s["vt"] = pd.to_datetime(s.valid_from), pd.to_datetime(s.valid_to)
    s["item"] = s.hs4 + "|" + s["sub"] + "|" + s.name_path.str.replace(r"\s+", "", regex=True) + "|" + s.spec.str.replace(r"\s+", "", regex=True)
    s["prefix"] = s.hs4 + s["sub"]
    con = duckdb.connect(str(DB), read_only=True)
    db = con.execute("""select r.year, r.hs10, string_agg(distinct r.rate_cd, ',' order by r.rate_cd) rate_cd,
                               min(r.adval) db_adval, any_value(c.name_ko) name_ko
                        from tariff_rate r left join tariff_code c using (year, hs10)
                        where r.rate_cd in ('P1','P3') group by 1, 2""").df()
    out, summ = [], []
    for y in range(2007, 2027):
        a, b = pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31")
        sy = s[(s.vf <= b) & (s.vt >= a)]
        dy = db[db.year == y]
        n_single = n_scored = n_tie = n_nomatch = 0
        used_items = set()
        for pre, g in sy.groupby("prefix"):
            cand = dy[dy.hs10.str.startswith(pre)]
            items = g.groupby("item")
            if cand.empty:
                continue
            for c in cand.itertuples(index=False):
                if items.ngroups == 1:
                    pick, method, score = [g.item.iloc[0]], "single", None
                else:
                    sc = {}
                    for it, gi in items:
                        r_ok = c.db_adval == c.db_adval and any(abs(x - c.db_adval) < 1e-9 for rt in gi.rate for x in nums(rt))
                        sc[it] = (1.0 if r_ok else 0.0) + sim(c.name_ko or "", gi.name_path.iloc[-1], gi.spec.iloc[-1])
                    top = max(sc.values())
                    pick = [it for it, v in sc.items() if abs(v - top) < 1e-9]
                    method, score = ("tie" if len(pick) > 1 else "scored"), round(top, 3)
                n_single += method == "single"; n_scored += method == "scored"; n_tie += method == "tie"
                for it in pick:
                    used_items.add(it)
                    for r in g[g.item == it].itertuples(index=False):
                        out.append({"year": y, "hs10": c.hs10, "valid_from": max(r.vf, a).date(), "valid_to": min(r.vt, b).date(),
                                    "rate": r.rate, "rate_num": r.rate_num, "quota": r.quota, "spec": r.spec, "name_path": r.name_path,
                                    "rate_cd": c.rate_cd, "db_adval": c.db_adval, "method": method, "score": score, "spell": r.spell})
        # 어느 코드에도 붙지 않은 품목은 그 소호 후보 가운데 점수가 가장 높은 코드에 붙인다(item_best) —
        # 한 코드 안에 별표 품목이 여럿인 경우(규격·비중 구분 등)
        for it in set(sy.item) - used_items:
            gi = sy[sy.item == it]
            cand = dy[dy.hs10.str.startswith(gi.prefix.iloc[0])]
            if cand.empty:
                continue
            sc = [((1.0 if c.db_adval == c.db_adval and any(abs(x - c.db_adval) < 1e-9 for rt in gi.rate for x in nums(rt)) else 0.0)
                   + sim(c.name_ko or "", gi.name_path.iloc[-1], gi.spec.iloc[-1]), c) for c in cand.itertuples(index=False)]
            top = max(v for v, _ in sc)
            for v, c in sc:
                if abs(v - top) < 1e-9:
                    used_items.add(it)
                    for r in gi.itertuples(index=False):
                        out.append({"year": y, "hs10": c.hs10, "valid_from": max(r.vf, a).date(), "valid_to": min(r.vt, b).date(),
                                    "rate": r.rate, "rate_num": r.rate_num, "quota": r.quota, "spec": r.spec, "name_path": r.name_path,
                                    "rate_cd": c.rate_cd, "db_adval": c.db_adval, "method": "item_best", "score": round(top, 3), "spell": r.spell})
        items_y = set(sy.item)
        cand_y = set(dy.hs10)
        mapped = {o["hs10"] for o in out if o["year"] == y}
        summ.append({"year": y, "db_codes": len(cand_y), "mapped_codes": len(mapped & cand_y), "single": n_single, "scored": n_scored,
                     "tie": n_tie, "items": len(items_y), "items_unmapped": len(items_y - used_items)})
    o = pd.DataFrame(out)
    # 같은 코드에 날짜가 겹치는 구간이 둘 이상이고 세율이 다르면 conflict(병행 지정이거나 대응이 모호한 것)
    o["vf_"], o["vt_"] = pd.to_datetime(o.valid_from), pd.to_datetime(o.valid_to)
    o["conflict"] = False
    for _, g in o.groupby(["year", "hs10"]):
        if len(g) < 2:
            continue
        for i in g.index:
            ov = g[(g.index != i) & (g.vf_ <= o.at[i, "vt_"]) & (g.vt_ >= o.at[i, "vf_"])]
            if (ov.rate.str.replace(" ", "") != o.at[i, "rate"].replace(" ", "")).any():
                o.at[i, "conflict"] = True
    o = o.drop(columns=["vf_", "vt_"])
    # 검증: 그해 세율 DB의 할당 세율이 그 코드에 붙은 구간 세율 가운데 하나인가
    ok = [any(abs(x - d) < 1e-9 for x in nums(r)) for r, d in zip(o.rate, o.db_adval)]
    rk = o.assign(ok=ok).groupby(["year", "hs10"]).ok.any()
    cf = o.groupby(["year", "hs10"]).conflict.any()
    v = (pd.DataFrame(summ).merge(rk.groupby("year").agg(rate_agree="mean").reset_index(), on="year", how="left")
         .merge(cf.groupby("year").agg(conflict_codes="sum").reset_index(), on="year", how="left"))
    o.to_csv(ROOT / "outputs" / "할당관세_시간표_hs10.csv", index=False, encoding="utf-8-sig")
    v.to_csv(ROOT / "outputs" / "할당관세_시간표_hs10_검증.csv", index=False, encoding="utf-8-sig")
    print(v.round(3).to_string(index=False))
    print(f"행 {len(o):,}, 코드×연도 {o[['year','hs10']].drop_duplicates().shape[0]:,}")


if __name__ == "__main__":
    main()
