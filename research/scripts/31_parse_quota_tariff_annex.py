"""
31_parse_quota_tariff_annex.py — 할당관세 규정 판본별 별표(HWP)를 행 단위 표로 읽는다(2026-10-03, 첫 단계).

입력: data/external/할당관세_규정_별표/manifest.csv 와 HWP 파일(scripts/30이 받은 것).
산출: outputs/할당관세_별표_행.csv
  efYd(판본 시행일), lsiSeq, byl_no, title, period_start, period_end(별표 제목에서; 「…까지」만 있으면 시작은 판본 시행일),
  hs4, sub(소호 1~2자리), name_path(품명 계층 「1.」「가.」「(1)」을 > 로 이음), spec(규격 등), rate(문구), rate_num(숫자 하나로 읽히면),
  quota(한계수량 문구), quota_all(「수입전량」 여부), flag
읽는 법: HWP 5.0의 BodyText 레코드에서 표 컨트롤('tbl ') 아래 셀 목록 머리(LIST_HEADER)의 8바이트 뒤 열·행 주소와 병합 수를 읽어
셀을 격자에 놓고, 머리글(호·소호·품명·규격·세율·한계수량)의 열 범위로 칸을 나눈다. 2007년 판은 「관세율표 번호」 한 칸(0404.10).
옛 판본에서 한 칸에 소호를 줄마다 적은 행은 세율 줄 수가 맞으면 줄마다 나눈다. 행 병합 칸은 아래 행의 빈 칸에 채우되 세율은 그 행에
제 소호가 있을 때만 채운다. 같은 내용의 행은 하나만 둔다. 소호 한 자리 머리 행은 그 아래 두 자리 소호가 같은 별표에 있으면 뺀다.
2011-01-28·2011-03-07 판은 별표 파일 없이 텍스트(괘선 문자로 그린 표, html)라 text_rows로 읽는다: 칸 경계는 머리 아래
「├──┼…┤」 줄의 세로선 표시 위치(한글·괘선 두 칸 폭), 호 칸에 값이 있는 줄이 새 항목, 빈 줄이 항목 안의 구획을 가르며 세율이 있는
구획이 행이 된다. 「├┐ … ├┘」 괄호로 한계수량 하나를 나눠 쓰는 행은 flag 'quota_shared'. 앞뒤 HWP 판본과 행이 이어진다(2011-01-28 판
별표 2는 2011-01-01 판과 152행 전부 같음). 2009~2010년 7개 판본은 별표 제목에 기간이 없어
본문 제2조·제3조에서 읽은 기간(ARTICLE_PERIOD)을 넣고 flag 'period_from_articles'; 그래도 없으면 'period_missing'. 원문의 호 오기는 HS4_FIX로 고치고 flag 'hs4_corrected'. 세율 칸에 값이 둘인 행(약 0.8%)은 flag 'rate_multi'.
"""

import html
import re
import struct
import zlib

import olefile

TAG_PARA_TEXT, TAG_CTRL_HEADER, TAG_LIST_HEADER = 67, 71, 72


def records(data):
    i, n = 0, len(data)
    while i + 4 <= n:
        h = struct.unpack_from("<I", data, i)[0]; i += 4
        tag, lvl, size = h & 0x3FF, (h >> 10) & 0x3FF, (h >> 20) & 0xFFF
        if size == 0xFFF:
            size = struct.unpack_from("<I", data, i)[0]; i += 4
        yield tag, lvl, data[i:i + size]; i += size


def para_text(b):
    out, i = [], 0
    while i + 2 <= len(b):
        c = struct.unpack_from("<H", b, i)[0]
        if c < 32:
            if c == 10:                                   # 문단 안 줄바꿈: 칸 안의 「11 19 91 99」가 붙지 않게
                out.append(" "); i += 2
            elif c in (0, 13):
                i += 2
            elif c == 9:                                  # 탭(인라인 컨트롤, 8 WCHAR)도 칸 안의 값을 가른다
                out.append(" "); i += 16
            else:
                i += 16                                   # 확장·인라인 컨트롤은 8 WCHAR
            continue
        out.append(chr(c)); i += 2
    return "".join(out)


