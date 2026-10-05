"""
17_fetch_item_detail.py — 관세법령정보포털 「국내관세율상세」 화면(openULS0201007Q, 관세율표에서 품목을 눌러 여는 화면; 파일 이름의 「품목상세」)에서 코드 쌍에 든 코드의
연도별 세율 전부(그 밖 FTA 포함)와 부가 정보(사전세액심사 대상 표시, 유통이력 신고대상 지정기간,
분류사례·원산지결정기준 건수)를 받는다. 상세 화면은 2012년부터만 세율을 준다.

입력: research/outputs/코드쌍_코드목록.txt (한 줄에 HS10 하나)
캐시: data/raw/clip_item_detail/<year>/<hs10>.html
산출: research/outputs/품목상세_세율_2012_2026.csv (연도×코드×구분기호, 긴 형태)
      research/outputs/품목상세_부가정보_2012_2026.csv
세율 문구에 " / "가 있으면 연중 구간이 여럿이다(구간 날짜는 화면에 없다). 첫 구간과 마지막 구간을 따로 둔다.
"""
from __future__ import annotations

import argparse
import html
import re
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]                      # KCSTARIFF/research
RAW = ROOT / "data" / "raw" / "clip_item_detail"
OUT = ROOT / "outputs"
CODES = OUT / "코드쌍_코드목록.txt"
BASE = "https://unipass.customs.go.kr/clip/hsinfosrch/openULS0201007Q.do"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://unipass.customs.go.kr/clip/index.do"}
YEARS = range(2012, 2027)
ERROR_MARK = "프로그램 오류발생"


def strip(x: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


def fetch(sess: requests.Session, code: str, year: int) -> str:
    r = sess.post(BASE, data={"searchVal": code, "aplyYy": str(year)}, timeout=60)
    r.raise_for_status()
    if ERROR_MARK in r.text:
        raise requests.RequestException("오류 안내문")
    return r.text


def parse_rate(txt: str) -> tuple[float | None, float | None]:
    """'270% 또는 6,210원' → (270.0, 6210.0); '240원' → (None, 240.0); '0%' → (0.0, None)."""
    a = re.search(r"([\d.]+)\s*%", txt)
    sp = re.search(r"([\d,]+(?:\.\d+)?)\s*원", txt)
    return (float(a.group(1)) if a else None, float(sp.group(1).replace(",", "")) if sp else None)


def parse(page: str, code: str, year: int) -> tuple[list[dict], dict]:
    rows = []
    i = page.find("세율적용 우선순위")
    j = page.find("내국세", i) if i > 0 else -1
    seg = page[i:j] if i > 0 and j > i else ""
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S):
        c = [strip(x) for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(c) >= 3 and re.fullmatch(r"[A-Z][A-Z0-9]*", c[0]):
            segs = [s.strip() for s in c[1].split(" / ")]
            a1, s1 = parse_rate(segs[0])
            aN, sN = parse_rate(segs[-1])
            rows.append(dict(year=year, hs10=code, rate_cd=c[0], rate_name=c[2], rate_txt=c[1], n_seg=len(segs),
                             adval_first=a1, specific_first=s1, adval_last=aN, specific_last=sN))
    text = strip(re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S))
    m_yu = re.search(r"유통이력 신고대상물품명, 지정기간, 통보기관 (.*?) 연관정보", text)
    yu = m_yu.group(1).strip() if m_yu else ""
    if yu.startswith("There were no results"):
        yu = ""
    cnt = {k: int(m.group(1)) if (m := re.search(k + r"\s*(\d+)건", text)) else None
           for k in ["분류사례", "평가사례", "원산지결정기준", "판례·결정례"]}
    extra = dict(year=year, hs10=code, pre_assessment="사전세액대상물품" in text, deposit_price="담보기준가격" in text,
                 distribution_history=yu, n_class_case=cnt["분류사례"], n_valuation_case=cnt["평가사례"],
                 n_origin_rule=cnt["원산지결정기준"], n_ruling=cnt["판례·결정례"], n_rates=len(rows))
    return rows, extra


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--parse-only", action="store_true")
    ap.add_argument("--codes", nargs="*", help="지정하면 이 코드만")
    args = ap.parse_args()
    codes = args.codes or [c.strip() for c in CODES.read_text().splitlines() if c.strip()]
    sess = requests.Session()
    sess.headers.update(HEADERS)
    rates, extras, failed = [], [], []
    n = 0
    for code in codes:
        for year in YEARS:
            f = RAW / str(year) / f"{code}.html"
            if f.exists():
                page = f.read_text(encoding="utf-8")
            elif args.parse_only:
                continue
            else:
                try:
                    page = fetch(sess, code, year)
                except Exception as e:  # noqa: BLE001
                    failed.append((code, year, str(e)[:80]))
                    time.sleep(args.delay * 4)
                    continue
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(page, encoding="utf-8")
                time.sleep(args.delay)
            r, x = parse(page, code, year)
            rates.extend(r)
            extras.append(x)
        n += 1
        if n % 20 == 0:
            print(f"{n}/{len(codes)} 코드, 세율 행 {len(rates):,}, 실패 {len(failed)}", flush=True)
    pd.DataFrame(rates).to_csv(OUT / "품목상세_세율_2012_2026.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(extras).to_csv(OUT / "품목상세_부가정보_2012_2026.csv", index=False, encoding="utf-8-sig")
    print(f"완료: 코드 {len(codes)}, 세율 행 {len(rates):,}, 부가정보 {len(extras):,}, 실패 {len(failed)}")
    if failed:
        pd.DataFrame(failed, columns=["hs10", "year", "err"]).to_csv(OUT / "품목상세_실패.csv", index=False, encoding="utf-8-sig")
        print(failed[:10])


if __name__ == "__main__":
    main()
