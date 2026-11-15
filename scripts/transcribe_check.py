#!/usr/bin/env python3
"""옮겨 적기 확인: PROBLEM.md 의 숫자와 낱말이 원본에서 꺼낸 글과 같은지 기계로 견준다.

PROBLEM.md 가 틀리면 답안도, 독립 구현도, 교차 확인도 같은 틀린 글을 보고 함께 틀린다.
그래서 사람 눈 대신 기계로 본다.

    scripts/transcribe_check.sh p1                     # 원본 글을 스스로 찾는다
    scripts/transcribe_check.sh p1 inbox/_text/a.txt   # 견줄 글을 직접 준다 (두 번째 읽기 파일 등)

원본 글을 찾는 순서: PROBLEM.md 첫 줄의 `<!-- 원본: given/파일이름 … -->` → inbox/_text/파일이름.txt,
problems/p1/given/second_read.txt (그림이나 스캔 PDF 를 다른 에이전트가 따로 읽어 적은 것), 글 파일이면 given/ 이나 inbox/ 의 그 파일.

견주는 것: 숫자(쉼표는 뗀다, 음수 부호 포함), 영문 대문자 낱말(한 글자도), 꺾쇠 속 이름(<종목>),
비교 기호(<=, >=, <, >, !=), 비교 낱말(이상, 이하, 초과, 미만, 보다 크, 보다 작, 같거나, 넘).
≤ ≥ ≠ − × 는 <= >= != - x 와 같은 것으로 본다.
  - 옮긴 글에만 있는 것  → 잘못 옮겼거나 지어 넣은 것. 반드시 본다.
  - 원본의 문제 구간에만 있는 것 → 빠뜨린 것. 구간을 찾았을 때만 본다.
  - 개수는 같은데 순서가 다른 곳(두 숫자의 자리 바꿈 등) → "확인"으로 5곳까지 보인다. 종료 코드는 바꾸지 않는다.
문장 전체를 견주는 것은 아니다(낱말 하나를 다른 낱말로 바꾼 것은 위에 든 것이 아니면 못 잡는다).
종료 코드: 0 개수가 같다, 1 다른 것이 있다, 2 견줄 원본 글이 없다.
"""
import difflib
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 앞에서부터: 자리표(<종목>), 음수 부호가 붙을 수 있는 수, 대문자 낱말(두 글자 이상), 대문자 한 글자,
# 비교 기호, 비교 낱말. 자리표의 꺾쇠는 비교 기호로 세지 않는다(자리표를 먼저 찾는다)
TOKEN = re.compile(r"<[^<>\s][^<>\n]{0,18}[^<>\s]>|<[^<>\s=]>"
                   r"|(?<![\w)\]])-?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?"
                   r"|[A-Z][A-Z0-9_]{1,}|(?<![A-Za-z0-9_])[A-Z](?![A-Za-z0-9_])"
                   r"|<=|>=|!=|(?<![-=<>])<(?![<=])|(?<![-=<>])>(?![>=])"
                   r"|이상|이하|초과|미만|보다\s*크|보다\s*작|같거나|넘")
# 모양만 다른 글자를 ASCII 로 맞춘다(≤ 는 <= 와 같다)
SAME = {"−": "-", "×": "x", "≤": "<=", "≥": ">=", "≠": "!="}


def clean(text):
    """표 구분줄, 코드 울타리, 주석 줄처럼 옮길 때 덧붙인 것을 뺀다."""
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("<!--") or s.startswith("```") or re.fullmatch(r"\|?[\s:|-]+\|?", s or "x"):
            continue
        out.append(ln)
    return "\n".join(out)


def normalize(text):
    for a, b in SAME.items():
        text = text.replace(a, b)
    return re.sub(r"(?m)^([ \t]*>)+", lambda m: " " * len(m.group(0)), text)   # 인용 표시(>)는 비교 기호가 아니다


def token_seq(text):
    """뽑은 것을 나온 순서대로: [(뽑은 것, 시작, 끝)]. 위치는 normalize 한 글 기준"""
    out = []
    for m in TOKEN.finditer(text):
        t = m.group(0)
        if t[0].isdigit() or t[0] == "-":
            t = t.replace(",", "").rstrip(".")
        elif t.startswith("보다"):
            t = "보다 " + t[-1]
        out.append((t, m.start(), m.end()))
    return out


def tokens(text):
    return Counter(t for t, _, _ in token_seq(normalize(text)))


def around(text, seq, i, j):
    """seq[i:j] 를 앞뒤 낱말과 함께 한 줄로"""
    if not seq:
        return "(없음)"
    if i >= len(seq):
        a = b = seq[-1][2]
    elif i >= j:
        a = b = seq[i][1]
    else:
        a, b = seq[i][1], seq[j - 1][2]
    s = text[max(0, a - 20):b + 20]
    return "…" + re.sub(r"\s+", " ", s).strip() + "…"


