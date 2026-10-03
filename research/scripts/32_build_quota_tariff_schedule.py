"""
32_build_quota_tariff_schedule.py — 할당관세 별표 행을 판본 시행 기간과 별표 기간으로 이어 일 단위 시간표를 만든다(2026-10-03).

입력: outputs/할당관세_별표_행.csv(scripts/31).
산출: outputs/할당관세_시간표.csv — 한 행이 「같은 품목·규격·세율·한계수량이 끊김 없이 적용된 구간」 하나.
  hs4, sub, hs6(소호가 한 자리면 0을 붙임), name_path, spec, rate, rate_num, quota, quota_all,
  valid_from, valid_to(둘 다 포함), n_versions(이은 판본 수), first_efYd, last_efYd, flag(31의 flag 합집합)
      outputs/할당관세_시간표_검증.csv — 해마다 1월 1일·7월 1일에 걸린 HS6 수, 그해 한 번이라도 걸린 HS6 수와 세율 DB 대조,
  같은 날 같은 품목·규격에 세율이 둘 이상인 구간 수.
규칙: 별표 행의 적용 구간 = [max(판본 시행일, 별표 기간 시작), min(다음 판본 시행일 전날, 별표 기간 끝)]. 구간이 비면 버린다
(예: 2026-07-01 판의 「1월 1일부터 3월 31일까지」 별표). 판본이 바뀌어도 품목·규격·세율·한계수량이 같고 구간이 이어지면 하나로 합친다.
품명은 판본마다 띄어쓰기·영문 병기가 달라 비교할 때 공백을 지우고, 표에는 마지막 판본의 문구를 둔다.
한계수량이 빈 행은 「수입전량」이 아니다 — 세율 DB의 P1(추천)·P3(수입전량) 구분은 추천 필요 여부를 따르며(예: 「농약관리법」에 따라
등록된 농약원제는 한계수량 없이 P1), 별표 행의 36%가 한계수량이 비어 있다. 10단위 대응에서 세율 DB의 구분을 붙인다.
한계수량은 그 판본·별표가 정한 물량이며 구간 전체의 물량이 아니다(2009년 상반기 판처럼 한계수량을 세는 기간이 적용 기간과 다를 수 있다).
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
KCSTARIFF_DB = ROOT.parent / "data" / "processed" / "kcstariff.duckdb"


def build(d: pd.DataFrame) -> pd.DataFrame:
    d = d.fillna("")
    vers = sorted(d.efYd.unique())
    nxt = {a: b for a, b in zip(vers, vers[1:])}
    ef = pd.to_datetime(d.efYd)
    vend = pd.to_datetime(d.efYd.map(nxt).fillna("29991231")) - pd.Timedelta(days=1)
    vend = vend.where(d.efYd.map(nxt).notna(), pd.Timestamp("2999-12-31"))
    ps, pe = pd.to_datetime(d.period_start), pd.to_datetime(d.period_end)
    d = d.assign(valid_from=pd.concat([ef, ps], axis=1).max(axis=1), valid_to=pd.concat([vend, pe], axis=1).min(axis=1))
    d = d[d.valid_from <= d.valid_to].copy()
    d["hs6"] = d.hs4 + d["sub"].str.ljust(2, "0").str[:2]
    d["name_key"] = d.name_path.str.replace(r"\s+", "", regex=True)
    key = ["hs4", "sub", "name_key", "spec_key", "rate", "quota_key"]
    d["spec_key"] = d.spec.str.replace(r"\s+", "", regex=True)
    d["quota_key"] = d.quota.str.replace(r"\s+", "", regex=True)
    d = d.sort_values(key + ["valid_from", "efYd"])
    out = []
    for _, g in d.groupby(key, sort=False):
        cur = None
        for r in g.itertuples(index=False):
            if cur is not None and r.valid_from <= cur["valid_to"] + pd.Timedelta(days=1):
                cur["valid_to"] = max(cur["valid_to"], r.valid_to)
                cur["n_versions"] += r.efYd != cur["last_efYd"]
                cur["last_efYd"] = r.efYd
                cur["name_path"], cur["spec"], cur["quota"] = r.name_path, r.spec, r.quota
                cur["flag"] |= set(filter(None, r.flag.split(";")))
                continue
            if cur is not None:
                out.append(cur)
            cur = {"hs4": r.hs4, "sub": r.sub, "hs6": r.hs6, "name_path": r.name_path, "spec": r.spec, "rate": r.rate,
                   "rate_num": r.rate_num, "quota": r.quota, "quota_all": r.quota_all, "valid_from": r.valid_from,
                   "valid_to": r.valid_to, "n_versions": 1, "first_efYd": r.efYd, "last_efYd": r.efYd,
                   "flag": set(filter(None, r.flag.split(";")))}
        out.append(cur)
    s = pd.DataFrame(out)
    # 같은 품목(소호·품명)·규격에 날짜가 겹치는 다른 구간(세율이나 한계수량이 다름)이 있으면 'overlap'.
    # 실제로 겹쳐 지정된 경우(2015년 원유: 별표 4 1%·연간 물량과 별표 3·5 2%·반기 물량)와 병합 칸의 조건이 한 행에만 적혀
    # 다른 행에서 빈 경우(2011년 3808호 농약원제)가 섞여 있다.
    nk = s.name_path.str.replace(r"\s+", "", regex=True) + "|" + s.spec.str.replace(r"\s+", "", regex=True)
    for _, g in s.assign(nk=nk).groupby(["hs4", "sub", "nk"]):
        if len(g) < 2:
            continue
        for i in g.index:
            if ((g.index != i) & (g.valid_from <= s.at[i, "valid_to"]) & (g.valid_to >= s.at[i, "valid_from"])).any():
                s.at[i, "flag"] = s.at[i, "flag"] | {"overlap"}
    s["flag"] = s.flag.map(lambda x: ";".join(sorted(x)))
    return s.sort_values(["hs6", "valid_from", "spec"]).reset_index(drop=True)


def check(s: pd.DataFrame) -> pd.DataFrame:
    import duckdb
    con = duckdb.connect(str(KCSTARIFF_DB), read_only=True) if KCSTARIFF_DB.exists() else None
    rows = []
    for y in range(int(s.valid_from.dt.year.min()), 2027):
        a, b = pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31")
        on = lambda t: set(s.hs6[(s.valid_from <= t) & (s.valid_to >= t)])
        yr = set(s.hs6[(s.valid_from <= b) & (s.valid_to >= a)])
        r = {"year": y, "hs6_jan1": len(on(a)), "hs6_jul1": len(on(pd.Timestamp(f"{y}-07-01"))), "hs6_year": len(yr)}
        if con is not None:
            db = {x[0] for x in con.execute("select distinct substr(hs10,1,6) from tariff_rate where year=? and rate_cd in ('P1','P3')", [y]).fetchall()}
            r.update(db_hs6=len(db), db_only=len(db - yr), schedule_only=len(yr - db))
        rows.append(r)
    v = pd.DataFrame(rows)
    # 같은 날 같은 품목(소호·품명)·규격에 세율이 둘 이상 — 별표 사이 겹침
    k = s.assign(nk=s.name_path.str.replace(r"\s+", "", regex=True), sk=s.spec.str.replace(r"\s+", "", regex=True))
    over = 0
    for _, g in k.groupby(["hs4", "sub", "nk", "sk"]):
        if len(g) < 2:
            continue
        g = g.sort_values("valid_from")
        end = pd.Timestamp.min
        for r in g.itertuples():
            over += r.valid_from <= end
            end = max(end, r.valid_to)
    v.attrs["overlap"] = over
    return v


def main() -> None:
    d = pd.read_csv(ROOT / "outputs" / "할당관세_별표_행.csv", dtype=str)
    s = build(d)
    out = ROOT / "outputs" / "할당관세_시간표.csv"
    s.to_csv(out, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    v = check(s)
    v.to_csv(ROOT / "outputs" / "할당관세_시간표_검증.csv", index=False, encoding="utf-8-sig")
    print(v.to_string(index=False))
    print(f"구간 {len(s):,}개(HS6 {s.hs6.nunique()}, {s.valid_from.min():%Y-%m-%d}~{s.valid_to.max():%Y-%m-%d}), "
          f"같은 날 같은 품목·규격에 세율이 겹치는 구간 {v.attrs['overlap']} → {out}")


if __name__ == "__main__":
    main()
