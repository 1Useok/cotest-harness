#!/usr/bin/env python3
"""cotest 검증기.

사용법:
    scripts/verify.sh p1              # problems/p1 을 검증한다
    scripts/verify.sh p1 --fuzz 2000  # 무작위 입력 횟수를 바꾼다
    scripts/final_gate.sh p1          # 같은 검증 + 통과하면 submit/ 에 복사한다
    scripts/final_gate.sh p1 --accept "사람이 승인한 사유"   # 조건부 판정을 사람이 받아들일 때

문제 폴더에 있어야 하는 것:
    <이름>.cpp      제출 파일 (필수)
    tests/*.in, tests/*.out   1층: 정답 사례 (필수)
    xcheck/*.out              다른 모델이 원문만 보고 따로 구한 출력 (scripts/codex_ask.sh cases 가 만든다)
    tests/HUMAN_OK.txt        (있으면) 사람이 눈으로 확인한 사례 이름. 없어도 된다
    EDGE.md         예외 표. 행마다 테스트 파일이 있는지 본다
    check.py        2층: check(inp, out) -> 위반 목록
    gen.py          3층: gen(rng) -> 입력 문자열. gen_big(rng) -> 큰 입력(문자열 하나 또는 목록)
    gen2.py         (있으면) 다른 모델이 답안을 보지 않고 쓴 생성기. gen.py 와 번갈아 쓴다
    alt.cpp         3층: 독립 구현
    known_fail/*.in, *.out    고치지 못하고 남긴 반례(알려진 한계)
    MUTANTS.json    scripts/mutants.sh 의 결과(있으면 표에 싣는다)

판정은 셋 중 하나다.
    PASS    모든 검사를 돌렸고 실패가 없다.
    조건부  실패는 없지만 사람이 알고 받아들여야 할 것이 있다(생략된 검사, 알려진 한계 등).
    FAIL    실패한 검사가 있다.

결과는 화면에 표로 나오고, 문제 폴더의 VERIFY.txt 와 VERIFY.json 에 저장된다.
REPORT.md 에 <!-- VERIFY:BEGIN --> 와 <!-- VERIFY:END --> 가 있으면 그 사이를 최신 결과로 바꾼다.
종료 코드: FAIL 이면 1, 최종 관문에서 조건부인데 승인이 없으면 2, 그 밖에는 0.
"""
import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xcheck  # noqa: E402  정답 사례 교차 확인 (scripts/xcheck.py)

XCHECK_MIN_SHARE = 0.5   # 정답 사례 가운데 다른 모델이 따로 확인한 비율이 이보다 낮으면 조건부

EXAM_FLAGS = ["-std=c++20", "-O2"]                      # 과제 안내문의 명령 그대로
WARN_FLAGS = ["-Wall", "-Wextra", "-Wshadow", "-Wconversion"]
SAN_FLAGS = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
COV_FLAGS = ["-std=c++20", "-O0", "--coverage"]

RUN_TIMEOUT = 5.0        # 한 번 실행의 시간 제한(초)
SLOW_SECONDS = 1.0       # 큰 입력이 이보다 오래 걸리면 조건부(과제의 시간 제한은 모르므로 보수적으로)
GROWTH_MIN_SECONDS = 0.2 # 이보다 빨리 끝나면 성장률을 재지 않는다(잡음이 크다)
GROWTH_WARN_RATIO = 3.2  # 입력 2배에 시간이 이 배수 이상이면 제곱 연산을 의심한다
GROWTH_BLOCK_SHARE = 0.5 # 최대 크기의 시간이 기준의 이 비율 이상일 때만 성장률을 조건부 사유로 삼는다
GROWTH_ODD_RATIO = 5.0   # 2배에 이 배수 이상이면 제곱(4배)으로 설명되지 않는다. 앞 절반과 뒤 절반이 하는 일이 다른 입력일 때 나온다
GROWTH_ODD_SHARE = 0.8   # 그런 입력은 기준의 이 비율 이상 걸릴 때만 조건부 사유로 삼는다
REMEASURE_TIMES = 2      # 기준을 넘거나 성장률이 높으면 이만큼 더 재서 가장 작은 값을 쓴다
LOAD_WALL_RATIO = 1.3    # 벽시계 시간이 CPU 시간의 이 배수를 넘으면 다른 작업이 함께 돌았다고 적는다
MEM_NOTE_MB = 256        # 큰 입력의 최대 메모리가 이보다 크면 알린다(흔한 평가 제한)
MEM_LIMIT_MB = 1024      # 이보다 크면 조건부(과제의 메모리 제한은 모르므로 보수적으로)
CHECKER_LINES_PER_TEST = 6   # 검사기의 힘을 잴 때 사례마다 바꿔 보는 줄 수
CHECKER_MAX_TRIES = 160      # 틀리게 바꾼 출력의 최대 개수
CHECKER_WEAK_SHARE = 0.5     # 이 비율도 못 잡으면 조건부
RARE_KIND_SHARE = 0.005      # 무작위 출력에서 이 비율보다 드문 출력 종류를 알려 준다
FUZZ_BUDGET = 90.0       # 무작위 시험에 쓰는 최대 시간(초)
SAN_FUZZ_LIMIT = 200     # 무작위 입력 중 앞의 몇 개를 검사 옵션 빌드로도 돌릴지
COV_FUZZ_LIMIT = 200     # 무작위 입력 중 앞의 몇 개로 "실행된 줄"을 잴지
COV_MAX_INPUT = 1_000_000  # 이보다 큰 정답 사례는 실행된 줄을 잴 때 건너뛴다(-O0 이라 느리다)
MAX_SAVED_FAILS = 5      # 저장할 실패 입력 수
MINIMIZE_EVALS = 300     # 실패 입력을 줄일 때 쓰는 최대 실행 횟수
MINIMIZE_SECONDS = 15.0  # 실패 입력 하나를 줄이는 데 쓰는 최대 시간(초)
FIXED_SEED_SHARE = 0.6   # 무작위 입력 중 고정 seed 의 비율. 나머지는 실행할 때마다 새 seed
MIN_FINAL_FUZZ = 200     # 최종 관문에서 요구하는 최소 무작위 실행 횟수
MID_BIG_LINES = 20_000   # 중간 크기 비교: 큰 입력을 이 줄 수 근처로 줄여 독립 구현과 견준다
MID_SMALL_LINES = 2_000  # 이 줄 수 근처의 입력에는 검사 옵션 빌드와 check.py 도 돌린다
MID_MIN_SCALE = 0.001    # 중간 크기 비교에서 쓰는 가장 작은 scale
MID_BUDGET = 60.0        # 중간 크기 비교 전체에 쓰는 최대 시간(초)
LIMITS_FILE = ROOT / "limits.conf"   # 안내문의 시간·메모리 제한(있으면). TIME_SECONDS=<수>, MEMORY_MB=<수>

STD_HEADERS = set("""
algorithm any array atomic barrier bit bitset charconv chrono compare complex concepts
condition_variable coroutine deque exception execution filesystem format forward_list fstream
functional future initializer_list iomanip ios iosfwd iostream istream iterator latch limits list
locale map memory memory_resource mutex new numbers numeric optional ostream queue random ranges
ratio regex scoped_allocator semaphore set shared_mutex source_location span sstream stack
stdexcept stop_token streambuf string string_view syncstream system_error thread tuple
type_traits typeindex typeinfo unordered_map unordered_set utility valarray variant vector version
cassert cctype cerrno cfenv cfloat cinttypes climits clocale cmath csetjmp csignal cstdarg
cstddef cstdint cstdio cstdlib cstring ctime cuchar cwchar cwctype
""".split())

VERIFY_BEGIN = "<!-- VERIFY:BEGIN -->"
VERIFY_END = "<!-- VERIFY:END -->"


class Report:
    """검사 결과 표. status: PASS, FAIL, SKIP(돌리지 못함), 확인(사람이나 AI가 봐야 함), 한계(알려진 실패)."""

    def __init__(self):
        self.rows = []
        self.conditions = []   # 판정을 '조건부'로 만드는 사유

    def add(self, name, status, detail=""):
        self.rows.append({"check": name, "status": status, "detail": detail})

    def condition(self, text):
        self.conditions.append(text)

    def failed(self):
        return any(r["status"] == "FAIL" for r in self.rows)

    def has(self, prefix):
        return any(r["check"].startswith(prefix) for r in self.rows)


def resolve_problem_dir(arg):
    p = Path(arg)
    if p.is_dir():
        return p.resolve()
    q = ROOT / "problems" / arg
    if q.is_dir():
        return q.resolve()
    sys.exit(f"문제 폴더를 찾을 수 없습니다: {arg}")


