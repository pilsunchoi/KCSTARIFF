"""
21_fetch_comtrade_mirror.py — UN Comtrade 공개 미리보기 API(키 없음, 호출당 500행)로 주요 원산지가 보고한
대한국 HS6 수출(미러 통계)을 받는다. 대상 HS6는 확정 코드 쌍과 처리군 코드의 앞 6자리이며, 그해 HS 판본의
옛 코드(dim_hs6_concordance)도 함께 요청한다.

캐시: data/raw/comtrade/<reporter>_<year>.json
산출: research/outputs/comtrade_mirror_hs6_2012_2024.csv
      (reporter, reporterISO, year, cmdCode, classification, value_usd, net_kg, qty, qty_unit)
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb
import pandas as pd
import requests

import os
ROOT = Path(__file__).resolve().parents[1]                      # KCSTARIFF/research
KCSDB2 = Path(os.environ.get("KCSDB2_ROOT", r"C:\Work\Projects\KCSDB2"))
KCS = KCSDB2 / "data" / "processed" / "kcsdb.duckdb"
OUT = ROOT / "outputs"
RAW = ROOT / "data" / "raw" / "comtrade"
URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
# 관세청 stat_cd → Comtrade reporterCode (UN M49). 대만은 490(Other Asia, nes).
REPORTERS = {"CN": 156, "US": 842, "JP": 392, "VN": 704, "AU": 36, "MY": 458, "DE": 276, "SG": 702, "BR": 76, "ID": 360,
             "AR": 32, "TH": 764, "NL": 528, "RU": 643, "TW": 490, "AE": 784, "FR": 250, "IT": 380, "NZ": 554, "IN": 699,
             "CA": 124, "GB": 826, "CH": 756, "ES": 724, "PE": 604, "MX": 484, "PH": 608, "TR": 792, "CL": 152, "EG": 818}
YEARS = range(2012, 2025)


def scope() -> tuple[list[str], pd.DataFrame]:
    pairs = pd.read_csv(OUT / "코드쌍_목록.csv", dtype={"hs10_high": str, "hs10_low": str})
    pairs = pairs[(pairs.확인.fillna("") == "Y") | pairs.source.isin(["별표", "별표(선택)"])]
    treat = pd.read_csv(OUT / "처리군_목록.csv", dtype={"hs10": str, "mate_hs10": str})
    tr = treat[treat.type.isin(["감시형", "감시형(혼합 전신)", "세율형"])]
    codes = set(pairs.hs10_high) | set(pairs.hs10_low) | set(tr.hs10) | set(tr.mate_hs10.dropna())
    hs6 = sorted({c[:6] for c in codes})
    con = duckdb.connect(); con.execute(f"ATTACH '{KCS.as_posix()}' AS s (READ_ONLY)")
    con.register("h6", pd.DataFrame({"hs6": hs6}))
    past = con.sql("SELECT DISTINCT hs2022, hs_past, past_version FROM s.dim_hs6_concordance JOIN h6 ON hs2022=hs6").df()
    con.close()
    return hs6, past


def codes_for_year(hs6: list[str], past: pd.DataFrame, year: int) -> list[str]:
    ver = "2012" if year <= 2016 else "2017" if year <= 2021 else None
    extra = set(past[past.past_version == ver].hs_past) if ver else set()
    return sorted(set(hs6) | extra)


def fetch(sess: requests.Session, reporter: int, year: int, codes: list[str], delay: float = 1.5) -> dict:
    """500행 상한에 걸리면 코드를 반으로 나눠 다시 받아 합친다. 429는 30초 쉬고 두 번 더 시도한다."""
    for attempt in range(3):
        r = sess.get(URL, params=dict(reporterCode=reporter, partnerCode=410, period=str(year), cmdCode=",".join(codes), flowCode="X"), timeout=120)
        if r.status_code == 429:
            time.sleep(30 * (attempt + 1)); continue
        r.raise_for_status(); j = r.json(); break
    else:
        r.raise_for_status()
    if j.get("count", 0) >= 500 and len(codes) > 1:
        h = len(codes) // 2; time.sleep(delay)
        a = fetch(sess, reporter, year, codes[:h], delay); time.sleep(delay); b = fetch(sess, reporter, year, codes[h:], delay)
        return {"count": a.get("count", 0) + b.get("count", 0), "data": a.get("data", []) + b.get("data", []), "split": True}
    return j


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--delay", type=float, default=1.5); ap.add_argument("--parse-only", action="store_true"); ap.add_argument("--refetch-capped", action="store_true", help="500행에 걸린 캐시를 나눠 다시 받는다")
    args = ap.parse_args()
    hs6, past = scope()
    RAW.mkdir(parents=True, exist_ok=True)
    sess = requests.Session(); sess.headers.update({"User-Agent": "Mozilla/5.0"})
    rows, failed = [], []
    for iso, rep in REPORTERS.items():
        for y in YEARS:
            f = RAW / f"{iso}_{y}.json"
            if f.exists() and not args.refetch_capped:
                j = json.loads(f.read_text(encoding="utf-8"))
            elif f.exists() and json.loads(f.read_text(encoding="utf-8")).get("count", 0) < 500:
                j = json.loads(f.read_text(encoding="utf-8"))
            elif args.parse_only:
                continue
            else:
                try:
                    j = fetch(sess, rep, y, codes_for_year(hs6, past, y), args.delay)
                except Exception as e:  # noqa: BLE001
                    failed.append((iso, y, str(e)[:80])); time.sleep(args.delay * 4); continue
                f.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8"); time.sleep(args.delay)
            for d in j.get("data", []):
                rows.append(dict(reporter=iso, reporterISO=d.get("reporterISO"), year=y, cmdCode=d["cmdCode"], classification=d.get("classificationCode"),
                                 value_usd=d.get("primaryValue"), net_kg=d.get("netWgt"), qty=d.get("qty"), qty_unit=d.get("qtyUnitAbbr"), count=j.get("count")))
        print(f"{iso}: 행 {sum(1 for r in rows if r['reporter']==iso):,}, 실패 {len(failed)}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "comtrade_mirror_hs6_2012_2024.csv", index=False, encoding="utf-8-sig")
    capped = int(sum(1 for iso in REPORTERS for y in YEARS if (RAW / f"{iso}_{y}.json").exists() and json.loads((RAW / f"{iso}_{y}.json").read_text(encoding="utf-8")).get("count", 0) >= 500 and not json.loads((RAW / f"{iso}_{y}.json").read_text(encoding="utf-8")).get("split")))
    print(f"완료: {len(df):,}행, 보고국 {df.reporter.nunique()}, HS6 {df.cmdCode.nunique()}, 500행 상한에 걸린 채 남은 호출 {capped}, 실패 {len(failed)}")
    if failed:
        print(failed[:10])


if __name__ == "__main__":
    main()