def order_diffs(problem, span):
    """개수는 같아도 순서가 다른 곳(두 숫자의 자리 바꿈 등). [(옮긴 글 쪽, 원본 쪽)]"""
    pt, st = normalize(clean(problem)), normalize(span)
    ps, ss = token_seq(pt), token_seq(st)
    sm = difflib.SequenceMatcher(None, [t for t, _, _ in ps], [t for t, _, _ in ss], autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            out.append((around(pt, ps, i1, i2), around(st, ss, j1, j2)))
    return out


def squash(s):
    return re.sub(r"[\s|`*#>-]+", "", s)


def find_span(source, problem):
    """원본 글에서 이 문제에 해당하는 구간. 첫 줄과 끝 줄을 찾지 못하면 None."""
    lines = [ln for ln in clean(problem).splitlines() if len(squash(ln)) >= 6]
    if len(lines) < 2:
        return None
    src = source
    sq = squash(src)
    a = sq.find(squash(lines[0])[:30])
    b = sq.rfind(squash(lines[-1])[-30:])
    if a < 0 or b < 0 or b <= a:
        return None
    # 뭉갠 글의 위치를 원래 글의 위치로 되돌린다
    pos, idx = [], 0
    for i, ch in enumerate(src):
        if not re.match(r"[\s|`*#>-]", ch):
            pos.append(i)
    start = pos[a]
    end = pos[min(len(pos) - 1, b + len(squash(lines[-1])[-30:]) - 1)] + 1
    return src[start:end]


def source_candidates(pdir):
    cands = []
    prob = (pdir / "PROBLEM.md").read_text(encoding="utf-8", errors="replace")
    text_dir = ROOT / "inbox" / "_text"
    m = re.search(r"<!--\s*원본:\s*(\S+)", prob)
    if m:
        n = Path(m.group(1).rstrip(".,")).name
        if text_dir.is_dir():
            cands += sorted(text_dir.glob(f"{Path(n).stem}*.txt"))
        for base in (pdir / "given", ROOT / "inbox"):
            f = base / n
            if f.exists() and f.suffix.lower() in (".txt", ".md", ".text", ""):
                cands.append(f)
    if not cands:
        # 이름으로 못 찾으면, 문제의 첫 줄이 들어 있는 글을 찾는다
        lines = [ln for ln in clean(prob).splitlines() if len(squash(ln)) >= 6]
        key = squash(lines[0])[:30] if lines else ""
        pool = (sorted(text_dir.glob("*.txt")) if text_dir.is_dir() else []) + sorted((ROOT / "inbox").glob("*.txt"))
        for f in pool:
            if key and key in squash(f.read_text(encoding="utf-8", errors="replace")):
                cands.append(f)
    second = pdir / "given" / "second_read.txt"
    if second.exists():
        cands.append(second)
    seen, out = set(), []
    for c in cands:
        if c.resolve() not in seen:
            seen.add(c.resolve())
            out.append(c)
    return out


def compare(problem, source, label):
    p = tokens(clean(problem))
    whole = tokens(source)
    only_problem = {t: n - whole.get(t, 0) for t, n in p.items() if n > whole.get(t, 0)}
    span = find_span(source, problem)
    only_source = {}
    if span is not None:
        s = tokens(span)
        only_source = {t: n - p.get(t, 0) for t, n in s.items() if n > p.get(t, 0)}
    print(f"견준 원본 글: {label}")
    print(f"  옮긴 글의 숫자·낱말 {sum(p.values())}개 ({len(p)}종)")
    if only_problem:
        print("  **옮긴 글에만 있다 (잘못 옮겼거나 지어 넣음):** "
              + ", ".join(f"{t}×{n}" for t, n in sorted(only_problem.items())[:20]))
    if span is None:
        print("  원본에서 이 문제의 구간을 찾지 못해 빠뜨린 것은 보지 못했다(첫 줄과 끝 줄이 원본과 다르다)")
    elif only_source:
        print("  **원본에만 있다 (빠뜨림):** " + ", ".join(f"{t}×{n}" for t, n in sorted(only_source.items())[:20]))
    bad = bool(only_problem or only_source)
    if not bad:
        print("  다른 것이 없다" + ("" if span is not None else " (옮긴 글 → 원본 방향만 봤다)"))
    moved = []
    if not bad and span is not None:
        moved = order_diffs(problem, span)
        if moved:
            print(f"  확인: 개수는 같은데 순서가 다른 곳 {len(moved)}군데 (표를 옮기며 순서가 바뀌었을 수도 있다)")
            for a, b in moved[:5]:
                print(f"    - 옮긴 글: {a}")
                print(f"      원본:    {b}")
    return bad, len(moved)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    arg = Path(sys.argv[1])
    pdir = arg.resolve() if arg.is_dir() else ROOT / "problems" / sys.argv[1]
    ppath = pdir / "PROBLEM.md"
    if not ppath.exists():
        print(f"PROBLEM.md 가 없습니다: {pdir}")
        return 2
    problem = ppath.read_text(encoding="utf-8", errors="replace")
    cands = [Path(a) for a in sys.argv[2:]] or source_candidates(pdir)
    cands = [c for c in cands if c.exists()]
    if not cands:
        print("견줄 원본 글이 없습니다. 원본이 그림이나 스캔한 PDF 면 다른 에이전트에게 원본을 따로 읽혀 문제의 글 전체를 "
              f"{pdir.name}/given/second_read.txt 에 적게 한 뒤 다시 돌리세요.")
        return 2
    bad, moved = False, 0
    for c in cands:
        raw = c.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp949", "replace")
        b, n = compare(problem, text, str(c.relative_to(ROOT)) if c.is_relative_to(ROOT) else str(c))
        bad, moved = bad or b, moved + n
    print("옮겨 적기 확인: " + ("다른 것이 있다. 원본을 다시 읽고 PROBLEM.md 를 고친다" if bad
                              else "숫자·기호·낱말의 개수가 같다 (문장 전체를 견준 것은 아니다)"))
    if moved:
        print(f"순서가 다른 곳 {moved}군데: 위를 눈으로 본다")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