def sections(path):
    ole = olefile.OleFileIO(path)
    hdr = ole.openstream("FileHeader").read()
    compressed = bool(struct.unpack_from("<I", hdr, 36)[0] & 1)
    names = sorted([e for e in ole.listdir() if e[0] == "BodyText"], key=lambda e: int(e[1][7:]))
    for e in names:
        d = ole.openstream(e).read()
        yield zlib.decompress(d, -15) if compressed else d


def tables(path):
    """[(표 번호, 행, 열, 행 병합, 열 병합, 문단 목록)]. 셀 목록 머리(LIST_HEADER)의 8바이트 뒤에 열·행 주소와 병합 수가 있다."""
    out, tno = [], -1
    for data in sections(path):
        stack = []
        cell = None
        for tag, lvl, b in records(data):
            if tag == TAG_CTRL_HEADER and b[:4][::-1] == b"tbl ":
                tno += 1; cell = None
                stack.append(lvl)
            elif tag == TAG_LIST_HEADER and stack and lvl == stack[-1] + 1 and len(b) >= 16:
                col, row, cs, rs = struct.unpack_from("<HHHH", b, 8)
                cell = [tno, row, col, rs, cs, []]; out.append(cell)
            elif tag == TAG_PARA_TEXT and cell is not None:
                cell[5].append(para_text(b))
            elif tag == TAG_CTRL_HEADER and stack and lvl <= stack[-1]:
                stack.pop(); cell = None
    return [(t, r, c, rs, cs, [" ".join(p.split()) for p in x if p.strip()]) for t, r, c, rs, cs, x in out]


HEAD = [("호", "hs4"), ("소호", "sub"), ("품명", "name"), ("규격", "spec"), ("세율", "rate"), ("한계수량", "quota")]
LEVEL = [(re.compile(r"^\d+\."), 1), (re.compile(r"^[가-힣]\."), 2), (re.compile(r"^\(\d+\)"), 3),
         (re.compile(r"^\([가-힣]\)"), 4), (re.compile(r"^\d+\)"), 5), (re.compile(r"^[가-힣]\)"), 6)]


