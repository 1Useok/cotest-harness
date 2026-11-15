#!/usr/bin/env python3
"""변형 시험: 테스트가 버그를 잡을 힘이 있는지 잰다.

제출 코드의 비교 연산자와 조건 결합을 하나씩 바꾼 판(변형)을 만든다.
    <  <->  <=      >  <->  >=      ==  <->  !=      &&  <->  ||
변형마다 정답 사례(tests/)와 무작위 입력(gen.py)을 돌려 원래 코드와 출력이 달라지는지 본다.
- 달라지면 "잡았다": 그 경계를 시험이 구별한다는 뜻이다.
- 끝까지 같으면 "살아남았다": 그 경계를 구별하는 입력이 시험에 없다.
  살아남은 변형마다 (1) 그것을 잡는 정답 사례를 추가하거나 (2) 왜 결과가 같은지 한 줄로 적는다.

사용: scripts/mutants.sh p1 [--max 60] [--fuzz 150] [--budget 90]
결과: 문제 폴더의 MUTANTS.txt, MUTANTS.json (verify.sh 가 표에 싣는다)
"""
import argparse
import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWAP = {"<": "<=", "<=": "<", ">": ">=", ">=": ">", "==": "!=", "!=": "==", "&&": "||", "||": "&&"}
SITE = re.compile(r" (<=|>=|==|!=|&&|\|\||<|>) ")
MUT_FLAGS = ["-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
RUN_TIMEOUT = 3.0
MAX_TEST_INPUT = 1_000_000


def is_digit_separator(text, i):
    """text[i] 의 작은따옴표가 숫자 구분자(1'000, 0xFF'FF)인가.
    바로 앞 글자가 숫자·영문자·밑줄이고, 그 낱말이 숫자로 시작해야 한다.
    (L'x', u8'x' 같은 글자 상수의 앞붙이는 영문자로 시작하므로 구분자로 보지 않는다)"""
    if i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_"):
        return False
    j = i - 1
    while j > 0 and (text[j - 1].isalnum() or text[j - 1] in "_'"):
        j -= 1
    return text[j].isdigit()


def mask_code(text):
    """주석, 문자열, 글자 상수, 전처리 줄을 공백으로 가린 같은 길이의 글을 돌려준다."""
    out = list(text)
    i, n = 0, len(text)
    line_start = True
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if line_start and c == "#":
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if text[k] != "\n":
                    out[k] = " "
            i = j
            continue
        if c == "'" and is_digit_separator(text, i):
            # 1'000 같은 숫자 구분자다. 글자 상수가 아니다
            line_start = False
            i += 1
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            j = min(n, j + 1)
            for k in range(i, j):
                if text[k] != "\n":
                    out[k] = " "
            i = j
            continue
        if c == "\n":
            line_start = True
        elif not c.isspace():
            line_start = False
        i += 1
    return "".join(out)


def find_sites(text):
    masked = mask_code(text)
    sites = []
    for m in SITE.finditer(masked):
        op = m.group(1)
        start = m.start(1)
        line_no = text.count("\n", 0, start) + 1
        ls = text.rfind("\n", 0, start) + 1
        le = text.find("\n", start)
        code = text[ls:le if le >= 0 else len(text)].strip()
        sites.append({"pos": start, "op": op, "new": SWAP[op], "line": line_no, "code": code})
    return sites


def run(binary, data, timeout=RUN_TIMEOUT):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0")
    try:
        p = subprocess.run([str(binary)], input=data, capture_output=True, timeout=timeout, env=env)
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired:
        return -999, b""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("problem")
    ap.add_argument("--max", type=int, default=60, help="만들 변형의 최대 수")
    ap.add_argument("--fuzz", type=int, default=150, help="무작위 입력 수")
    ap.add_argument("--budget", type=float, default=90.0, help="전체 시간 한도(초)")
    ap.add_argument("--seed", type=int, default=20261115)
    args = ap.parse_args()

    p = Path(args.problem)
    pdir = p.resolve() if p.is_dir() else (ROOT / "problems" / args.problem).resolve()
    name = pdir.name
    src = pdir / f"{name}.cpp"
    if not src.exists():
        sys.exit(f"제출 파일이 없습니다: {src}")
    text = src.read_text(encoding="utf-8")
    sha = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
    t0 = time.perf_counter()

    work = pdir / "build" / "mutants"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    # 기준: 원래 코드를 같은 옵션으로 빌드한다
    ref_bin = work / "ref"
    r = subprocess.run(["g++", *MUT_FLAGS, "-o", str(ref_bin), str(src)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("원래 코드가 컴파일되지 않습니다:\n" + r.stderr[:500])

    # 입력 모으기: 정답 사례 + 무작위
    inputs = []   # (이름, 데이터, 정답 사례인가)
    for t in sorted((pdir / "tests").glob("*.in")):
        data = t.read_bytes()
        if len(data) <= MAX_TEST_INPUT:
            inputs.append((t.name, data, True))
    gen_path = pdir / "gen.py"
    if gen_path.exists() and "TEMPLATE_NOT_FILLED" not in gen_path.read_text(encoding="utf-8"):
        spec = importlib.util.spec_from_file_location("gen_mod", gen_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for i in range(args.fuzz):
            d = mod.gen(random.Random(args.seed + i))
            inputs.append((f"무작위 seed {args.seed + i}", d if isinstance(d, bytes) else str(d).encode(), False))
    if not inputs:
        sys.exit("돌릴 입력이 없습니다(tests/ 와 gen.py 가 모두 비었다)")
    ref_out = []
    for nm, data, _ in inputs:
        rc, out = run(ref_bin, data, timeout=RUN_TIMEOUT * 2)
        ref_out.append((rc, out))

    sites = find_sites(text)
    total_sites = len(sites)
    if len(sites) > args.max:
        rng = random.Random(int(sha, 16))
        sites = sorted(rng.sample(sites, args.max), key=lambda s: s["pos"])

    def one(idx_site):
        idx, s = idx_site
        if time.perf_counter() - t0 > args.budget:
            return {**s, "result": "시간 부족"}
        mutated = text[:s["pos"]] + s["new"] + text[s["pos"] + len(s["op"]):]
        msrc = work / f"m{idx}.cpp"
        mbin = work / f"m{idx}"
        msrc.write_text(mutated, encoding="utf-8")
        c = subprocess.run(["g++", *MUT_FLAGS, "-w", "-o", str(mbin), str(msrc)], capture_output=True, text=True)
        if c.returncode != 0:
            return {**s, "result": "컴파일 안 됨"}
        for (nm, data, is_test), (rrc, rout) in zip(inputs, ref_out):
            if time.perf_counter() - t0 > args.budget * 1.5:
                return {**s, "result": "시간 부족"}
            rc, out = run(mbin, data)
            if rc != rrc or out != rout:
                mbin.unlink(missing_ok=True)
                return {**s, "result": "잡음", "by": nm, "by_test": is_test}
        mbin.unlink(missing_ok=True)
        return {**s, "result": "살아남음"}

    with ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4))) as ex:
        results = list(ex.map(one, enumerate(sites)))

    valid = [r for r in results if r["result"] in ("잡음", "살아남음")]
    killed = [r for r in valid if r["result"] == "잡음"]
    by_test = [r for r in killed if r["by_test"]]
    survivors = [r for r in valid if r["result"] == "살아남음"]
    skipped = [r for r in results if r["result"] not in ("잡음", "살아남음")]
    elapsed = time.perf_counter() - t0

    lines = [
        f"# 변형 시험: {name}",
        "",
        f"- 파일: {name}.cpp (sha256 앞 16자리 {sha})",
        f"- 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}, 걸린 시간 {elapsed:.0f}초",
        f"- 바꿀 수 있는 자리 {total_sites}곳 중 {len(sites)}곳을 바꿔 보았다",
        f"- 입력: 정답 사례 {sum(1 for i in inputs if i[2])}개 + 무작위 {sum(1 for i in inputs if not i[2])}개",
        "",
        f"**변형 {len(valid)}개 중 {len(killed)}개를 잡았다.** "
        f"(정답 사례가 잡은 것 {len(by_test)}, 무작위 입력만 잡은 것 {len(killed) - len(by_test)}, "
        f"살아남은 것 {len(survivors)})",
        "",
    ]
    if survivors:
        lines += ["## 살아남은 변형 (이 경계를 구별하는 입력이 시험에 없다)", "",
                  "| 줄 | 바꾼 것 | 코드 |", "|---|---|---|"]
        for s in survivors:
            op, new = s["op"].replace("|", "\\|"), s["new"].replace("|", "\\|")
            lines.append(f"| {s['line']} | `{op}` → `{new}` | `{s['code'][:100]}` |".replace("||", "\\|\\|"))
        lines += ["", "변형마다 하나를 한다: 잡는 정답 사례를 추가한다 / 결과가 같은 이유를 REPORT.md 에 한 줄로 적는다.", ""]
    fuzz_only = [r for r in killed if not r["by_test"]]
    if fuzz_only:
        lines += ["## 무작위 입력만 잡은 변형 (기대 출력이 있는 정답 사례로는 구별되지 않는다)", "",
                  "| 줄 | 바꾼 것 | 잡은 입력 |", "|---|---|---|"]
        for s in fuzz_only[:20]:
            lines.append(f"| {s['line']} | `{s['op']}` → `{s['new']}` | {s['by']} |")
        lines.append("")
    if skipped:
        n_c = sum(1 for r in skipped if r["result"] == "컴파일 안 됨")
        n_t = len(skipped) - n_c
        lines.append(f"세지 않은 것: 컴파일되지 않은 변형 {n_c}개, 시간이 모자라 돌리지 못한 변형 {n_t}개.")
    text_out = "\n".join(lines) + "\n"
    (pdir / "MUTANTS.txt").write_text(text_out, encoding="utf-8")
    (pdir / "MUTANTS.json").write_text(json.dumps({
        "name": name, "sha": sha, "total": len(valid), "killed": len(killed),
        "killed_by_tests": len(by_test), "sites": total_sites, "seconds": round(elapsed, 1),
        "survivors": [{"line": s["line"], "change": f"{s['op']} → {s['new']}", "code": s["code"][:160]}
                      for s in survivors],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(text_out)


if __name__ == "__main__":
    main()
