"""
37_fetch_cpi_items.py — 품목별 소비자물가지수(전국, 월)를 KOSIS에서 받는다(2026-10-03, 할당관세 귀착 연구의 소매 단계).

표: 통계청 DT_1J22112 「품목별 소비자물가지수(품목성질별: 2020=100)」, 기관 101. 축 C(시도)는 전국 T10만, 축 I(품목)는 전부(484개).
기간: 2006.01~ 최근(할당관세 시간표 2007~의 앞 12개월 포함). 한 번에 받는 칸 수 한도 때문에 5년 창으로 나눈다.
키: KCSDB2/config/api_key.env 의 KOSIS_API_KEY(저장소에 올리지 않는다; 출력에 찍지 않는다).
산출: data/external/kosis_cpi_items/<받은 날>_<시작>.json (원자료, gitignore)
      outputs/소비자물가_품목_월.parquet — yyyymm, item_id, item_nm, up_item_id, value
      outputs/소비자물가_품목.csv — 품목 사전(item_id, item_nm, up_item_id, 첫·끝 달, 관측 수)
"""

import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
KCSDB2 = Path(os.environ.get("KCSDB2_ROOT", r"C:\Work\Projects\KCSDB2"))
RAW = ROOT / "data" / "external" / "kosis_cpi_items"
URL = "https://kosis.kr/openapi/statisticsData.do"
URL_DATA = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
TBL, ORG = "DT_1J22112", "101"


def api_key() -> str:
    for line in open(KCSDB2 / "config" / "api_key.env", encoding="utf-8"):
        if line.startswith("KOSIS_API_KEY") and not line.startswith("#"):
            return line.split("=", 1)[1].strip()
    raise SystemExit("KOSIS_API_KEY 없음")


def get(url, q):
    t = urllib.request.urlopen(url + "?" + urllib.parse.urlencode(q), timeout=180).read().decode("utf-8")
    js = json.loads(t)
    if isinstance(js, dict):
        raise SystemExit(f"KOSIS 오류: {js}")
    return js


def main() -> None:
    key = api_key()
    meta = pd.DataFrame(get(URL, {"method": "getMeta", "apiKey": key, "orgId": ORG, "tblId": TBL, "type": "ITM", "format": "json", "jsonVD": "Y"}))
    items = meta[meta.OBJ_ID == "I"][["ITM_ID", "ITM_NM", "UP_ITM_ID"]].rename(columns={"ITM_ID": "item_id", "ITM_NM": "item_nm", "UP_ITM_ID": "up_item_id"})
    RAW.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().strftime("%Y%m%d")
    rows = []
    for y in range(2006, dt.date.today().year + 1, 5):
        q = {"method": "getList", "apiKey": key, "itmId": "T", "objL1": "T10", "objL2": "ALL", "format": "json", "jsonVD": "Y",
             "prdSe": "M", "startPrdDe": f"{y}01", "endPrdDe": f"{min(y + 4, dt.date.today().year)}12", "orgId": ORG, "tblId": TBL}
        js = get(URL_DATA, q)
        (RAW / f"{stamp}_{y}.json").write_text(json.dumps(js, ensure_ascii=False), encoding="utf-8")
        rows += js
        print(y, len(js))
    d = pd.DataFrame(rows)
    d = pd.DataFrame({"yyyymm": d.PRD_DE.astype(int), "item_id": d.C2.astype(str), "value": pd.to_numeric(d.DT, errors="coerce")}).dropna()
    d = d.merge(items, on="item_id", how="left")
    d.to_parquet(ROOT / "outputs" / "소비자물가_품목_월.parquet", index=False)
    s = d.groupby(["item_id", "item_nm", "up_item_id"], dropna=False).agg(first=("yyyymm", "min"), last=("yyyymm", "max"), n=("value", "size")).reset_index()
    s.to_csv(ROOT / "outputs" / "소비자물가_품목.csv", index=False, encoding="utf-8-sig")
    print(f"품목 {d.item_id.nunique()}개, {len(d):,}행, {d.yyyymm.min()}~{d.yyyymm.max()}")


if __name__ == "__main__":
    main()
