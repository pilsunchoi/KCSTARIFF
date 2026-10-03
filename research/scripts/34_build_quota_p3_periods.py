"""
34_build_quota_p3_periods.py — 할당관세 시간표(HSK 10단위, scripts/33)에서 전량 할당(P3)이 적용된 날짜와 세율을 뽑아
공개 저장소의 data/quota/quota_p3_periods.csv로 쓴다(2026-10-03). scripts/02가 이 파일로 무협정 세율의 P3 적용 날짜를 정한다.

입력: outputs/할당관세_시간표_hs10.csv, 세율 DB의 tariff_rate(P3 세율).
산출: ../data/quota/quota_p3_periods.csv — year, hs10, valid_from, valid_to, adval (같은 코드의 겹치지 않는 구간)
      outputs/할당관세_P3_구간_검증.csv — 코드×연도마다 세율 DB의 P3 여부, 시간표의 P3 일수, 분류 근거.
구간이 P3인지(수입전량)·P1인지(물량·추천)는 다음 순서로 정한다.
  1) 세율 DB의 그해 구분이 P3만이면 P3, P1만이면 P1(P1은 추천이 필요한 할당이라 한계수량 문구보다 세율 DB를 따른다 —
     2017년 이차전지 격리막처럼 물량이 적혀 있어도 세율 DB는 P3인 경우가 있다).
  2) 둘 다이면 한계수량에 「수입전량」이 있으면 P3, 물량이 있으면 P1, 비어 있으면 구간 세율이 세율 DB의 P3 세율과 같을 때 P3.
  3) 세율 DB에 그해 P3가 없는 코드는 P3로 두지 않는다(세율 DB의 연 단위 집합이 기준; 기록 6·10절).
같은 날 P3 구간이 둘 이상이면(용도 구분 등 conflict) 세율 DB의 P3 세율과 같은 구간, 없으면 가장 낮은 세율을 쓴다.
세율 문구에 숫자가 여럿인 구간(rate_multi)은 세율 DB의 P3 세율이 그 가운데 있으면 그 값, 없으면 가장 낮은 값.
"""

import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
DB = REPO / "data" / "processed" / "kcstariff.duckdb"


def nums(rate: str) -> list:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(rate))]


def classify(o: pd.DataFrame, p3: pd.DataFrame) -> pd.DataFrame:
    """시간표(코드×구간)에 세율 DB의 그해 P3 세율(p3)을 붙이고 구간마다 P1·P3(cls)와 근거(basis)를 정한다. scripts/35도 쓴다."""
    o = o.merge(p3, on=["year", "hs10"], how="left")
    q = o.quota.str.replace(r"\s+", "", regex=True)
    cds = o.rate_cd.fillna("")
    match = pd.Series([any(abs(x - p) < 1e-9 for x in nums(r)) if p == p else False for r, p in zip(o.rate, o.p3)], index=o.index)
    cls = pd.Series("", index=o.index); basis = pd.Series("", index=o.index)
    cls[cds == "P3"], basis[cds == "P3"] = "P3", "db_only"
    cls[cds == "P1"], basis[cds == "P1"] = "P1", "db_only"
    both = cds == "P1,P3"
    m1 = both & q.str.contains("수입전량"); cls[m1], basis[m1] = "P3", "quota"
    m2 = both & ~q.str.contains("수입전량") & (q != ""); cls[m2], basis[m2] = "P1", "quota"
    m3 = both & (q == ""); cls[m3] = ["P3" if m else "P1" for m in match[m3]]; basis[m3] = "db_rate"
    o["cls"], o["basis"] = cls, basis
    return o


def load_classified() -> pd.DataFrame:
    o = pd.read_csv(ROOT / "outputs" / "할당관세_시간표_hs10.csv", dtype={"hs10": str}).fillna({"quota": "", "rate": ""})
    con = duckdb.connect(str(DB), read_only=True)
    p3 = con.execute("select year, hs10, min(adval) p3 from tariff_rate where rate_cd='P3' group by 1, 2").df()
    con.close()
    return classify(o, p3), p3


def main() -> None:
    o, p3 = load_classified()
    s = o[(o.cls == "P3") & o.p3.notna()].copy()                     # 3) 세율 DB에 그해 P3가 없으면 두지 않는다

    def pick(r, p):
        v = nums(r)
        if not v:
            return None
        return p if any(abs(x - p) < 1e-9 for x in v) else min(v)
    s["adval"] = [pick(r, p) for r, p in zip(s.rate, s.p3)]
    s = s[s.adval.notna()]
    # 일 단위로 펼쳐 같은 날 여러 구간이면 P3 세율과 같은 것, 없으면 최저
    rows = []
    for (y, h), g in s.groupby(["year", "hs10"]):
        days = {}
        for r in g.itertuples(index=False):
            for d in pd.date_range(r.valid_from, r.valid_to):
                days.setdefault(d, []).append(r.adval)
        p = g.p3.iloc[0]
        ser = pd.Series({d: (p if any(abs(x - p) < 1e-9 for x in v) else min(v)) for d, v in days.items()}).sort_index()
        # 같은 세율이 이어지는 날을 구간으로
        start = prev_d = None; prev_v = None
        for d, v in ser.items():
            if start is not None and (d - prev_d).days == 1 and v == prev_v:
                prev_d = d; continue
            if start is not None:
                rows.append((y, h, start.date(), prev_d.date(), prev_v))
            start = prev_d = d; prev_v = v
        rows.append((y, h, start.date(), prev_d.date(), prev_v))
    out = pd.DataFrame(rows, columns=["year", "hs10", "valid_from", "valid_to", "adval"])
    dst = REPO / "data" / "quota" / "quota_p3_periods.csv"
    out.to_csv(dst, index=False)
    # 검증: 세율 DB의 P3 코드×연도마다 시간표의 P3 일수
    out["days"] = (pd.to_datetime(out.valid_to) - pd.to_datetime(out.valid_from)).dt.days + 1
    dd = out.groupby(["year", "hs10"]).days.sum()
    v = p3.set_index(["year", "hs10"]).join(dd).fillna({"days": 0}).reset_index()
    v["ndays"] = [366 if y % 4 == 0 else 365 for y in v.year]
    v["share"] = v.days / v.ndays
    v.to_csv(ROOT / "outputs" / "할당관세_P3_구간_검증.csv", index=False, encoding="utf-8-sig")
    summ = v.groupby("year").agg(p3_codes=("hs10", "size"), full_year=("share", lambda x: (x >= 0.999).sum()),
                                  partial=("share", lambda x: ((x > 0) & (x < 0.999)).sum()), none=("share", lambda x: (x == 0).sum()),
                                  mean_share=("share", "mean"))
    print(summ.round(3).to_string())
    print("분류 근거(구간):", o.groupby(["basis", "cls"]).size().to_dict())
    print(f"→ {dst} {len(out):,}행")


if __name__ == "__main__":
    main()
