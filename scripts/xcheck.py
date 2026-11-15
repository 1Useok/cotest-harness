#!/usr/bin/env python3
"""정답 사례 교차 확인.

다른 모델이 문제 원문과 결정 기록만 보고(기대 출력도 답안도 보지 않고) 입력마다 따로 구한 출력을
tests/*.out 과 견준다. 사람이 기대 출력을 눈으로 확인하던 절차를 대신한다.

    scripts/xcheck.sh status p1                  # 지금 상태
    scripts/xcheck.sh prepare p1 <폴더> [--all]   # <폴더>/cases/ 에 아직 확인하지 않은 입력을 복사 (codex_ask.sh 가 부른다)
    scripts/xcheck.sh ingest p1 <폴더> "<모델>"    # <폴더>/xcheck/*.out 을 받아들인다

파일 (problems/p1/xcheck/):
    <사례>.out     다른 모델이 구한 출력
    INDEX.json     사례마다 그때의 입력 지문, 모델, 시각
    RESOLVED.md    두 출력이 다를 때 어느 쪽이 맞는지 가린 기록. 표: | 사례 | 맞는 쪽 | 원문 근거 |
"""
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 4096     # 이보다 큰 입력은 손으로 따라가기 어려워 뺀다
MAX_LINES = 80
MIN_REASON = 8       # 근거 칸이 이보다 짧으면 가린 것으로 치지 않는다


def sha(data):
    return hashlib.sha256(data).hexdigest()[:12]


def norm(data):
    """끝의 빈 줄과 \\r 차이는 같은 것으로 본다. 줄 안의 글자는 한 글자도 봐주지 않는다."""
    return data.replace(b"\r\n", b"\n").rstrip(b"\n")


def problem_dir(arg):
    p = Path(arg)
    return p.resolve() if p.is_dir() else ROOT / "problems" / arg


def load_index(pdir):
    try:
        return json.loads((pdir / "xcheck" / "INDEX.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def eligible(path):
    data = path.read_bytes()
    return len(data) <= MAX_BYTES and data.count(b"\n") <= MAX_LINES


def resolved(pdir):
    """RESOLVED.md 의 표에서 {사례: 근거}."""
    out = {}
    path = pdir / "xcheck" / "RESOLVED.md"
    if not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 3 or set(cells[0]) <= set("-: ") or cells[0] in ("사례", ""):
            continue
        name = cells[0].strip("`").removesuffix(".in").removesuffix(".out")
        reason = cells[-1]
        if len(reason) >= MIN_REASON:
            out[name] = f"{cells[1]}: {reason}"
    return out


def first_diff(a, b):
    la, lb = a.decode("utf-8", "replace").split("\n"), b.decode("utf-8", "replace").split("\n")
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else "(없음)"
        y = lb[i] if i < len(lb) else "(없음)"
        if x != y:
            return f"{i + 1}째 줄: 기대 출력 `{x[:60]}` / 다른 모델 `{y[:60]}`"
    return "같다"


def status(pdir):
    """교차 확인 상태. ran 이 False 면 한 번도 하지 않은 것이다."""
    tests = sorted((pdir / "tests").glob("*.in"))
    index = load_index(pdir)
    res = resolved(pdir)
    st = {"ran": bool(index), "total": len(tests), "match": [], "mismatch": [], "resolved": [],
          "unchecked": [], "too_big": [], "models": sorted({v.get("model", "?") for v in index.values()})}
    for t in tests:
        stem = t.stem
        exp = t.with_suffix(".out")
        other = pdir / "xcheck" / f"{stem}.out"
        rec = index.get(stem)
        if not rec or not other.exists() or rec.get("in_sha") != sha(t.read_bytes()):
            (st["unchecked"] if eligible(t) else st["too_big"]).append(stem)
            continue
        if not exp.exists():
            st["unchecked"].append(stem)
            continue
        a, b = exp.read_bytes(), other.read_bytes()
        if norm(a) == norm(b):
            st["match"].append(stem)
        elif stem in res:
            st["resolved"].append((stem, res[stem]))
        else:
            st["mismatch"].append((stem, first_diff(norm(a), norm(b))))
    return st


def summary(st):
    if not st["ran"]:
        return "아직 하지 않았다"
    parts = [f"{st['total']}개 중 {len(st['match'])}개가 다른 모델({', '.join(st['models'])})이 원문만 보고 구한 출력과 같다"]
    if st["mismatch"]:
        parts.append("다른 것 " + str(len(st["mismatch"])) + "개: " + "; ".join(f"{n} ({d})" for n, d in st["mismatch"][:3]))
    if st["resolved"]:
        parts.append("달랐지만 원문으로 가린 것 " + str(len(st["resolved"])) + "개: " + "; ".join(f"{n} ({r[:80]})" for n, r in st["resolved"][:3]))
    if st["unchecked"]:
        parts.append("아직 안 본 사례 " + str(len(st["unchecked"])) + "개: " + ", ".join(st["unchecked"][:6]))
    if st["too_big"]:
        parts.append("커서 뺀 사례 " + str(len(st["too_big"])) + "개")
    return ". ".join(parts)


def prepare(pdir, work, everything):
    st = status(pdir)
    todo = [t for t in sorted((pdir / "tests").glob("*.in"))
            if eligible(t) and (everything or t.stem in st["unchecked"] or not st["ran"])]
    cases = Path(work) / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    for t in todo:
        shutil.copy(t, cases / t.name)
    print(f"{len(todo)}개 사례를 넘긴다" + (f" (커서 뺀 것 {len(st['too_big'])}개)" if st["too_big"] else ""))
    return 0 if todo else 5


def ingest(pdir, work, model):
    src = Path(work) / "xcheck"
    dst = pdir / "xcheck"
    dst.mkdir(exist_ok=True)
    index = load_index(pdir)
    got = 0
    for f in sorted(src.glob("*.out")):
        t = pdir / "tests" / f"{f.stem}.in"
        if not t.exists():
            continue
        shutil.copy(f, dst / f.name)
        index[f.stem] = {"in_sha": sha(t.read_bytes()), "model": model, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        got += 1
    (dst / "INDEX.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    st = status(pdir)
    print(f"받은 출력 {got}개. 교차 확인: {summary(st)}")
    for n, d in st["mismatch"]:
        print(f"  다름 {n}: {d}")
    return 0 if got else 4


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cmd, pdir = sys.argv[1], problem_dir(sys.argv[2])
    if not (pdir / "tests").is_dir():
        print(f"tests/ 가 없습니다: {pdir}")
        return 2
    if cmd == "status":
        st = status(pdir)
        print(summary(st))
        for n, d in st["mismatch"]:
            print(f"  다름 {n}: {d}")
        return 0
    if cmd == "prepare":
        return prepare(pdir, sys.argv[3], "--all" in sys.argv[4:])
    if cmd == "ingest":
        return ingest(pdir, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "?")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
