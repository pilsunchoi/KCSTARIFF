"""
38_fetch_quota_amendment_reasons.py — 할당관세 규정 판본마다 「제정·개정이유」를 받는다(2026-10-03, 지정 사유로 사건을 나누기 위해).

판본 목록은 scripts/30이 받은 manifest.csv(lsiSeq·시행일). 판본마다 국가법령정보센터 `lsRvsDocInfoR.do?lsiSeq=…`가
【제정·개정이유】와 【제정·개정문】을 준다. 「◇ 개정이유 및 주요내용」부터 【제정·개정문】 앞까지를 사유 문단으로 둔다.
산출: data/external/할당관세_규정_별표/<시행일>_<lsiSeq>/개정이유.html (gitignore)
      outputs/할당관세_개정이유.csv — efYd, lsiSeq, kind(제정·전부개정·일부개정), annual(1월 1일 시행), reason(사유 문단),
        reason_specific(일반 문구 「…있는바,」 뒤의 품목별 사유), flag_shock(작황·가뭄·질병 등 국내 공급 충격), flag_price(가격 상승),
        flag_world(국제·대외 요인), flag_cpi(물가·서민), flag_cost(원가·경쟁력·산업) — 품목별 사유에서 찾는다
요청 사이에 0.5초 쉰다. 이미 받은 파일은 다시 받지 않는다.
"""

import html
import re
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "external" / "할당관세_규정_별표"
URL = "https://www.law.go.kr/LSW/lsRvsDocInfoR.do"
# 사유 문단의 머리(관세법 제71조의 일반 문구, 「…있는바,」까지)를 뗀 뒤의 품목별 사유에서 찾는다
FLAGS = {"flag_shock": r"작황|가뭄|침수|장마|태풍|폭염|한파|냉해|병해|조류\s*인플루엔자|AI|아프리카\s*돼지열병|ASF|구제역|생산\s*감소|공급\s*부족|수급\s*불안|출하\s*감소",
         "flag_price": r"가격.{0,8}(?:상승|오름|급등|불안|강세)|가격이\s*(?:오르|상승)",
         "flag_world": r"국제|대외|원자재|유가|환율",
         "flag_cpi": r"물가|서민|생계비|장바구니",
         "flag_cost": r"원가|경쟁력|생산비|기업|산업"}


def text(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def main() -> None:
    m = pd.read_csv(BASE / "manifest.csv", dtype=str)[["efYd", "lsiSeq"]].drop_duplicates()
    rows = []
    for r in m.itertuples(index=False):
        p = BASE / f"{r.efYd}_{r.lsiSeq}" / "개정이유.html"
        if not p.exists():
            q = requests.get(URL, params={"lsiSeq": r.lsiSeq}, headers={"User-Agent": "Mozilla/5.0",
                             "Referer": f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={r.lsiSeq}"}, timeout=60)
            q.raise_for_status()
            p.write_text(q.text, encoding="utf-8")
            time.sleep(0.5)
        t = text(p.read_text(encoding="utf-8"))
        kind = re.search(r"\d{4}\.\s*\d+\.\s*\d+\.,\s*(제정|전부개정|일부개정|폐지제정)\]", t)
        a = t.find("【제정·개정이유】"); b = t.find("【제정·개정문】")
        reason = t[a + len("【제정·개정이유】"): b if b > a else None].replace("<법제처 제공>", "").strip()
        i = reason.find("는바,")
        spec = reason[i + 3:].strip() if i >= 0 else reason
        row = {"efYd": r.efYd, "lsiSeq": r.lsiSeq, "kind": kind.group(1) if kind else "", "annual": r.efYd[4:] == "0101", "reason": reason, "reason_specific": spec}
        for k, pat in FLAGS.items():
            row[k] = bool(re.search(pat, spec))
        rows.append(row)
    d = pd.DataFrame(rows).sort_values(["efYd", "lsiSeq"])
    d.to_csv(ROOT / "outputs" / "할당관세_개정이유.csv", index=False, encoding="utf-8-sig")
    print(f"판본 {len(d)}, 사유 비어 있음 {int((d.reason.str.len() < 20).sum())}")
    print(d.groupby("annual")[[c for c in d if c.startswith("flag_")]].mean().round(2).to_string())
    print(d.kind.value_counts().to_string())


if __name__ == "__main__":
    main()
