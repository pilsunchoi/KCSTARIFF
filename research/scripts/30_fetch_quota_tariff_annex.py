"""
30_fetch_quota_tariff_annex.py — 할당관세 규정의 판본별 별표를 국가법령정보센터에서 받는다(2026-10-03).

대상: 「관세법 제71조에 따른 할당관세의 적용에 관한 규정」(대통령령)의 판본 가운데 2007~2026년에 시행된 것.
판본 목록(lsiSeq, 시행일)은 국가법령정보센터 연혁법령 검색(법령명 「할당관세」, 120건)의 결과 페이지에서 읽었다
(2026-10-03; 2006-01-01 시행 판까지는 2007년 전에 대체되어 뺀다). 같은 날 시행된 판본이 둘인 경우(2021-11-12)도 둘 다 둔다.

판본마다 `lsInfoR.do?lsiSeq=…&efYd=…&chrClsCd=010202&ancYnChk=0`이 본문과 별표 목록을 준다. 별표마다
[별표 N] 제목(적용 기간이 들어 있다), HWP 링크(flSeq, 같은 flSeq에 flExt=hwpx를 붙이면 HWPX), PDF 링크(flSeq)가 있다.
HWPX와 PDF를 요청한다(실제로는 flExt=hwpx를 주어도 HWP가 온다; PDF는 대조용). 파일 형식은 머리 바이트로 판별한다.
파일이 없는 별표(텍스트 내려받기만 있는 판본)는 별표 뷰어 `lsBylContentsInfoR.do?bylSeq=…`의 HTML을 저장한다.

산출: data/external/할당관세_규정_별표/<시행일>_<lsiSeq>/별표<N>_<flSeq>.<hwpx|hwp|pdf>
      data/external/할당관세_규정_별표/manifest.csv (시행일, lsiSeq, 별표 번호, 제목, 형식, flSeq, 바이트, sha256)
이미 받은 파일은 건너뛴다. 요청 사이에 0.5초 쉰다.
"""
from __future__ import annotations

import csv
import hashlib
import html
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external" / "할당관세_규정_별표"
BASE = "https://www.law.go.kr/LSW/"
UA = {"User-Agent": "Mozilla/5.0"}
VERSIONS = [
    ("76923", "20070101"),
    ("79529", "20070701"),
    ("82354", "20080101"),
    ("86685", "20080401"),
    ("88342", "20080807"),
    ("91087", "20090101"),
    ("93616", "20090521"),
    ("95165", "20090701"),
    ("98070", "20100101"),
    ("107349", "20100825"),
    ("108202", "20101012"),
    ("108782", "20101115"),
    ("109547", "20110101"),
    ("110323", "20110128"),
    ("110920", "20110307"),
    ("113065", "20110512"),
    ("113595", "20110530"),
    ("114322", "20110701"),
    ("115972", "20110811"),
    ("117231", "20110922"),
    ("121762", "20120101"),
    ("124162", "20120401"),
    ("126004", "20120605"),
    ("126427", "20120701"),
    ("127265", "20120724"),
    ("128885", "20120928"),
    ("131375", "20130101"),
    ("141590", "20130701"),
    ("149236", "20140101"),
    ("155862", "20140701"),
    ("165786", "20150101"),
    ("172565", "20150701"),
    ("177254", "20151210"),
    ("178610", "20160101"),
    ("185016", "20160801"),
    ("188750", "20170101"),
    ("190893", "20170104"),
    ("196480", "20170809"),
    ("200453", "20180101"),
    ("206453", "20190101"),
    ("212887", "20200101"),
    ("215633", "20200318"),
    ("225173", "20210101"),
    ("228905", "20210127"),
    ("231909", "20210423"),
    ("233353", "20210701"),
    ("236729", "20211112"),
    ("236755", "20211112"),
    ("238733", "20220101"),
    ("241967", "20220427"),
    ("243323", "20220622"),
    ("243987", "20220720"),
    ("244341", "20220817"),
    ("245277", "20221110"),
    ("247117", "20230101"),
    ("248317", "20230223"),
    ("250547", "20230501"),
    ("251343", "20230601"),
    ("252243", "20230701"),
    ("252579", "20230706"),
    ("254185", "20230825"),
    ("255301", "20231013"),
    ("256123", "20231117"),
    ("257175", "20240101"),
    ("258983", "20240119"),
    ("261511", "20240401"),
    ("261705", "20240405"),
    ("262607", "20240510"),
    ("263451", "20240701"),
    ("265521", "20241001"),
    ("266107", "20241029"),
    ("267819", "20250101"),
    ("268641", "20250124"),
    ("270305", "20250401"),
    ("271039", "20250501"),
    ("272597", "20250701"),
    ("273917", "20250925"),
    ("280769", "20260101"),
    ("283343", "20260212"),
    ("285307", "20260403"),
    ("286339", "20260529"),
    ("287543", "20260701"),
]


def kind(b: bytes) -> str:
    if b[:4] == b"%PDF": return "pdf"
    if b[:2] == b"PK": return "hwpx"
    if b[:8] == bytes.fromhex("d0cf11e0a1b11ae1"): return "hwp"
    return "bin"