def annex_rows(path):
    """별표의 행. 한 칸에 줄이 여럿이고(옛 판본의 「11 / 19 / 41」처럼 소호를 줄마다 적은 경우) 세율 줄 수가 맞으면 줄마다 행을 나눈다."""
    cells = tables(path)
    out = []
    for tno in sorted(set(c[0] for c in cells)):
        cs = [c for c in cells if c[0] == tno]
        cols = {}
        for t, r, c, rs, csp, lines in cs:
            k = "".join(lines).replace(" ", "")
            for h, key in HEAD:
                if (k == h or (h != "호" and k.startswith(h))) and key not in cols and len(k) <= 8:
                    cols[key] = (c, c + max(csp, 1) - 1, r)
        if "hs4" not in cols:                                  # 2007년 판: 「관세율표 번호」 한 칸에 0404.10
            for t, r, c, rs, csp, lines in cs:
                k = "".join(lines).replace(" ", "")
                if k.startswith("관세율표") and len(k) < 12:
                    cols["hs4"] = (c, c + max(csp, 1) - 1, r); break
        if not {"hs4", "name", "rate"} <= set(cols):
            continue
        hrow = max(v[2] for v in cols.values())
        rows, merged = {}, []
        for t, r, c, rs, csp, lines in cs:
            if r <= hrow:
                continue
            for key, (c0, c1, _) in cols.items():
                if c0 <= c <= c1:
                    rows.setdefault(r, {}).setdefault(key, [])
                    rows[r][key] += lines
                    if rs > 1 and lines and key in ("spec", "rate", "quota"):
                        merged.append((key, r, rs, lines))
        for key, r, rs, lines in merged:                       # 행 병합 셀: 이미 있는 아래 행의 빈 칸만 채운다
            for rr in range(r + 1, r + rs):
                if rr in rows and not rows[rr].get(key) and (key != "rate" or rows[rr].get("sub") or rows[rr].get("hs4")):
                    rows[rr][key] = lines                     # 세율은 그 행에 제 소호가 있을 때만 채운다(옛 판본의 긴 병합 칸)
        hs4 = sub = ""; path = {}
        for r in sorted(rows):
            d = rows[r]
            if any(len(x.split()) > 1 and all(t.isdigit() for t in x.split()) for x in d.get("sub", [])):
                d["sub"] = [t for x in d["sub"] for t in x.split()]   # 한 칸에 줄바꿈으로 적은 소호 여럿(2008-01-01 판 2710호)
            subs, rates = d.get("sub", []), d.get("rate", [])
            n = len(subs) if len(subs) > 1 and len(rates) in (1, len(subs)) else 1
            for i in range(n):
                def pick(key):
                    v = d.get(key, [])
                    return v[i] if n > 1 and len(v) == n else " ".join(v)
                h, sb = pick("hs4"), pick("sub")
                if h:
                    dg = re.sub(r"\D", "", h)
                    hs4 = dg[:4] or hs4
                    if len(dg) >= 6 and not sb:
                        sb = dg[4:6]
                    if not sb:
                        sub = ""; path = {}
                if sb:
                    sub = " ".join(re.findall(r"\d+", sb)); path = {}   # 병합 칸에 소호 여럿이면 공백으로 이어 두고 행마다 나눈다
                nm = pick("name")
                lv = next((l for p_, l in LEVEL if p_.match(nm)), 0)
                if nm:
                    path = {k: v for k, v in path.items() if k < lv}
                    path[lv] = nm
                rt = pick("rate")
                if rt.strip():
                    for sb_ in (sub.split() or [""]):
                        out.append({"table": tno, "row": r, "line": i, "hs4": hs4, "sub": sb_,
                                    "name_path": " > ".join(path[k] for k in sorted(path)),
                                    "spec": " ".join(d.get("spec", [])), "rate": rt, "quota": " ".join(d.get("quota", []))})
    seen, uniq = set(), []                                     # 같은 내용의 행은 하나만
    for x in out:
        k = (x["hs4"], x["sub"], x["name_path"], x["spec"], x["rate"], x["quota"])
        if k not in seen:
            seen.add(k); uniq.append(x)
    return uniq


# ── 텍스트 별표(2011-01-28·03-07 판: 별표 파일 없이 괘선 문자로 그린 표) ──

def _w(ch):
    return 2 if ord(ch) >= 0x1100 else 1                  # 한글·괘선·ㆍ는 두 칸 폭


def _cells(line, bounds):
    """줄을 표시 폭 위치로 칸에 나눈다. bounds는 세로선의 표시 위치."""
    out = [""] * (len(bounds) - 1)
    pos = 0
    for ch in line:
        if not (0x2500 <= ord(ch) <= 0x257F):
            for k in range(len(bounds) - 1):
                if bounds[k] < pos < bounds[k + 1]:
                    out[k] += ch; break
        pos += _w(ch)
    return [c.strip() for c in out]