def run(binary, data, timeout=RUN_TIMEOUT, env=None, cwd=None):
    """(종료 코드, 표준 출력, 표준 오류, 걸린 시간, 시간 초과 여부)"""
    start = time.perf_counter()
    try:
        p = subprocess.run([str(binary)], input=data, capture_output=True, timeout=timeout, env=env, cwd=cwd)
        return p.returncode, p.stdout, p.stderr, time.perf_counter() - start, False
    except subprocess.TimeoutExpired as e:
        return -999, e.stdout or b"", e.stderr or b"", timeout, True


# 최대 메모리를 재는 작은 중간 프로세스. 답안을 fork 해서 실행하고 그 실행 하나의 자원 사용량을 적는다.
# 이 검증 프로그램이 답안을 직접 띄워서 재면 안 된다: 리눅스는 exec 직전의 메모리(= 큰 입력을 들고 있는
# 이 프로그램의 크기)까지 그 프로세스의 최대 메모리로 친다. 그래서 작은 프로세스가 대신 띄운다.
_MEASURE_HELPER = r"""
import os, sys, time
t0 = time.perf_counter()
pid = os.fork()
if pid == 0:
    os.execv(sys.argv[2], [sys.argv[2]])
_, status, usage = os.wait4(pid, 0)
with open(sys.argv[1], "w") as f:
    f.write(f"{os.waitstatus_to_exitcode(status)} {usage.ru_maxrss} {time.perf_counter() - t0:.6f}"
            f" {usage.ru_utime + usage.ru_stime:.6f}\n")
"""


def run_measured(binary, data, timeout):
    """큰 입력용. 입력을 파일로 넘기고(평가와 같은 모양) 최대 메모리와 CPU 시간도 잰다.
    CPU 시간은 답안이 실제로 계산한 시간이라, 다른 일이 함께 돌아도 거의 늘지 않는다.
    (종료 코드, 표준 출력, 걸린 시간(벽시계), 시간 초과 여부, 최대 메모리 MB, CPU 시간)"""
    with tempfile.TemporaryDirectory() as td:
        inp, outp, meta = Path(td) / "in.txt", Path(td) / "out.txt", Path(td) / "meta.txt"
        inp.write_bytes(data)
        cmd = [sys.executable, "-S", "-E", "-c", _MEASURE_HELPER, str(meta), str(binary)]
        killed = []
        with open(inp, "rb") as fi, open(outp, "wb") as fo:
            # 새 세션으로 띄워, 시간 초과 때 중간 프로세스와 답안을 함께 끝낸다
            p = subprocess.Popen(cmd, stdin=fi, stdout=fo, stderr=subprocess.DEVNULL, start_new_session=True)

            def stop():
                killed.append(1)
                try:
                    os.killpg(p.pid, 9)
                except ProcessLookupError:
                    pass

            timer = threading.Timer(timeout, stop)
            timer.start()
            try:
                p.wait()
            finally:
                timer.cancel()
        if killed or not meta.exists():
            return -999, b"", timeout, True, 0.0, timeout
        parts = meta.read_text().split()
        return int(parts[0]), outp.read_bytes(), float(parts[2]), False, int(parts[1]) / 1024.0, float(parts[3])


def compile_cpp(src, out, flags, cwd=None):
    cmd = ["g++", *flags, "-o", str(out), str(src)]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return p.returncode == 0, p.stderr


def first_lines(text, n=4):
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return " / ".join(lines[:n])


def first_diff(a, b):
    la = a.decode("utf-8", "replace").split("\n")
    lb = b.decode("utf-8", "replace").split("\n")
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else "(없음)"
        y = lb[i] if i < len(lb) else "(없음)"
        if x != y:
            return f"{i + 1}번째 줄: [{x}] 와 [{y}]"
    return "차이 없음"