def annexes(lsi: str, ef: str) -> list[dict]:
    """별표 목록. 판본에 따라 세 꼴이 있다 — 제목 링크와 HWP·PDF(대부분), 제목은 글자이고 HWP·PDF(2009년 초 등),
    파일 없이 텍스트 내려받기만(2011-01-28·03-07). 별표 영역(<a name="byl">)의 <li>마다 읽는다."""
    r = requests.get(BASE + "lsInfoR.do", params={"lsiSeq": lsi, "efYd": ef, "chrClsCd": "010202", "ancYnChk": "0"},
                     headers={**UA, "Referer": BASE + f"lsInfoP.do?lsiSeq={lsi}"}, timeout=60)
    r.raise_for_status()
    s = r.text
    k = s.find('<a name="byl"></a>')
    if k < 0:
        return []
    out = []
    for li in re.findall(r'<li style="position: relative;">(.*?)</li>', s[k:], re.S):
        txt = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", li.split("<!--")[0]))).strip()
        t = re.search(r"\[별표[^\]]*\][^\[]*", txt)
        if not t:
            continue
        title = re.sub(r"\s+", " ", t.group(0)).strip()
        seq = re.search(r'name="J(\d+)"', li)
        hwp = re.search(r'flSeq=(\d+)[^"]*"[^>]*>\s*<img alt="HWP', li)
        pdf = re.search(r'flSeq=(\d+)[^"]*"[^>]*>\s*<img alt="PDF', li)
        no = re.search(r"\[별표\s*([^\]]*)\]", title)
        out.append({"byl_id": seq.group(1) if seq else "", "no": (no.group(1).strip() if no else "").replace(" ", ""), "title": title,
                    "hwp": hwp.group(1) if hwp else "", "pdf": pdf.group(1) if pdf else ""})
    return out


def get_text(byl: str, lsi: str) -> bytes:
    """파일이 없는 별표: 별표 뷰어가 주는 HTML(상자 그림 문자로 그린 표)."""
    r = requests.get(BASE + "lsBylContentsInfoR.do", params={"bylSeq": byl, "chrClsCd": "010202"},
                     headers={**UA, "Referer": BASE + f"lsInfoP.do?lsiSeq={lsi}"}, timeout=60)
    r.raise_for_status()
    return r.content


def get(fl: str, ext: str, lsi: str) -> bytes:
    p = {"gubun": "", "flSeq": fl, "bylClsCd": "110201"}
    if ext == "hwpx": p["flExt"] = "hwpx"
    r = requests.get(BASE + "flDownload.do", params=p, headers={**UA, "Referer": BASE + f"lsInfoP.do?lsiSeq={lsi}"}, timeout=120)
    r.raise_for_status()
    if not r.content and ext == "hwpx":                      # 옛 판본은 HWPX 변환이 없어 빈 응답이 온다 — HWP로 다시
        p.pop("flExt"); time.sleep(0.5)
        r = requests.get(BASE + "flDownload.do", params=p, headers={**UA, "Referer": BASE + f"lsInfoP.do?lsiSeq={lsi}"}, timeout=120)
        r.raise_for_status()
    return r.content


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for lsi, ef in VERSIONS:
        d = OUT / f"{ef}_{lsi}"
        d.mkdir(exist_ok=True)
        ax = annexes(lsi, ef); time.sleep(0.5)
        if not ax:
            print("별표 없음", ef, lsi)
        for a in ax:
            if not a["hwp"] and not a["pdf"] and a["byl_id"]:
                path = d / f"별표{a['no'] or 'X'}_txt{a['byl_id']}.html"
                if not path.exists():
                    path.write_bytes(get_text(a["byl_id"], lsi)); time.sleep(0.5)
                b = path.read_bytes()
                rows.append([ef, lsi, a["no"], a["title"], "html", a["byl_id"], len(b), hashlib.sha256(b).hexdigest()[:16], path.relative_to(OUT).as_posix()])
                continue
            for ext, fl in [("hwpx", a["hwp"]), ("pdf", a["pdf"])]:
                if not fl:
                    continue
                stem = f"별표{a['no'] or 'X'}_{fl}"
                have = [p for p in d.glob(stem + ".*") if (ext == "pdf") == (p.suffix == ".pdf")]
                have = [h for h in have if h.stat().st_size > 0]
                if have:
                    b = have[0].read_bytes(); path = have[0]
                else:
                    b = get(fl, ext, lsi); time.sleep(0.5)
                    if not b:                                   # 2008~2010년 일부 판본은 PDF 링크가 빈 응답이다(HWP는 있다)
                        print("빈 응답", ef, lsi, a["no"], ext, fl); continue
                    path = d / f"{stem}.{kind(b)}"
                    path.write_bytes(b)
                rows.append([ef, lsi, a["no"], a["title"], path.suffix[1:], fl, len(b), hashlib.sha256(b).hexdigest()[:16], path.relative_to(OUT).as_posix()])
        print(ef, lsi, "별표", len(ax))
    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["efYd", "lsiSeq", "byl_no", "title", "fmt", "flSeq", "bytes", "sha256_16", "path"]); w.writerows(rows)
    print("판본", len(VERSIONS), "파일", len(rows), "→", OUT / "manifest.csv")


if __name__ == "__main__":
    main()