def text_rows(path):
    """칸 경계는 머리 아래 「├──┼──┼…┤」 줄의 세로선 위치. 호 칸에 값이 있는 줄이 새 항목, 빈 줄이 항목 안의 구획을 가른다.
    구획마다 품명(계층 표시로 깊이를 정함)·규격·세율·한계수량을 모으고, 세율이 있는 구획을 행으로 낸다.
    「├┐ … ├┘」 괄호로 묶인 구획들은 한계수량 하나를 나눠 쓴다(shared)."""
    s = open(path, encoding="utf-8", errors="replace").read()
    lines = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", s))).split("\n")
    bounds, blocks, bracket, blank = None, [], None, True
    for l in lines:
        st = l.strip()
        if st.startswith("├") and st.count("┼") == 5:
            pos, b = sum(_w(c) for c in l[:len(l) - len(l.lstrip())]), []
            for ch in l.lstrip():
                if ch in "├┼┤":
                    b.append(pos)
                pos += _w(ch)
            bounds = b
            continue
        if bounds is None or not st.startswith("│"):
            continue
        hs4, sub, name, spec, rate, quota = _cells(l, bounds)
        if hs4 or (blank and (name or spec or rate or quota)):
            blocks.append({"new": bool(hs4), "hs4": hs4, "sub": sub, "name": [], "spec": [], "rate": [], "quota": [], "shared": None})
        blank = not (hs4 or sub or name or spec or rate or quota)
        if blocks:
            b = blocks[-1]
            if sub and not hs4 and b["new"]:
                b["sub"] += sub                            # 좁은 소호 칸: 값이 호 다음 줄에 오기도 한다(2011-03-07 판)
            for k, v in (("name", name), ("spec", spec), ("rate", rate), ("quota", quota)):
                if v:
                    b[k].append(v)
            if "┐" in l:
                bracket = b
            elif bracket is not None and b is not bracket:
                b["shared"] = bracket
            if "┘" in l:
                bracket = None
    out, hs4, sub, path, base = [], "", "", {}, {}
    for b in blocks:
        nm = " ".join(" ".join(b["name"]).split())
        if b["new"]:
            hs4 = re.sub(r"\D", "", b["hs4"])[:4]
            sub = re.sub(r"\D", "", b["sub"])
            base = {k: v for k, v in base.items() if k[0] == hs4 and sub.startswith(k[1]) and k[1] != sub}
            base[(hs4, sub)] = nm
            path = {}
        elif nm:
            lv = next((l_ for p_, l_ in LEVEL if p_.match(nm)), 9)
            path = {k: v for k, v in path.items() if k < lv}
            path[lv] = nm
        if not b["rate"]:
            continue
        quota, shared = " ".join(b["quota"]), False
        if b["shared"] is not None:
            quota, shared = " ".join(b["shared"]["quota"]), True
        elif any(x["shared"] is b for x in blocks):
            shared = True
        names = [base[k] for k in sorted(base, key=lambda k: len(k[1]))] + [path[k] for k in sorted(path)]
        out.append({"hs4": hs4, "sub": sub, "name_path": " > ".join(n for n in names if n), "spec": " ".join(b["spec"]),
                    "rate": " ".join(b["rate"]), "quota": " ".join(quota.split()), "shared": shared})
    return out


# 별표 원문의 오기: 2011-05-12~09-22 판 별표 2는 5403호 행들 사이에 「0403 41 비스코스레이온의 것」을 적었다(0403.41은 없는 소호).
HS4_FIX = {("0403", "41", "비스코스레이온의 것"): "5403"}


# 별표 제목에 기간이 없는 2009~2010년 판본: 본문 제2조(적용시한)·제3조(기간별 할당관세의 적용에 관한 특례)에서 읽은 기간.
# 2009년 상반기 판은 1월에는 별표 3을 갈음해 별표 1을, 2월에는 별표 2를 적용하므로 별표 3의 적용은 3월 1일부터다
# (한계수량은 별표 1이 1월분, 별표 2가 1~2월분, 별표 3이 1~6월분). 본문은 scripts/30이 받은 판본 폴더의 본문.html.
ARTICLE_PERIOD = {
    ("20090101", "1"): ("2009-01-01", "2009-01-31"), ("20090101", "2"): ("2009-02-01", "2009-02-28"),
    ("20090101", "3"): ("2009-03-01", "2009-06-30"),
    ("20090521", "1"): ("2009-01-01", "2009-01-31"), ("20090521", "2"): ("2009-02-01", "2009-02-28"),
    ("20090521", "3"): ("2009-03-01", "2009-06-30"),
    ("20090701", ""): ("2009-07-01", "2009-12-31"),
    ("20100101", ""): ("2010-01-01", "2010-12-31"), ("20100825", ""): ("2010-01-01", "2010-12-31"),
    ("20101012", ""): ("2010-01-01", "2010-12-31"), ("20101115", ""): ("2010-01-01", "2010-12-31"),
}


