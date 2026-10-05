# -*- coding: utf-8 -*-
"""관세청 FTA 포털의 협정별 수입 활용률(협정 × MTI 대분류 × 연도, 2016~2021년)을 받는다(2026-10-05).

화면: https://www.customs.go.kr/ftaportalkor/ad/ftaUseRate/ftaUseRateCnvnImpList.do?cnvnNm=<협정>&quarter=<연도>-0&mi=3353
정의(화면 문구): 수입활용률 = FTA 적용 신고금액 / FTA 특혜품목의 수입금액 x 100. 연도 선택지는 2016~2021년뿐이다.
산출: outputs/FTA_활용률_수입.csv (cnvn, year, cnvn_nm, mti, rate), 캐시 data/raw/fta_use_rate/<협정>_<연도>.html
실행: python scripts/41_fetch_fta_utilization.py (research/에서, kcsdb 환경)
"""
import re
import time
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent.parent
RAW = HERE / "data" / "raw" / "fta_use_rate"
OUT = HERE / "outputs" / "FTA_활용률_수입.csv"
URL = "https://www.customs.go.kr/ftaportalkor/ad/ftaUseRate/ftaUseRateCnvnImpList.do?cnvnNm={c}&quarter={y}-0&mi=3353"
CNVN = ["cl", "efta", "as", "in", "eu", "pe", "us", "tr", "au", "ca", "cn", "ve", "nz", "co"]
YEARS = range(2016, 2022)


def fetch(c, y):
    f = RAW / f"{c}_{y}.html"
    if f.exists():
        return f.read_text(encoding="utf-8")
    r = requests.get(URL.format(c=c, y=y), timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    f.write_text(r.text, encoding="utf-8")
    time.sleep(1.0)
    return r.text


def parse(html, c, y):
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"\s+", " ", t)
    i = t.find(f"{y}년(누적)")
    seg = t[i:i + 3000] if i >= 0 else ""
    rows = []
    for m in re.finditer(r"(\S+) (농림수산물|광산물|화학공업제품|플라스틱고무및가죽제품|섬유류|생활용품|철강금속제품|기계류|전자전기제품|잡제품|합계) ([\d.]+)%", seg):
        rows.append(dict(cnvn=c, year=y, cnvn_nm=m.group(1), mti=m.group(2), rate=float(m.group(3))))
    return rows


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in CNVN:
        for y in YEARS:
            r = parse(fetch(c, y), c, y)
            print(c, y, len(r))
            rows += r
    d = pd.DataFrame(rows)
    d.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(OUT, len(d))


if __name__ == "__main__":
    main()
