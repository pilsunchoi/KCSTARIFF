"""
40_fetch_item_detail_all.py — 관세법령정보포털 「국내관세율상세」 화면(openULS0201007Q, 관세율표에서 품목을 눌러 여는 화면; 파일 이름의 「품목상세」)에서 기준 연도의 HSK 10단위 코드 전부의
세율(세율 자료에 없는 협정 포함: 칠레·싱가포르·EFTA·페루·튀르키예·오스트레일리아·뉴질랜드·콜롬비아·영국·중미·이스라엘·
캄보디아·필리핀·인도네시아·UAE·RCEP)을 받는다(2026-10-04, 협정 특혜 분석용).

상세 화면은 2012년부터만 세율을 준다. 코드×연도마다 한 번 호출하므로 연도당 약 11,300회(호출 0.7초 + 간격 0.5초, 약 3~4시간)다.
화면 한 장이 약 60KB라 「세율적용 우선순위」부터 「내국세」까지의 세율 표 부분만 gzip으로 캐시한다.

입력: 세율 DB의 tariff_code(그해 코드 목록)
캐시: data/raw/clip_item_detail_all/<year>/<hs10>.txt.gz (세율 표 부분; 표가 없으면 빈 파일)
산출(--parse-only 또는 수집 뒤): outputs/품목상세_전협정_세율.csv — year, hs10, rate_cd, rate_name, rate_txt, n_seg,
      adval_first, specific_first, adval_last, specific_last (scripts/17의 parse와 같은 규칙; 세율 문구에 " / "가 있으면 연중 구간이 여럿)
      outputs/품목상세_전협정_수집기록.csv — year, 코드 수, 받은 수, 표 없음, 오류
실행: python scripts/40_fetch_item_detail_all.py --years 2025 2020 2016 2012
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import time
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
DB = REPO / "data" / "processed" / "kcstariff.duckdb"
RAW = ROOT / "data" / "raw" / "clip_item_detail_all"
OUT = ROOT / "outputs"

spec = importlib.util.spec_from_file_location("s17", ROOT / "scripts" / "17_fetch_item_detail.py")
s17 = importlib.util.module_from_spec(spec); spec.loader.exec_module(s17)
HEAD, TAIL = "세율적용 우선순위", "내국세"


def codes_of(year: int) -> list[str]:
    con = duckdb.connect(str(DB), read_only=True)
    c = [r[0] for r in con.execute("SELECT hs10 FROM tariff_code WHERE year = ? ORDER BY hs10", [year]).fetchall()]
    con.close()
    return c


def segment(page: str) -> str:
    i = page.find(HEAD)
    if i < 0:
        return ""
    j = page.find(TAIL, i)
    return page[i:(j + len(TAIL)) if j > i else len(page)]


def fetch_year(sess: requests.Session, year: int, delay: float) -> dict:
    d = RAW / str(year); d.mkdir(parents=True, exist_ok=True)
    codes = codes_of(year)
    got = empty = err = 0
    t0 = time.time()
    for k, code in enumerate(codes):
        f = d / f"{code}.txt.gz"
        if f.exists():
            continue
        for attempt in range(3):
            try:
                seg = segment(s17.fetch(sess, code, year))
                f.write_bytes(gzip.compress(seg.encode("utf-8")))
                got += 1; empty += (seg == "")
                break
            except requests.RequestException:
                time.sleep(delay * 4 * (attempt + 1))
        else:
            err += 1
        time.sleep(delay)
        if (k + 1) % 500 == 0:
            print(f"{year}: {k + 1}/{len(codes)} 받음 {got} 표 없음 {empty} 오류 {err} ({(time.time() - t0) / 60:.0f}분)", flush=True)
    return dict(year=year, codes=len(codes), fetched=got, empty=empty, errors=err)


def parse_all(years: list[int]) -> None:
    rows = []
    for y in years:
        d = RAW / str(y)
        if not d.exists():
            continue
        for f in sorted(d.glob("*.txt.gz")):
            seg = gzip.decompress(f.read_bytes()).decode("utf-8")
            if seg:
                r, _ = s17.parse(" " + seg, f.name[:10], y)   # s17.parse는 머리글 위치가 0보다 커야 표를 읽는다
                rows += r
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "품목상세_전협정_세율.csv", index=False, encoding="utf-8-sig")
    print(f"세율 {len(out):,}행, 코드×연도 {out[['year', 'hs10']].drop_duplicates().shape[0]:,} → 품목상세_전협정_세율.csv")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=[2025, 2020, 2016, 2012])
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--parse-only", action="store_true")
    a = ap.parse_args()
    if not a.parse_only:
        sess = requests.Session(); sess.headers.update(s17.HEADERS)
        logs = []
        for y in a.years:
            logs.append(fetch_year(sess, y, a.delay))
            print(logs[-1], flush=True)
        pd.DataFrame(logs).to_csv(OUT / "품목상세_전협정_수집기록.csv", index=False, encoding="utf-8-sig")
    parse_all(a.years)


if __name__ == "__main__":
    main()