def period(title: str, ef: str):
    t = re.sub(r"\s+", "", title)
    m = re.search(r"(\d{4})년(\d+)월(\d+)일부터(?:(\d{4})년)?(\d+)월(\d+)일까지", t)
    if m:
        y1, m1, d1, y2, m2, d2 = m.groups()
        return f"{y1}-{int(m1):02d}-{int(d1):02d}", f"{y2 or y1}-{int(m2):02d}-{int(d2):02d}"
    m = re.search(r"(\d{4})년(\d+)월(\d+)일까지", t)
    if m:
        return f"{ef[:4]}-{ef[4:6]}-{ef[6:]}", f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return "", ""


def main() -> None:
    import pandas as pd
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    base = root / "data" / "external" / "할당관세_규정_별표"
    m = pd.read_csv(base / "manifest.csv", dtype=str)
    m = m[m.fmt.isin(["hwp", "html"]) & ~m.title.str.contains("삭제")].drop_duplicates(["efYd", "byl_no", "title"])
    rows = []
    for _, r in m.iterrows():
        ps, pe = period(r.title, r.efYd)
        art = ARTICLE_PERIOD.get((r.efYd, r.byl_no if isinstance(r.byl_no, str) else ""))
        if not ps and art:
            ps, pe = art
        for x in (annex_rows if r.fmt == "hwp" else text_rows)(base / r.path):
            num = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%?\s*", x["rate"])
            flag = [] if num else ["rate_multi"]
            if not ps: flag.append("period_missing")
            elif art and not period(r.title, r.efYd)[0]: flag.append("period_from_articles")
            if x.get("shared"): flag.append("quota_shared")
            fix = HS4_FIX.get((x["hs4"], x["sub"], x["name_path"]))
            if fix:
                x["hs4"] = fix; flag.append("hs4_corrected")
            rows.append({"efYd": r.efYd, "lsiSeq": r.lsiSeq, "byl_no": r.byl_no if isinstance(r.byl_no, str) else "", "title": r.title,
                         "period_start": ps, "period_end": pe, "hs4": x["hs4"], "sub": x["sub"], "name_path": x["name_path"],
                         "spec": x["spec"], "rate": x["rate"], "rate_num": float(num.group(1)) if num else None,
                         "quota": x["quota"], "quota_all": "수입전량" in x["quota"].replace(" ", ""), "flag": ";".join(flag)})
    d = pd.DataFrame(rows)
    # 소호 한 자리(「2931 4」 같은 1단 소호 묶음) 행은 같은 별표에 그 아래 두 자리 소호가 있으면 머리 행이므로 뺀다
    # (병합된 세율 칸이 머리 행에도 채워진 것; 2022년 별표 3의 2931.4가 그 예).
    k2 = {k for k, s2 in zip(zip(d.efYd, d.byl_no, d.hs4, d["sub"].str[:1]), d["sub"]) if len(s2) == 2}
    head = (d["sub"].str.len() == 1) & pd.Series([(e, b_, h, s1) in k2 for e, b_, h, s1 in zip(d.efYd, d.byl_no, d.hs4, d["sub"])], index=d.index)
    d = d[~head].reset_index(drop=True)
    out = root / "outputs" / "할당관세_별표_행.csv"
    d.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"별표 {len(m)}개 → 행 {len(d):,} (판본 {d.efYd.nunique()}), 세율 숫자 {d.rate_num.notna().mean():.1%}, "
          f"기간 있음 {(d.period_start != '').mean():.1%}, 수입전량 {d.quota_all.mean():.1%} → {out}")


if __name__ == "__main__":
    main()
