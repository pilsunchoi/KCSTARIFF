"""
26_fetch_ecos_fx.py — 한국은행 ECOS 731Y001(주요국 통화의 대원화 환율)에서 원/미국달러 매매기준율을 일별로 받아 월평균을 만든다(자료 논문 부록 A3.3).

2026-09-12에 대화형으로 만든 outputs/환율_월별_USDKRW.csv 를 2026-09-13에 스크립트로 복원했다. 복원본은 옛 CSV와 237개월 전부 같다(소수 2자리).
이 통계표는 월별 주기 조회가 없고 일별만 있으므로 해마다 일별 전부를 받아(한 해 1,000행 상한 안) 달마다 평균한다.
항목 코드는 StatisticItemList 로 확인한다(0000001 = 원/미국달러(매매기준율)). 키는 KCSDB2/config/api_key.env 의 ECOS_API_KEY (저장소에 올리지 않는다).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
KCSDB2 = Path(os.environ.get("KCSDB2_ROOT", r"C:\Work\Projects\KCSDB2"))
OUT = ROOT / "outputs" / "환율_월별_USDKRW.csv"
STAT = "731Y001"


def api_key() -> str:
    for line in open(KCSDB2 / "config" / "api_key.env", encoding="utf-8"):
        if line.startswith("ECOS_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ECOS_API_KEY 없음")


def main(y0: int = 2007, y1: int = 2026) -> None:
    key = api_key()
    items = requests.get(f"https://ecos.bok.or.kr/api/StatisticItemList/{key}/json/kr/1/100/{STAT}", timeout=60).json()["StatisticItemList"]["row"]
    code = next(it["ITEM_CODE"] for it in items if "미국달러" in it["ITEM_NAME"])
    rows = []
    for y in range(y0, y1 + 1):
        for start in (1, 1001):
            r = requests.get(f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/{start}/{start + 999}/{STAT}/D/{y}0101/{y}1231/{code}", timeout=60).json()
            data = r.get("StatisticSearch", {}).get("row", [])
            rows += [(d["TIME"], float(d["DATA_VALUE"])) for d in data if d.get("DATA_VALUE") not in (None, "", "-")]
            if len(data) < 1000:
                break
            time.sleep(0.3)
        time.sleep(0.3)
    fx = pd.DataFrame(rows, columns=["date", "rate"]).drop_duplicates("date")
    fx["yyyymm"] = fx.date.str[:6].astype(int)
    mon = fx.groupby("yyyymm").rate.mean().round(2).reset_index().rename(columns={"rate": "krw_per_usd"})
    mon["year"] = mon.yyyymm // 100
    mon.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"{OUT.name}: {len(mon)}개월 ({mon.yyyymm.min()}~{mon.yyyymm.max()}), 일별 {len(fx):,}행")


if __name__ == "__main__":
    main()