def load_function(path, func_name):
    spec = importlib.util.spec_from_file_location(path.stem + "_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, func_name, None), mod


def to_bytes(x):
    return x if isinstance(x, bytes) else str(x).encode("utf-8")


def fmt_ranges(nums):
    """[3,4,5,9] -> '3-5, 9'"""
    nums = sorted(set(nums))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ", ".join(out)


def case_fingerprint(tests_dir, stem):
    """정답 사례 하나(입력과 기대 출력)의 지문. 사람이 확인한 뒤 바뀌었는지 볼 때 쓴다."""
    h = hashlib.sha256()
    for ext in (".in", ".out"):
        p = Path(tests_dir) / (stem + ext)
        h.update(p.read_bytes().replace(b"\r\n", b"\n") if p.exists() else b"<none>")
        h.update(b"\0")
    return h.hexdigest()[:12]


def load_generators(pdir, report):
    """gen.py(답안을 쓴 쪽)와 gen2.py(다른 모델이 답안을 보지 않고 쓴 것)를 읽는다.
    돌려주는 것: [(이름, gen 함수, 모듈)]. gen.py 가 없으면 빈 목록."""
    gens = []
    for fname, required in (("gen.py", True), ("gen2.py", False)):
        path = pdir / fname
        if not path.exists() or "TEMPLATE_NOT_FILLED" in path.read_text(encoding="utf-8", errors="replace"):
            continue
        try:
            fn, mod = load_function(path, "gen")
            gens.append((fname, fn, mod))
        except Exception as e:  # noqa: BLE001
            if required:
                report.add("3층 무작위 입력", "FAIL", f"gen.py 를 불러오지 못했다: {e}")
            else:
                report.add("두 번째 입력 생성기", "확인", f"gen2.py 를 불러오지 못해 쓰지 않았다: {e}")
    if gens and gens[0][0] != "gen.py":
        return []
    return gens


def takes_scale(fn):
    """gen_big 이 scale 인자를 받는가(gen_big(rng, scale=1.0))."""
    try:
        return "scale" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def big_inputs(gens, seed):
    """각 생성기의 gen_big 이 만든 큰 입력들. gen_big 은 문자열 하나나 문자열 목록을 돌려준다.
    돌려주는 것: ([(태그, 입력, 생성기 파일 이름, 순번, scale 을 받는가)], 오류 목록)"""
    out, errors = [], []
    for fname, _, mod in gens:
        gb = getattr(mod, "gen_big", None)
        if not gb:
            continue
        scalable = takes_scale(gb)
        try:
            res = gb(random.Random(seed))
            items = res if isinstance(res, (list, tuple)) else [res]
            for k, item in enumerate(items):
                out.append((f"{fname}#{k + 1}", to_bytes(item), fname, k, scalable))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{fname} 의 gen_big 오류: {e}")
    return out, errors


def scaled_big(gens, fname, seed, scale, cache):
    """gen_big(rng, scale=…) 로 같은 모양을 작게 만든 입력 목록. 같은 seed 라 순번이 같은 입력끼리 모양이 같다."""
    key = (fname, round(scale, 6))
    if key not in cache:
        mod = next(m for f, _, m in gens if f == fname)
        res = mod.gen_big(random.Random(seed), scale=scale)
        items = res if isinstance(res, (list, tuple)) else [res]
        cache[key] = [to_bytes(x) for x in items]
    return cache[key]


def check_includes(src_text, report):
    bad = []
    for m in re.finditer(r'^[ \t]*#[ \t]*include[ \t]*([<"])([^>"]+)[>"]', src_text, re.M):
        kind, name = m.group(1), m.group(2)
        if kind == '"' or name not in STD_HEADERS:
            bad.append(name)
    if bad:
        report.add("표준 라이브러리만 사용", "FAIL", "표준이 아닌 include: " + ", ".join(bad))
    else:
        report.add("표준 라이브러리만 사용", "PASS")


def unexecuted_lines(cov_dir, src_name):
    """gcov 로 한 번도 실행되지 않은 줄 번호를 구한다. (실행 가능한 줄 수, 실행 안 된 줄 목록) 또는 None."""
    for f in cov_dir.glob("*.gcov"):
        f.unlink()
    gcdas = sorted(cov_dir.glob("*.gcda"))
    if not gcdas:
        return None
    subprocess.run(["gcov", gcdas[0].name], cwd=cov_dir, capture_output=True, text=True)
    g = cov_dir / (src_name + ".gcov")
    if not g.exists():
        return None
    executed = {}
    code_of = {}
    for ln in g.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = ln.split(":", 2)
        if len(parts) < 3:
            continue
        cnt, no, code = parts[0].strip(), parts[1].strip(), parts[2]
        if not no.isdigit() or int(no) == 0 or cnt == "-":
            continue
        n = int(no)
        hit = cnt[:1].isdigit()
        executed[n] = executed.get(n, False) or hit
        code_of[n] = code.strip()
    missed = [n for n, hit in executed.items() if not hit and code_of[n] not in ("", "}", "};", "{")]
    return len(executed), sorted(missed)


def load_limits(path=LIMITS_FILE):
    """limits.conf 에서 안내문의 제한을 읽는다. (시간 초 또는 None, 메모리 MB 또는 None).
    source 하지 않고 줄을 읽는다. # 주석과 빈 줄은 건너뛴다. 값이 이상하면 없는 것으로 본다."""
    t_sec, m_mb = None, None
    if not path.exists():
        return t_sec, m_mb
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if "=" not in ln:
            continue
        key, val = (x.strip() for x in ln.split("=", 1))
        val = val.strip("\"'")
        try:
            num = float(val)
        except ValueError:
            continue
        if not (num > 0 and num < 1e7):
            continue
        if key == "TIME_SECONDS":
            t_sec = num
        elif key == "MEMORY_MB":
            m_mb = num
    return t_sec, m_mb


def decision_cards(pdir):
    """DECISIONS.md 의 사람 카드. (모든 카드 번호, '결정:' 줄이 없는 카드 번호) 또는 None(파일이 없다).
    scripts/board.py 의 open_cards 와 같은 판단이다."""
    path = pdir / "DECISIONS.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    part = text.split("## 사람에게 올린 것", 1)
    if len(part) < 2:
        return [], []
    body = re.split(r"\n## ", part[1], 1)[0]
    cards = re.split(r"\n(?=### )", "\n" + body)
    all_ids, open_ids = [], []
    for c in cards:
        m = re.match(r"\s*### (D\d+\w*)", c)
        if not m:
            continue
        all_ids.append(m.group(1))
        if not re.search(r"^\s*-\s*결정\s*:", c, re.M):
            open_ids.append(m.group(1))
    return all_ids, open_ids


def edge_rows(pdir):
    """EDGE.md 의 표에서 (번호, 기대 출력 칸, 테스트 파일 칸, 근거 칸) 을 읽는다."""
    path = pdir / "EDGE.md"
    if not path.exists():
        return None
    rows = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not re.match(r"^\|\s*E\d+\w*\s*\|", ln):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 6:
            rows.append((cells[0], "", "", ""))
            continue
        rows.append((cells[0], cells[3], cells[-1], cells[4]))
    return rows


EDGE_WAITING = "사람 답 대기"


def edge_waiting(expected, reason, cards):
    """기대 출력·근거 칸에 '사람 답 대기'가 남아 있고, 그 칸이 가리키는 카드에 아직 결정이 없으면 True.
    칸이 가리키는 카드(D2 같은 번호)가 모두 DECISIONS.md 에서 답을 받았으면 표를 늦게 고친 것뿐이라 세지 않는다."""
    cell = f"{expected} {reason}"
    if EDGE_WAITING not in cell:
        return False
    ids = re.findall(r"\bD\d+\w*", cell)
    if not ids or cards is None:
        return True
    all_ids, open_ids = cards
    return any(i not in all_ids or i in open_ids for i in ids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("problem")
    ap.add_argument("--fuzz", type=int, default=1000, help="무작위 입력 횟수")
    ap.add_argument("--seed", type=int, default=20261115, help="고정 seed (매번 같은 입력)")
    ap.add_argument("--seed2", type=int, default=None, help="새 seed 묶음의 시작값. 없으면 지금 시각")
    ap.add_argument("--no-cov", action="store_true", help="실행되지 않은 줄을 재지 않는다(빠르게 돌릴 때)")
    ap.add_argument("--final", action="store_true", help="통과하면 submit/ 에 복사한다")
    ap.add_argument("--accept", default="", help="조건부 판정을 사람이 받아들인 사유(최종 관문)")
    args = ap.parse_args()

    # 안내문의 제한(limits.conf). 없으면 보수적인 기본값을 쓴다.
    lim_time, lim_mem = load_limits()
    slow_seconds = lim_time if lim_time else SLOW_SECONDS
    slow_label = (f"기준 CPU {slow_seconds:g}초(안내문)" if lim_time
                  else f"기준 CPU {SLOW_SECONDS:g}초(안내문에 제한 없음)")

    pdir = resolve_problem_dir(args.problem)
    name = pdir.name
    src = pdir / f"{name}.cpp"
    report = Report()
    started = time.strftime("%Y-%m-%d %H:%M:%S")

    if not src.exists():
        sys.exit(f"제출 파일이 없습니다: {src}")

    src_bytes = src.read_bytes()
    sha = hashlib.sha256(src_bytes).hexdigest()[:16]
    build = pdir / "build"
    build.mkdir(exist_ok=True)

    check_includes(src_bytes.decode("utf-8", "replace"), report)

    # --- 평가 명령 그대로 빌드 (파일 하나만 있는 빈 폴더에서) ---
    exam_bin = build / name
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / src.name).write_bytes(src_bytes)
        ok, err = compile_cpp(src.name, name, EXAM_FLAGS, cwd=tmp)
        if ok:
            shutil.copy(Path(tmp) / name, exam_bin)
    exam_cmd = f"g++ {' '.join(EXAM_FLAGS)} -o {name} {name}.cpp"
    if not ok:
        report.add("평가 명령 빌드", "FAIL", first_lines(err))
        finish(report, pdir, name, sha, started, args, exam_cmd, src_bytes)
        return
    report.add("평가 명령 빌드", "PASS", exam_cmd)

    # --- 경고 ---
    ok, err = compile_cpp(src, build / f"{name}_warn", EXAM_FLAGS + WARN_FLAGS)
    n_warn = len(re.findall(r"\bwarning:", err))
    if not ok or n_warn:
        report.add("경고 없음", "FAIL", f"경고 {n_warn}개: " + first_lines(err, 3))
    else:
        report.add("경고 없음", "PASS", " ".join(WARN_FLAGS))

    # --- 검사 옵션 빌드 (메모리 오류, 정의되지 않은 동작) ---
    san_bin = build / f"{name}_san"
    san_ok, err = compile_cpp(src, san_bin, ["-std=c++20", *SAN_FLAGS])
    san_env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=0", UBSAN_OPTIONS="print_stacktrace=1")
    if not san_ok:
        report.add("검사 옵션 빌드", "FAIL", first_lines(err))

    # --- 실행된 줄을 재는 빌드 ---
    cov_dir, cov_bin = build / "cov", None
    if not args.no_cov and shutil.which("gcov"):
        shutil.rmtree(cov_dir, ignore_errors=True)
        cov_dir.mkdir()
        (cov_dir / src.name).write_bytes(src_bytes)
        ok, _ = compile_cpp(src.name, "covbin", COV_FLAGS, cwd=cov_dir)
        if ok:
            cov_bin = cov_dir / "covbin"

    # --- 2층 검사기 불러오기 ---
    check_fn = None
    check_path = pdir / "check.py"
    if check_path.exists() and "TEMPLATE_NOT_FILLED" not in check_path.read_text(encoding="utf-8"):
        try:
            check_fn, _ = load_function(check_path, "check")
            if check_fn is None:
                report.add("2층 불변식 검사", "FAIL", "check.py 에 check(inp, out) 함수가 없다")
        except Exception as e:  # noqa: BLE001
            report.add("2층 불변식 검사", "FAIL", f"check.py 를 불러오지 못했다: {e}")

    def run_check(data, out):
        return check_fn(data.decode("utf-8", "replace"), out.decode("utf-8", "replace")) or []

    # --- 1층: 정답 사례 ---
    tests = sorted((pdir / "tests").glob("*.in"))
    l1_fail, san_fail, l2_fail = [], [], []
    for t in tests:
        exp_path = t.with_suffix(".out")
        if not exp_path.exists():
            l1_fail.append(f"{t.name}: 기대 출력 파일이 없다")
            continue
        data, exp = t.read_bytes(), exp_path.read_bytes()
        rc, out, err, _, timed_out = run(exam_bin, data)
        if timed_out:
            l1_fail.append(f"{t.name}: 시간 초과")
            continue
        if rc != 0:
            l1_fail.append(f"{t.name}: 종료 코드 {rc}")
            continue
        if out != exp:
            note = " (끝의 공백·줄바꿈만 다름)" if out.rstrip() == exp.rstrip() else ""
            l1_fail.append(f"{t.name}: {first_diff(out, exp)}{note}")
        if san_ok:
            rc2, out2, err2, _, to2 = run(san_bin, data, timeout=RUN_TIMEOUT * 4, env=san_env)
            if to2 or rc2 != 0:
                msg = [ln for ln in err2.decode("utf-8", "replace").splitlines() if "error" in ln.lower()]
                san_fail.append(f"{t.name}: {msg[0][:160] if msg else '비정상 종료'}")
            elif out2 != out:
                san_fail.append(f"{t.name}: 검사 옵션 빌드의 출력이 다르다")
        if cov_bin and len(data) <= COV_MAX_INPUT:
            run(cov_bin, data, timeout=RUN_TIMEOUT * 4, cwd=cov_dir)
        if check_fn:
            try:
                v = run_check(data, out)
                if v:
                    l2_fail.append(f"{t.name}: {v[0]}")
            except Exception as e:  # noqa: BLE001
                l2_fail.append(f"{t.name}: check.py 오류 {e}")

    if not tests:
        report.add("1층 정답 사례", "FAIL", "tests/ 에 사례가 없다")
    elif l1_fail:
        report.add("1층 정답 사례", "FAIL", f"{len(l1_fail)}/{len(tests)} 실패. " + " | ".join(l1_fail[:3]))
    else:
        report.add("1층 정답 사례", "PASS", f"{len(tests)}개 전부 일치")

    # --- 사람이 확인한 사례 ---
    ok_path = pdir / "tests" / "HUMAN_OK.txt"
    stems = {t.stem for t in tests}
    human, changed_after = [], []
    if ok_path.exists():
        for ln in ok_path.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = ln.strip().split() if ln.strip() and not ln.startswith("#") else []
            if not parts:
                continue
            w = parts[0].removesuffix(".in")
            if w not in stems:
                continue
            # 둘째 칸은 확인할 때의 지문(scripts/human_ok.sh 가 적는다). 지금 파일과 다르면 확인 뒤에 바뀐 것이다.
            if len(parts) > 1 and parts[1] != case_fingerprint(pdir / "tests", w):
                changed_after.append(w)
            elif w not in human:
                human.append(w)
    if changed_after:
        report.add("사람이 확인한 뒤 바뀐 사례", "확인",
                   f"{len(changed_after)}개: " + ", ".join(changed_after[:6]) + ". 사람이 본 것과 지금의 입력·기대 출력이 다르다. 다시 보여 주고 확인받는다")
        report.condition("사람이 확인한 뒤 기대 출력이 바뀐 사례가 있다: " + ", ".join(changed_after[:6]))
    if human:
        # 사람의 확인은 선택이다. 있으면 싣고, 없어도 판정에 영향을 주지 않는다.
        report.add("사람이 확인한 정답 사례", "PASS", f"{len(human)}개: " + ", ".join(human[:6]))

    # --- 정답 사례 교차 확인: 다른 모델이 원문만 보고 따로 구한 출력과 견준다 ---
    # 기대 출력과 답안을 같은 모델이 썼으므로, 문제를 잘못 읽으면 둘이 함께 틀린다. 그것을 잡는 검사다.
    if tests:
        xs = xcheck.status(pdir)
        x_name = "정답 사례 교차 확인 (다른 모델)"
        if not xs["ran"]:
            report.add(x_name, "확인", f"아직 하지 않았다. `scripts/codex_ask.sh cases {name}`")
            report.condition("정답 사례의 기대 출력을 다른 모델이 따로 확인하지 않았다")
        else:
            checked = len(xs["match"]) + len(xs["resolved"])
            can_check = xs["total"] - len(xs["too_big"])
            detail = xcheck.summary(xs)
            if xs["mismatch"]:
                report.add(x_name, "확인", detail + ". 원문을 다시 읽어 어느 쪽이 맞는지 가리고 xcheck/RESOLVED.md 에 근거를 적는다")
                report.condition("기대 출력이 다른 모델이 따로 구한 출력과 다른 사례가 있다: "
                                 + ", ".join(n for n, _ in xs["mismatch"][:6]))
            elif can_check == 0 and xs["total"]:
                report.add(x_name, "확인", detail + ". 정답 사례가 모두 커서 다른 모델에게 넘기지 못했다")
                report.condition("교차 확인할 수 있는 크기의 정답 사례가 없다")
            elif can_check and checked < can_check * XCHECK_MIN_SHARE:
                report.add(x_name, "확인", detail)
                report.condition(f"정답 사례 {can_check}개 가운데 {checked}개만 다른 모델이 확인했다. "
                                 f"`scripts/codex_ask.sh cases {name}` 을 다시 돌린다")
            elif xs["unchecked"] or xs["resolved"]:
                report.add(x_name, "확인", detail)
            else:
                report.add(x_name, "PASS", detail)

    # --- 사람에게 올린 결정 카드: 사람이 답하지 않은 것이 있으면 추천안으로 푼 것이다 ---
    cards = decision_cards(pdir)
    if cards and cards[0]:
        if cards[1]:
            ids = ", ".join(cards[1])
            report.add("결정 카드", "확인", f"사람이 답하지 않은 카드: {ids} (추천안으로 풀었다)")
            report.condition(f"사람이 답하지 않은 결정 카드가 있다: {ids}")
        else:
            report.add("결정 카드", "PASS", f"사람 카드 {len(cards[0])}개 모두 답을 받았다")

    # --- 예외 표와 테스트의 대응 ---
    rows = edge_rows(pdir)
    if rows is None:
        report.add("예외 표와 테스트의 대응", "SKIP", "EDGE.md 가 없다")
        report.condition("예외 표(EDGE.md)가 없다")
    elif not rows:
        report.add("예외 표와 테스트의 대응", "확인", "EDGE.md 는 있는데 표에 행(E1, E2 …)이 없다")
        report.condition("예외 표에 행이 없다")
    else:
        missing, undecided = [], []
        test_names = {t.name for t in tests}
        for eid, expected, where, reason in rows:
            if not expected or edge_waiting(expected, reason, cards):
                undecided.append(eid)
            names = re.findall(r"[\w.\-]+\.in", where)
            in_tests = any(n in test_names for n in names)
            if not (in_tests or "check.py" in where or "known_fail" in where):
                missing.append(eid)
        if missing or undecided:
            parts = []
            if missing:
                parts.append("테스트가 없는 행: " + ", ".join(missing[:12]))
            if undecided:
                parts.append("기대 출력이 빈 행: " + ", ".join(undecided[:12]))
            report.add("예외 표와 테스트의 대응", "확인", f"{len(rows)}행. " + " / ".join(parts))
            report.condition("예외 표에 테스트나 기대 출력이 없는 행이 있다")
        else:
            report.add("예외 표와 테스트의 대응", "PASS", f"{len(rows)}행 모두 테스트가 있다")

    if san_ok and tests:
        if san_fail:
            report.add("메모리·정의되지 않은 동작 (1층 입력)", "FAIL", " | ".join(san_fail[:3]))
        else:
            report.add("메모리·정의되지 않은 동작 (1층 입력)", "PASS", "address, undefined")

    if check_fn and tests:
        if l2_fail:
            report.add("2층 불변식 검사 (1층 입력)", "FAIL", " | ".join(l2_fail[:3]))
        else:
            report.add("2층 불변식 검사 (1층 입력)", "PASS")
    elif not check_fn and not report.has("2층"):
        report.add("2층 불변식 검사", "SKIP", "check.py 가 없거나 아직 채워지지 않았다")
        report.condition("불변식 검사(check.py)를 돌리지 못했다")

    # --- 검사기의 힘: 정답 출력의 한 줄을 지우거나 다른 줄로 바꾼 "틀린 출력"을 검사기가 잡는가 ---
    if check_fn and tests and not l1_fail and not l2_fail:
        tried = caught = 0
        missed = []
        # 다른 사례의 출력 줄도 바꿔 넣을 후보로 쓴다(둘째 낱말이 같은 줄: 같은 주문에 대한 다른 결과)
        pool = {}
        for t in tests:
            ep = t.with_suffix(".out")
            if ep.exists():
                for ol in ep.read_bytes().decode("utf-8", "replace").splitlines():
                    w = ol.split()
                    if len(w) >= 2:
                        pool.setdefault(w[1], [])
                        if ol not in pool[w[1]]:
                            pool[w[1]].append(ol)
        for t in tests:
            exp_path = t.with_suffix(".out")
            data = t.read_bytes()
            lines = exp_path.read_bytes().decode("utf-8", "replace").split("\n")
            body = lines[:-1] if lines and lines[-1] == "" else lines
            for i in range(min(len(body), CHECKER_LINES_PER_TEST)):
                variants = [("줄 지움", body[:i] + body[i + 1:])]
                other = next((x for x in body if x != body[i]), None)
                if other is not None:
                    variants.append((f"`{body[i]}` → `{other}`", body[:i] + [other] + body[i + 1:]))
                w = body[i].split()
                if len(w) >= 2:
                    for cand in [x for x in pool.get(w[1], []) if x != body[i] and x.split()[0] != w[0]][:2]:
                        variants.append((f"`{body[i]}` → `{cand}`", body[:i] + [cand] + body[i + 1:]))
                for label, bad in variants:
                    if tried >= CHECKER_MAX_TRIES:
                        break
                    tried += 1
                    try:
                        hit = bool(check_fn(data.decode("utf-8", "replace"), "\n".join(bad) + "\n"))
                    except Exception:  # noqa: BLE001
                        hit = True
                    if hit:
                        caught += 1
                    elif len(missed) < 3:
                        missed.append(f"{t.name} {i + 1}번째 줄 {label}")
        if tried:
            detail = f"틀리게 바꾼 출력 {tried}개 중 {caught}개를 잡았다"
            if missed:
                detail += ". 못 잡은 예: " + "; ".join(missed)
            status = "PASS" if caught == tried else "확인"
            report.add("검사기의 힘 (check.py)", status, detail)
            if caught < tried * CHECKER_WEAK_SHARE:
                report.condition(f"검사기(check.py)가 약하다: 틀린 출력 {tried}개 중 {caught}개만 잡는다")

    cov_l1 = unexecuted_lines(cov_dir, src.name) if cov_bin else None

    # --- 3층: 무작위 입력 + 독립 구현 비교 ---
    alt_src = pdir / "alt.cpp"
    gens = load_generators(pdir, report)
    gen_fn = gens[0][1] if gens else None

    alt_bin = None
    if alt_src.exists():
        ok, err = compile_cpp(alt_src, build / "alt", EXAM_FLAGS)
        if ok:
            alt_bin = build / "alt"
        else:
            report.add("독립 구현 빌드", "FAIL", first_lines(err))

    # 독립 구현도 정답 사례의 기대 출력을 그대로 내는가. 기대 출력을 세 번째로 확인하는 셈이다.
    if alt_bin and tests:
        alt_diff = []
        for t in tests:
            exp_path = t.with_suffix(".out")
            if not exp_path.exists():
                continue
            rc2, out2, _, _, to2 = run(alt_bin, t.read_bytes())
            if to2 or rc2 != 0:
                alt_diff.append(f"{t.stem}: 독립 구현이 비정상 종료")
            elif out2 != exp_path.read_bytes():
                alt_diff.append(f"{t.stem}: {first_diff(out2, exp_path.read_bytes())}")
        if alt_diff:
            report.add("정답 사례에서 독립 구현의 출력", "확인",
                       f"{len(alt_diff)}개 사례에서 기대 출력과 다르다. " + " | ".join(alt_diff[:3])
                       + ". 원문을 다시 읽어 어느 쪽이 맞는지 가린다(solve 6번)")
            report.condition(f"독립 구현이 정답 사례 {len(alt_diff)}개에서 기대 출력과 다른 출력을 낸다")
        else:
            report.add("정답 사례에서 독립 구현의 출력", "PASS", f"{len(tests)}개 모두 기대 출력과 같다")

    last_out = [b""]

    def line_kind(line):
        """출력 줄의 종류: 첫 낱말, 그리고 끝 낱말이 대문자 낱말이면 그것까지(예: 'ERR … STATE')."""
        p = line.split()
        if not p:
            return ""
        tail = p[-1]
        if len(p) > 1 and tail.isascii() and tail.replace("_", "").isalpha() and tail.isupper():
            return f"{p[0]} … {tail}"
        return p[0]

    def evaluate(data, use_san):
        """실패하면 (종류, 설명), 통과하면 None."""
        rc, out, _, _, timed_out = run(exam_bin, data)
        if timed_out:
            return "timeout", "시간 초과"
        if rc != 0:
            return "crash", f"종료 코드 {rc}"
        last_out[0] = out
        if alt_bin:
            rc2, out2, _, _, to2 = run(alt_bin, data)
            if to2 or rc2 != 0:
                return "alt_crash", "독립 구현이 비정상 종료했다"
            if out != out2:
                return "diff", "제출 코드와 독립 구현이 다르다. " + first_diff(out, out2)
        if check_fn:
            v = run_check(data, out)
            if v:
                return "check", v[0]
        if use_san and san_ok:
            rc3, out3, err3, _, to3 = run(san_bin, data, timeout=RUN_TIMEOUT * 4, env=san_env)
            if to3 or rc3 != 0:
                msg = [ln for ln in err3.decode("utf-8", "replace").splitlines() if "error" in ln.lower()]
                return "san", (msg[0][:160] if msg else "검사 옵션 빌드가 비정상 종료했다")
            if out3 != out:
                return "san", "검사 옵션 빌드의 출력이 다르다"
        return None

    def minimize(data, kind, use_san):
        lines = data.split(b"\n")
        evals = 0
        deadline = time.perf_counter() + MINIMIZE_SECONDS
        changed = True
        while changed and evals < MINIMIZE_EVALS and time.perf_counter() < deadline:
            changed = False
            i = 0
            while i < len(lines) and evals < MINIMIZE_EVALS and time.perf_counter() < deadline:
                cand = lines[:i] + lines[i + 1:]
                evals += 1
                r = evaluate(b"\n".join(cand), use_san)
                if r and r[0] == kind:
                    lines = cand
                    changed = True
                else:
                    i += 1
        return b"\n".join(lines)

    def mid_compare(bigs):
        """중간 크기 비교. 큰 입력에서만 도는 코드(해시 충돌 처리, 버퍼 비우기, 큐 압축)를 검사한다.
        gen_big 이 scale 을 받는 생성기의 큰 입력마다 약 2천 줄(독립 구현 + 검사 옵션 빌드 + check.py)과
        약 2만 줄(독립 구현)로 줄인 입력을 만들어 답안과 견준다."""
        items = [b for b in bigs if b[4]]
        if not items:
            return
        name_ = "중간 크기 비교 (독립 구현, 검사 옵션)"
        t_mid = time.perf_counter()
        cache, fails, notes = {}, [], []
        compared, deep_done, line_counts = 0, 0, []
        alt_skip, planned, finished = 0, 0, 0
        fail_dir = pdir / "fuzz_fail"
        saved = 0
        broken = set()

        def save(tag, nl, data, out, out2=None):
            nonlocal saved
            if saved >= MAX_SAVED_FAILS:
                return ""
            fail_dir.mkdir(exist_ok=True)
            base = fail_dir / ("mid_" + re.sub(r"[^\w.-]", "_", tag) + f"_{nl}")
            base.with_suffix(".in").write_bytes(data)
            base.with_suffix(".main.out").write_bytes(out)
            if out2 is not None:
                base.with_suffix(".alt.out").write_bytes(out2)
            saved += 1
            return f" ({base.name}.in)"

        # 먼저 모든 입력을 약 2천 줄로, 그다음 약 2만 줄로 본다(시간이 모자라도 검사 옵션 빌드는 모두 돌게)
        for target, deep in ((MID_SMALL_LINES, True), (MID_BIG_LINES, False)):
            for tag, big, gname, k, _ in items:
                planned += 1
                left = MID_BUDGET - (time.perf_counter() - t_mid)
                if left <= 0 or gname in broken:
                    continue
                n_max = max(1, big.count(b"\n"))
                scale = min(1.0, max(MID_MIN_SCALE, target / n_max))
                try:
                    lst = scaled_big(gens, gname, args.seed, scale, cache)
                except Exception as e:  # noqa: BLE001
                    notes.append(f"{gname} 의 gen_big(scale={scale:g}) 오류: {str(e)[:80]}")
                    broken.add(gname)
                    continue
                if k >= len(lst):
                    continue
                data = lst[k]
                nl = max(1, data.count(b"\n"))
                finished += 1
                rc, out, _, _, to = run(exam_bin, data, timeout=RUN_TIMEOUT * 2)
                if to or rc != 0:
                    fails.append(f"{tag} {nl}줄: 답안이 시간 초과 또는 비정상 종료(종료 코드 {rc})" + save(tag, nl, data, out))
                    continue
                if alt_bin:
                    rc2, out2, _, _, to2 = run(alt_bin, data, timeout=min(RUN_TIMEOUT * 6, max(1.0, left)))
                    if to2 or rc2 != 0:
                        alt_skip += 1   # 독립 구현이 이 크기를 시간 안에 못 끝냈다: 이 크기는 건너뛴다
                    elif out2 != out:
                        fails.append(f"{tag} {nl}줄: 독립 구현과 다르다. {first_diff(out, out2)}"
                                     + save(tag, nl, data, out, out2))
                        continue
                    else:
                        compared += 1
                        line_counts.append(nl)
                if deep:
                    if san_ok:
                        rc3, out3, err3, _, to3 = run(san_bin, data, timeout=RUN_TIMEOUT * 4, env=san_env)
                        if to3 or rc3 != 0:
                            msg = [ln for ln in err3.decode("utf-8", "replace").splitlines() if "error" in ln.lower()]
                            fails.append(f"{tag} {nl}줄: 검사 옵션 빌드 " + (msg[0][:160] if msg else "비정상 종료")
                                         + save(tag, nl, data, out))
                            continue
                        if out3 != out:
                            fails.append(f"{tag} {nl}줄: 검사 옵션 빌드의 출력이 다르다" + save(tag, nl, data, out))
                            continue
                    if check_fn:
                        try:
                            v = run_check(data, out)
                        except Exception as e:  # noqa: BLE001
                            v = [f"check.py 오류 {e}"]
                        if v:
                            fails.append(f"{tag} {nl}줄: {v[0]}" + save(tag, nl, data, out))
                            continue
                    deep_done += 1
        elapsed_mid = time.perf_counter() - t_mid
        if line_counts:
            detail = (f"독립 구현과 견준 입력 {compared}개(줄 수 {min(line_counts)}~{max(line_counts)})"
                      if alt_bin else "")
        else:
            detail = "독립 구현과 견준 입력 0개" if alt_bin else ""
        if not alt_bin:
            detail = "독립 구현이 없어 출력은 견주지 못했다"
        detail += f"; 약 {MID_SMALL_LINES}줄 입력 {deep_done}개에 검사 옵션 빌드" + ("·check.py" if check_fn else "")
        if alt_skip:
            detail += f"; 독립 구현이 시간 안에 못 끝내 건너뛴 것 {alt_skip}개"
        if finished < planned and elapsed_mid >= MID_BUDGET:
            detail += f"; 시간 때문에 {planned}개 가운데 {finished}개만"
        detail += f" ({elapsed_mid:.0f}초)"
        if notes:
            detail += ". " + "; ".join(notes[:2])
        if fails:
            report.add(name_, "FAIL", f"{len(fails)}건. " + " | ".join(fails[:3]) + ". " + detail)
        elif notes or (alt_bin and compared == 0):
            report.add(name_, "확인", detail)
        else:
            report.add(name_, "PASS", detail)

    fuzz_done = 0
    if gen_fn:
        fail_dir = pdir / "fuzz_fail"
        if fail_dir.exists():
            shutil.rmtree(fail_dir)
        n_fixed = min(args.fuzz, max(1, int(args.fuzz * FIXED_SEED_SHARE))) if args.fuzz else 0
        seed2 = args.seed2 if args.seed2 is not None else int(time.time())
        seeds = [args.seed + i for i in range(n_fixed)] + [seed2 + i for i in range(args.fuzz - n_fixed)]
        counts, examples = {}, []
        t0 = time.perf_counter()
        gen_error = None
        fuzz_kinds = {}
        active = list(gens)            # 번갈아 쓴다: gen.py, gen2.py, gen.py, ...
        used = {g[0]: 0 for g in gens}
        gen2_note = ""
        for i, seed in enumerate(seeds):
            if time.perf_counter() - t0 > FUZZ_BUDGET:
                break
            gname, gfn, _ = active[i % len(active)]
            try:
                data = to_bytes(gfn(random.Random(seed)))
            except Exception as e:  # noqa: BLE001
                if gname == "gen.py":
                    gen_error = f"gen.py 오류 (seed {seed}): {e}"
                    break
                # 다른 모델이 쓴 생성기가 고장 나면 빼고 계속 간다
                gen2_note = f" gen2.py 는 오류로 중간에 뺐다(seed {seed}: {str(e)[:80]})."
                active = [g for g in active if g[0] == "gen.py"]
                data = to_bytes(gen_fn(random.Random(seed)))
                gname = "gen.py"
            used[gname] += 1
            use_san = i < SAN_FUZZ_LIMIT
            last_out[0] = b""
            try:
                r = evaluate(data, use_san)
            except Exception as e:  # noqa: BLE001
                r = ("check", f"check.py 오류: {e}")
            if cov_bin and i < COV_FUZZ_LIMIT:
                run(cov_bin, data, timeout=RUN_TIMEOUT * 4, cwd=cov_dir)
            fuzz_done += 1
            for ol in last_out[0].decode("utf-8", "replace").splitlines():
                k = line_kind(ol)
                if k:
                    fuzz_kinds[k] = fuzz_kinds.get(k, 0) + 1
            if r:
                kind, detail = r
                counts[kind] = counts.get(kind, 0) + 1
                if len(examples) < MAX_SAVED_FAILS:
                    fail_dir.mkdir(exist_ok=True)
                    try:
                        small = minimize(data, kind, use_san)
                    except Exception:  # noqa: BLE001
                        small = data
                    base = fail_dir / (f"{kind}_{seed}" if gname == "gen.py" else f"{kind}_g2_{seed}")
                    base.with_suffix(".in").write_bytes(small)
                    _, o1, _, _, _ = run(exam_bin, small)
                    base.with_suffix(".main.out").write_bytes(o1)
                    if alt_bin:
                        _, o2, _, _, _ = run(alt_bin, small)
                        base.with_suffix(".alt.out").write_bytes(o2)
                    examples.append(f"{base.name}.in: {detail}")
                if sum(counts.values()) >= 30:
                    break
        elapsed = time.perf_counter() - t0
        label = "3층 무작위 입력 + 독립 구현 비교" if alt_bin else "3층 무작위 입력 (독립 구현 없음)"
        seed_note = f"고정 seed {args.seed} {n_fixed}개 + 새 seed {seed2} {max(0, len(seeds) - n_fixed)}개"
        gen2_unused = len(gens) > 1 and bool(gen2_note) and used.get("gen2.py", 0) == 0
        if len(gens) > 1:
            seed_note += f". 생성기: gen.py {used['gen.py']}회, gen2.py(다른 모델이 씀) {used.get('gen2.py', 0)}회.{gen2_note}"
        else:
            seed_note += ". 생성기: gen.py 하나(답안을 쓴 쪽이 만든 것)"
        if gen_error:
            report.add(label, "FAIL", gen_error)
        elif counts:
            summary = ", ".join(f"{k} {v}건" for k, v in counts.items())
            report.add(label, "FAIL", f"{fuzz_done}회 중 실패: {summary}. fuzz_fail/ 참고. " + " | ".join(examples[:2]))
        else:
            report.add(label, "PASS", f"{fuzz_done}회 실행, 실패 0 ({elapsed:.0f}초, {seed_note})")
            if fuzz_done < MIN_FINAL_FUZZ:
                report.condition(f"무작위 입력을 {fuzz_done}회만 돌렸다(최소 {MIN_FINAL_FUZZ}회)")
        if gen2_unused and not gen_error:
            report.add("두 번째 입력 생성기", "확인", "gen2.py 가 오류로 빠져 한 번도 쓰이지 않았다." + gen2_note)
            report.condition("두 번째 생성기가 한 번도 쓰이지 않았다")
        if not alt_src.exists():
            report.add("독립 구현 비교", "SKIP", "alt.cpp 가 없다")
            report.condition("독립 구현(alt.cpp)과 비교하지 못했다")

        # 정답 사례에 나오는 출력 종류 가운데 무작위 입력에서는 거의 나오지 않는 것
        total_lines = sum(fuzz_kinds.values())
        if total_lines and not gen_error:
            wanted = {}
            for t in tests:
                ep = t.with_suffix(".out")
                if ep.exists():
                    for ol in ep.read_bytes().decode("utf-8", "replace").splitlines():
                        k = line_kind(ol)
                        if k:
                            wanted[k] = wanted.get(k, 0) + 1
            rare = sorted((fuzz_kinds.get(k, 0) / total_lines, k) for k in wanted
                          if fuzz_kinds.get(k, 0) / total_lines < RARE_KIND_SHARE)
            top = sorted(fuzz_kinds.items(), key=lambda kv: -kv[1])[:4]
            mix = ", ".join(f"{k} {v * 100 // total_lines}%" for k, v in top)
            if rare:
                names = ", ".join(f"{k}({share * 100:.1f}%)" for share, k in rare[:8])
                report.add("무작위 입력의 치우침", "확인",
                           f"거의 나오지 않는 출력: {names}. 많이 나온 출력: {mix}. gen.py 가 이 갈래를 더 자주 지나가게 고친다")
            else:
                report.add("무작위 입력의 치우침", "PASS", f"정답 사례의 출력 종류가 모두 나온다. 많이 나온 출력: {mix}")

        bigs, big_errors = big_inputs(gens, args.seed)
        if bigs:
            worst, parts, failed_big, alt_slow = 0.0, [], False, []
            growth_block, growth_info = [], []
            worst_mb, mem_parts = 0.0, []
            scale_cache = {}       # (생성기, scale) -> 작게 만든 입력 목록
            alt_slow_noscale = []  # 독립 구현이 못 끝낸 큰 입력 가운데 scale 을 받지 않는 생성기의 것
            for tag, big, gname, k_big, scalable in bigs:
                rc, big_out, wall, timed_out, peak_mb, cpu = run_measured(exam_bin, big, RUN_TIMEOUT * 2)
                n_lines = max(1, big.count(b"\n"))
                count = f"{n_lines / 10000:.0f}만 줄" if n_lines >= 10000 else f"{n_lines}줄"
                size = f"{len(big) / 1e6:.1f}MB({count})"
                worst_mb = max(worst_mb, peak_mb)
                mem_parts.append(f"{tag} {peak_mb:.0f}MB(줄당 {peak_mb * 1e6 / n_lines:.0f}바이트)")
                if timed_out or rc != 0:
                    report.add("큰 입력 실행 시간", "FAIL", f"{tag} {size}: 시간 초과({RUN_TIMEOUT * 2:.0f}초) 또는 비정상 종료")
                    failed_big = True
                    break
                note = ""
                if alt_bin:
                    rc2, alt_out, _, _, to2 = run(alt_bin, big, timeout=RUN_TIMEOUT * 6)
                    if to2 or rc2 != 0:
                        note = "(독립 구현은 시간 안에 못 끝내 비교 못 함)"
                        alt_slow.append(tag)
                        if not scalable:
                            alt_slow_noscale.append(tag)
                    elif alt_out != big_out:
                        report.add("큰 입력 출력 비교", "FAIL", f"{tag}: 독립 구현과 다르다. " + first_diff(big_out, alt_out))
                    else:
                        note = "(독립 구현과 일치)"
                # 판정은 CPU 시간으로 한다. 벽시계 시간은 창 여러 개에서 컴파일·무작위 시험이 함께 돌면 늘어난다.
                # 성장률: 절반 크기 입력과 견준다. 2배면 정상, 4배에 가까우면 제곱 연산이 숨어 있다.
                # gen_big 이 scale 을 받으면 scale=0.5 로 만든 같은 순번의 입력을 쓴다(개수 머리줄도 맞다).
                # 받지 않으면 앞 절반 줄만 자른다(두 절반이 하는 일이 다르거나 머리줄에 개수가 있으면 틀릴 수 있다).
                half, cpu_half = None, None

                def half_cpu():
                    _, _, _, to_h, _, c = run_measured(exam_bin, half, RUN_TIMEOUT * 2)
                    return None if to_h else c

                def growth_ratio():
                    if cpu >= GROWTH_MIN_SECONDS and cpu_half is not None and cpu_half > 0.01:
                        return cpu / cpu_half
                    return 0.0

                if cpu >= GROWTH_MIN_SECONDS:
                    if scalable:
                        try:
                            hl = scaled_big(gens, gname, args.seed, 0.5, scale_cache)
                            half = hl[k_big] if k_big < len(hl) else None
                        except Exception:  # noqa: BLE001
                            half = None
                    if half is None:
                        lines = big.split(b"\n")
                        half = b"\n".join(lines[: len(lines) // 2]) + b"\n"
                    cpu_half = half_cpu()
                # 기준을 넘거나 성장률이 높으면 더 재서 가장 작은 값을 쓴다(함께 돈 작업의 잡음을 뺀다)
                for _ in range(REMEASURE_TIMES):
                    if cpu <= slow_seconds and growth_ratio() < GROWTH_WARN_RATIO:
                        break
                    rc_r, _, wall_r, to_r, _, cpu_r = run_measured(exam_bin, big, RUN_TIMEOUT * 2)
                    if not to_r and rc_r == 0:
                        cpu, wall = min(cpu, cpu_r), min(wall, wall_r)
                    if half is not None:
                        c = half_cpu()
                        if c is not None:
                            cpu_half = c if cpu_half is None else min(cpu_half, c)
                shown_t = f"CPU {cpu:.2f}초"
                if wall > cpu * LOAD_WALL_RATIO and wall - cpu >= 0.05:
                    shown_t += f"(실제 경과 {wall:.2f}초: 다른 작업이 함께 돌아 늘었다)"
                parts.append(f"{tag} {size} {shown_t}(줄당 {cpu * 1e6 / n_lines:.2f}마이크로초){note}")
                ratio = growth_ratio()
                if ratio >= GROWTH_WARN_RATIO:
                    if cpu >= slow_seconds * (GROWTH_ODD_SHARE if ratio >= GROWTH_ODD_RATIO else GROWTH_BLOCK_SHARE):
                        odd = (", 4배를 크게 넘으면 앞 절반과 뒤 절반이 하는 일이 달라서일 수 있다"
                               if ratio >= GROWTH_ODD_RATIO else "")
                        growth_block.append(f"{tag}: 입력이 2배일 때 CPU 시간이 {ratio:.1f}배다"
                                            f"(제곱에 가까운 연산이 있다{odd})")
                    else:
                        growth_info.append(f"{tag} {ratio:.1f}배" + ("(4배를 크게 넘는다: 앞 절반과 뒤 절반이 하는 일이 다른 입력으로 보인다)" if ratio >= GROWTH_ODD_RATIO else ""))
                worst = max(worst, cpu)
            if not failed_big:
                detail = "; ".join(parts)
                if growth_info:
                    # 입력은 문제의 최대 크기보다 커지지 않으므로, 기준보다 한참 빠르면 제곱 증가여도 문제가 아니다
                    detail += (". 참고(판정에 넣지 않음): 입력이 2배일 때 시간이 " + ", ".join(growth_info)
                               + "이지만 최대 크기에서도 기준보다 충분히 빠르고"
                               " 입력은 최대 크기를 넘지 않는다")
                growth_note = "".join(f" {g}." for g in growth_block)
                if worst > slow_seconds or growth_block:
                    report.add("큰 입력 실행 시간", "확인", f"{detail}.{growth_note} {slow_label}")
                    if worst > slow_seconds:
                        report.condition(f"큰 입력에 CPU {worst:.2f}초가 걸린다({slow_label}, 다시 재도 같다)."
                                         " 과제의 시간 제한을 넘을 수 있다")
                    if growth_block:
                        report.condition("입력이 커질 때 시간이 제곱으로 늘어난다." + growth_note)
                else:
                    report.add("큰 입력 실행 시간", "PASS", f"{detail}. {slow_label}")
                # 메모리: 입력이 큰 만큼 자라는 것은 정상이다. 한도에 가까운지만 본다.
                mem_detail = "; ".join(mem_parts)
                if lim_mem:
                    # 안내문에 메모리 제한이 있으면 그 값이 기준이다
                    if worst_mb > lim_mem:
                        report.add("큰 입력 메모리", "확인",
                                   f"{mem_detail}. 기준 {lim_mem:g}MB(안내문)를 넘는다. 주문 하나가 차지하는 크기와 지우지 않고 쌓이는 것을 본다(knowledge/PERF.md 의 메모리 절)")
                        report.condition(f"큰 입력에 메모리를 {worst_mb:.0f}MB 쓴다. 안내문의 메모리 제한 {lim_mem:g}MB 를 넘는다")
                    else:
                        report.add("큰 입력 메모리", "PASS", f"{mem_detail}. 기준 {lim_mem:g}MB(안내문)")
                elif worst_mb > MEM_NOTE_MB:
                    report.add("큰 입력 메모리", "확인",
                               f"{mem_detail}. {MEM_NOTE_MB}MB 를 넘는다. 주문 하나가 차지하는 크기와 지우지 않고 쌓이는 것을 본다(knowledge/PERF.md 의 메모리 절)."
                               f" 기준 {MEM_NOTE_MB}MB 알림, {MEM_LIMIT_MB}MB 조건부(안내문에 제한 없음)")
                    if worst_mb > MEM_LIMIT_MB:
                        report.condition(f"큰 입력에 메모리를 {worst_mb:.0f}MB 쓴다. 평가 환경의 제한을 넘을 수 있다")
                else:
                    report.add("큰 입력 메모리", "PASS",
                               f"{mem_detail}. 기준 {MEM_NOTE_MB}MB 알림, {MEM_LIMIT_MB}MB 조건부(안내문에 제한 없음)")
                if alt_slow:
                    # 시간은 쟀지만 출력이 맞는지는 견주지 못했다. PASS 로 덮지 않는다.
                    report.add("큰 입력 출력 비교", "확인",
                               "독립 구현이 느려서 출력을 견주지 못한 큰 입력: " + ", ".join(alt_slow)
                               + ". 그 입력을 절반으로 줄여 두 출력을 한 번 견주어 본다")
                # 중간 크기 비교를 한 번도 할 수 없을 때만 조건부로 삼는다(scale 을 받는 생성기가 하나라도 있으면 그쪽에서 견준다)
                if alt_slow_noscale and not any(b[4] for b in bigs):
                    report.condition(f"큰 입력 {len(alt_slow_noscale)}개의 출력을 독립 구현과 견주지 못했고 중간 크기 비교도 없다."
                                     " gen_big 이 scale 을 받게 고치면 자동으로 견준다")
            mid_compare(bigs)
            for e in big_errors:
                report.add("큰 입력 만들기", "확인", e)
        elif big_errors:
            report.add("큰 입력 실행 시간", "FAIL", "; ".join(big_errors))
        else:
            report.add("큰 입력 실행 시간", "SKIP", "gen.py 에 gen_big 이 없다")
            report.condition("큰 입력의 실행 시간을 재지 않았다")
    elif not report.has("3층"):
        report.add("3층 무작위 입력", "SKIP", "gen.py 가 없거나 아직 채워지지 않았다")
        report.condition("무작위 입력 시험(gen.py)을 돌리지 못했다")

    # --- 실행되지 않은 줄 ---
    if cov_bin:
        cov_all = unexecuted_lines(cov_dir, src.name)
        if cov_all is None:
            report.add("실행되지 않은 줄", "SKIP", "gcov 결과를 읽지 못했다")
        else:
            total, missed = cov_all
            l1_missed = len(cov_l1[1]) if cov_l1 else "?"
            if missed:
                report.add("실행되지 않은 줄", "확인",
                           f"{len(missed)}줄이 어떤 시험에서도 실행되지 않았다 (실행 가능한 {total}줄 중. "
                           f"1층만으로는 {l1_missed}줄): {fmt_ranges(missed)}")
            else:
                report.add("실행되지 않은 줄", "PASS",
                           f"실행 가능한 {total}줄이 모두 실행됐다 (1층만으로는 {l1_missed}줄이 남는다)")
    elif not args.no_cov:
        report.add("실행되지 않은 줄", "SKIP", "gcov 를 쓸 수 없다")

    # --- 변형 시험 결과 (scripts/mutants.sh 가 만든 것) ---
    mpath = pdir / "MUTANTS.json"
    if mpath.exists():
        try:
            m = json.loads(mpath.read_text(encoding="utf-8"))
            line = f"변형 {m['total']}개 중 {m['killed']}개를 잡았다"
            if m.get("survivors"):
                line += ". 살아남은 것: " + "; ".join(f"{s['line']}행 {s['change']}" for s in m["survivors"][:6])
            if m.get("sha") != sha:
                report.add("변형 시험", "확인", "결과가 지금 파일의 것이 아니다. scripts/mutants.sh 를 다시 돌린다")
            elif not m.get("total"):
                report.add("변형 시험", "확인", line + f" (바꿀 수 있는 자리 {m.get('sites', '?')}곳). 변형을 하나도 만들지 못했다")
                report.condition("변형을 하나도 만들지 못했다(변형 시험이 돌지 않은 것과 같다)")
            elif m.get("survivors"):
                report.add("변형 시험", "확인", line)
            else:
                report.add("변형 시험", "PASS", line)
        except Exception as e:  # noqa: BLE001
            report.add("변형 시험", "확인", f"MUTANTS.json 을 읽지 못했다: {e}")

    # --- 알려진 한계 ---
    known = sorted((pdir / "known_fail").glob("*.in")) if (pdir / "known_fail").is_dir() else []
    if known:
        still, fixed, noexp = [], [], []
        for k in known:
            exp_path = k.with_suffix(".out")
            if not exp_path.exists():
                noexp.append(k.name)
                continue
            rc, out, _, _, timed_out = run(exam_bin, k.read_bytes(), timeout=RUN_TIMEOUT * 2)
            if timed_out or rc != 0 or out != exp_path.read_bytes():
                still.append(k.name)
            else:
                fixed.append(k.name)
        parts = []
        if still:
            parts.append(f"{len(still)}개 입력에서 답이 틀린다: " + ", ".join(still[:4]))
            report.condition(f"알려진 오답 {len(still)}건 (known_fail/)")
        if fixed:
            parts.append("이제 맞는 것(tests/ 로 옮길 것): " + ", ".join(fixed[:4]))
        if noexp:
            parts.append("기대 출력이 없는 것: " + ", ".join(noexp[:4]))
            report.condition("기대 출력(.out)이 없는 알려진 반례가 있다: " + ", ".join(noexp[:4]))
        report.add("알려진 한계", "한계" if still else "확인", " / ".join(parts))

    finish(report, pdir, name, sha, started, args, exam_cmd, src_bytes)


def finish(report, pdir, name, sha, started, args, exam_cmd, src_bytes):
    # 검증한 파일과 지금 파일이 같은지 판정 직전에 다시 본다. 다르면 이 결과는 지금 파일의 것이 아니다.
    try:
        now_sha = hashlib.sha256((pdir / f"{name}.cpp").read_bytes()).hexdigest()[:16]
    except OSError:
        now_sha = "(읽지 못함)"
    if now_sha != sha:
        report.add("검증한 파일 그대로", "FAIL",
                   f"검증하는 동안 답안 파일이 바뀌었다(처음 {sha}, 지금 {now_sha}). 다시 돌린다")
    failed = report.failed()
    conditions = report.conditions
    verdict = "FAIL" if failed else ("조건부" if conditions else "PASS")
    gxx = subprocess.run(["g++", "--version"], capture_output=True, text=True).stdout.splitlines()[0]

    lines = [
        f"# 검증 결과: {name}",
        "",
        f"- 파일: {name}.cpp (sha256 앞 16자리 {sha})",
        f"- 시각: {started}",
        f"- 컴파일러: {gxx}",
        f"- 평가 명령: {exam_cmd}",
        "",
        "| 검사 | 결과 | 내용 |",
        "|---|---|---|",
    ]
    for r in report.rows:
        detail = r["detail"].replace("|", "/").replace("\n", " ")
        lines.append(f"| {r['check']} | {r['status']} | {detail} |")
    lines += ["", f"**판정: {verdict}**"]
    if conditions and not failed:
        lines.append("")
        lines.append("조건부인 이유 (사람이 알고 받아들여야 제출할 수 있다):")
        lines += [f"- {c}" for c in conditions]
    todo = [r for r in report.rows if r["status"] == "확인"]
    if todo:
        lines.append("")
        lines.append("확인할 것:")
        lines += [f"- {r['check']}: {r['detail']}" for r in todo]

    copied = False
    exit_code = 1 if failed else 0
    if args.final:
        lines.append("")
        if failed:
            lines.append("최종 관문: 통과하지 못했다. submit/ 에 복사하지 않았다.")
        elif conditions and not args.accept.strip():
            lines.append("최종 관문: 조건부라서 복사하지 않았다. 사람이 위 이유를 받아들이면 "
                         f"`scripts/final_gate.sh {name} --accept \"<사람이 말한 사유>\"` 로 다시 돌린다.")
            exit_code = 2
        else:
            submit = ROOT / "submit"
            submit.mkdir(exist_ok=True)
            # 검증한 바이트(처음 읽은 것)를 그대로 쓴다
            (submit / f"{name}.cpp").write_bytes(src_bytes)
            copied = True
            if conditions:
                lines.append(f"최종 관문: 조건부이지만 사람의 승인으로 제출한다. 사유: {args.accept.strip()}")
            lines.append(f"최종 관문: submit/{name}.cpp 로 복사했다 (sha256 앞 16자리 {sha}).")

    text = "\n".join(lines) + "\n"
    (pdir / "VERIFY.txt").write_text(text, encoding="utf-8")
    (pdir / "VERIFY.json").write_text(
        json.dumps({"name": name, "sha": sha, "time": started, "verdict": verdict, "conditions": conditions,
                    "final": bool(args.final), "copied": copied, "accept": args.accept.strip(),
                    "rows": report.rows}, ensure_ascii=False, indent=1), encoding="utf-8")

    rpath = pdir / "REPORT.md"
    if rpath.exists():
        body = rpath.read_text(encoding="utf-8")
        if VERIFY_BEGIN in body and VERIFY_END in body:
            head, rest = body.split(VERIFY_BEGIN, 1)
            _, tail = rest.split(VERIFY_END, 1)
            rpath.write_text(head + VERIFY_BEGIN + "\n" + text + VERIFY_END + tail, encoding="utf-8")

    print(text)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
