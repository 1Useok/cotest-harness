#!/usr/bin/env python3
"""현황판과 타이머.

사용:
    scripts/board.sh                 # 지금 상태를 한 번 보여 준다 (BOARD.md 에도 쓴다)
    scripts/board.sh --watch         # 5초마다 다시 그린다 (다른 터미널에 띄워 둔다)
    scripts/clock.sh start 150       # 작업 시작. 150분짜리. (문제 수는 problems/ 에서 센다)
    scripts/clock.sh mark p1 solve   # p1 풀이 시작을 기록한다
    scripts/clock.sh mark p1 wait    # 사람의 답을 기다리기 시작
    scripts/clock.sh mark p1 resume  # 답을 받고 다시 시작
    scripts/clock.sh mark p1 done    # p1 보고까지 끝

상태는 대화가 아니라 파일에서 읽는다. 그래서 대화가 길어지거나 요약돼도 맞다.
"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAM = ROOT / "logs" / "EXAM.json"
TIMELINE = ROOT / "logs" / "TIMELINE.tsv"
FINISH_RESERVE_MIN = 20     # 제출 준비에 남겨 둘 시간(분)


def now():
    return time.time()


def hhmm(epoch):
    return time.strftime("%H:%M", time.localtime(epoch))


def load_exam():
    if EXAM.exists():
        try:
            return json.loads(EXAM.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return None


def load_events():
    ev = []
    if TIMELINE.exists():
        for ln in TIMELINE.read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 3:
                try:
                    ev.append((float(parts[0]), parts[1], parts[2]))
                except ValueError:
                    pass
    return ev


def cmd_start(minutes):
    EXAM.parent.mkdir(exist_ok=True)
    start = now()
    EXAM.write_text(json.dumps({"start": start, "end": start + minutes * 60, "minutes": minutes}), encoding="utf-8")
    print(f"타이머를 시작했습니다: {hhmm(start)} ~ {hhmm(start + minutes * 60)} ({minutes}분). "
          f"제출 준비는 {hhmm(start + (minutes - FINISH_RESERVE_MIN) * 60)} 에 시작합니다.")


def cmd_mark(problem, event):
    if event not in ("solve", "wait", "resume", "done"):
        sys.exit("사건은 solve, wait, resume, done 중 하나입니다")
    TIMELINE.parent.mkdir(exist_ok=True)
    with TIMELINE.open("a", encoding="utf-8") as f:
        f.write(f"{now():.0f}\t{problem}\t{event}\n")
    print(f"기록했습니다: {hhmm(now())} {problem} {event}")


def problem_times(events, name):
    """(일한 분, 사람 답을 기다린 분, 상태) — 상태: 대기 전 / 풀이 중 / 답 대기 / 끝"""
    evs = [(t, e) for t, p, e in events if p == name]
    if not evs:
        return 0.0, 0.0, "시작 전"
    work = wait = 0.0
    state, since = None, None
    for t, e in evs:
        if state == "work":
            work += t - since
        elif state == "wait":
            wait += t - since
        if e in ("solve", "resume"):
            state = "work"
        elif e == "wait":
            state = "wait"
        elif e == "done":
            state = "done"
        since = t
    if state == "work":
        work += now() - since
    elif state == "wait":
        wait += now() - since
    label = {"work": "풀이 중", "wait": "사람 답 대기", "done": "끝"}.get(state, "시작 전")
    return work / 60, wait / 60, label


def open_cards(pdir):
    """DECISIONS.md 의 사람 카드 가운데 '결정:' 줄이 없는 것의 번호."""
    path = pdir / "DECISIONS.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    part = text.split("## 사람에게 올린 것", 1)
    if len(part) < 2:
        return []
    body = part[1]
    body = re.split(r"\n## ", body, 1)[0]
    cards = re.split(r"\n(?=### )", "\n" + body)
    out = []
    for c in cards:
        m = re.match(r"\s*### (D\d+\w*)", c)
        if m and not re.search(r"^\s*-\s*결정\s*:", c, re.M):
            out.append(m.group(1))
    return out


def stage(pdir, name):
    def has(f):
        p = pdir / f
        return p.exists() and p.stat().st_size > 0
    tmpl = ROOT / "templates" / "main.cpp"
    written = has(f"{name}.cpp") and (not tmpl.exists() or (pdir / f"{name}.cpp").read_bytes() != tmpl.read_bytes())
    steps = [("접수", has("PROBLEM.md")), ("요구사항·예외 표", has("SPEC.md") and has("EDGE.md")),
             ("테스트", any((pdir / "tests").glob("*.in")) if (pdir / "tests").is_dir() else False),
             ("구현", written),
             ("독립 구현", has("alt.cpp")), ("검증", has("VERIFY.json")), ("리뷰", has("REVIEW_codex.md")),
             ("보고", has("REPORT.md"))]
    done = [s for s, ok in steps if ok]
    return done[-1] if done else "빈 폴더", len(done), len(steps)


def problem_row(pdir, events, budget):
    name = pdir.name
    st, n_done, n_all = stage(pdir, name)
    src = pdir / f"{name}.cpp"
    sha = hashlib.sha256(src.read_bytes()).hexdigest()[:16] if src.exists() else ""
    verdict, vtime, stale, conds = "-", "", False, []
    vj = pdir / "VERIFY.json"
    if vj.exists():
        try:
            v = json.loads(vj.read_text(encoding="utf-8"))
            verdict, vtime = v.get("verdict", "?"), v.get("time", "")[11:16]
            stale = v.get("sha") != sha
            conds = v.get("conditions", [])
        except Exception:  # noqa: BLE001
            verdict = "읽기 실패"
    tests = len(list((pdir / "tests").glob("*.in"))) if (pdir / "tests").is_dir() else 0
    # 정답 사례 가운데 다른 모델이 따로 구한 출력과 같은 것의 수 (scripts/xcheck.py)
    human = "-"
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import xcheck
        xs = xcheck.status(pdir)
        if xs["ran"]:
            human = str(len(xs["match"]) + len(xs["resolved"])) + (f", 다름 {len(xs['mismatch'])}" if xs["mismatch"] else "")
    except Exception:  # noqa: BLE001
        human = "?"
    cards = open_cards(pdir)
    known = len(list((pdir / "known_fail").glob("*.in"))) if (pdir / "known_fail").is_dir() else 0
    mut = ""
    mj = pdir / "MUTANTS.json"
    if mj.exists():
        try:
            m = json.loads(mj.read_text(encoding="utf-8"))
            mut = f"{m['killed']}/{m['total']}" + ("(옛 파일)" if m.get("sha") != sha else "")
        except Exception:  # noqa: BLE001
            mut = "?"
    submit = ROOT / "submit" / f"{name}.cpp"
    submitted = submit.exists() and hashlib.sha256(submit.read_bytes()).hexdigest()[:16] == sha
    work, wait, tstate = problem_times(events, name)
    running = sorted(p.name.split("_")[1] for p in (ROOT / "logs").glob(f".running_*_{name}"))
    todo = []
    if cards:
        todo.append("카드에 답하기: " + ", ".join(f"{name}-{c}" for c in cards))
    if verdict == "조건부" and not submitted:
        todo.append("조건 받아들일지 정하기")
    if budget and work > budget and tstate != "끝":
        todo.append(f"예산({budget:.0f}분)을 넘었다: 알림")
    return {
        "name": name, "stage": f"{st} ({n_done}/{n_all})", "state": tstate,
        "work": work, "wait": wait, "verdict": verdict + (" (옛 파일)" if stale and verdict != "-" else ""),
        "vtime": vtime, "tests": tests, "human": human, "mut": mut or "-", "known": known,
        "submitted": submitted, "running": running, "todo": todo, "conds": conds,
    }


def render():
    exam = load_exam()
    events = load_events()
    pdirs = sorted(p for p in (ROOT / "problems").glob("*") if p.is_dir()) if (ROOT / "problems").is_dir() else []
    lines = [f"# 현황판  ({time.strftime('%H:%M:%S')})", ""]
    budget = 0.0
    budgets = {}
    if exam:
        left = (exam["end"] - now()) / 60
        total = exam["minutes"]
        n = max(1, len(pdirs))
        budget = max(5.0, (total - 15 - FINISH_RESERVE_MIN) / n)
        finish_at = exam["end"] - FINISH_RESERVE_MIN * 60
        times = {p.name: problem_times(events, p.name) for p in pdirs}
        solving = [k for k, t in times.items() if t[2] == "풀이 중"]
        if len(solving) >= 2:
            # 동시에 풀면 나누지 않는다: 제출 준비 시각까지 남은 시간 + 이미 일한 시간
            budgets = {k: max(5.0, (finish_at - now()) / 60 + t[0]) for k, t in times.items()}
            per = f"동시에 {len(solving)}문제 풀이 중: 문제당 예산을 나누지 않는다"
        else:
            per = f"문제당 예산 약 {budget:.0f}분"
        lines.append(f"제한 시간: {hhmm(exam['start'])} ~ {hhmm(exam['end'])}  |  남은 시간 **{left:.0f}분**  |  "
                     f"제출 준비 시작 {hhmm(finish_at)} ({(finish_at - now()) / 60:.0f}분 뒤)  |  {per}")
        lines.append(f"제출 준비(/finish) 를 시작할 시각: {hhmm(finish_at)}"
                     + ("  |  **지금 /finish 를 시작한다**" if now() >= finish_at else ""))
    else:
        lines.append("타이머가 꺼져 있다. 켜려면: scripts/clock.sh start 150")
    lines.append("")
    rows = [problem_row(p, events, budgets.get(p.name, budget)) for p in pdirs]
    if rows:
        lines += ["| 문제 | 단계 | 상태 | 일한 시간 | 답 대기 | 마지막 판정 | 정답 사례 (다른 모델 확인) | 변형 잡음 | 알려진 한계 | 제출 복사 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            state = r["state"] + (" · Codex " + "+".join(r["running"]) + " 중" if r["running"] else "")
            lines.append(f"| {r['name']} | {r['stage']} | {state} | {r['work']:.0f}분 | {r['wait']:.0f}분 | "
                         f"{r['verdict']} {r['vtime']} | {r['tests']} ({r['human']}) | {r['mut']} | {r['known']} | "
                         f"{'예' if r['submitted'] else '-'} |")
    else:
        lines.append("아직 접수한 문제가 없다.")
    todo = [(r["name"], t) for r in rows for t in r["todo"]]
    lines += ["", "## 지금 사람이 할 일"]
    lines += [f"- {n}: {t}" for n, t in todo] if todo else ["- 없음"]
    conds = [(r["name"], c) for r in rows for c in r["conds"]]
    if conds:
        lines += ["", "## 조건부인 이유"] + [f"- {n}: {c}" for n, c in conds]
    usage = ROOT / "AI_USAGE.md"
    if usage.exists():
        recent = [ln for ln in usage.read_text(encoding="utf-8", errors="replace").splitlines()
                  if re.match(r"^\| \d{4}-\d{2}-\d{2} ", ln)][-6:]
        if recent:
            lines += ["", "## 최근 한 일"]
            for ln in recent:
                c = [x.strip() for x in ln.strip("|").split("|")]
                if len(c) >= 3:
                    lines.append(f"- {c[0][11:16]} [{c[1]}] {c[2][:110]}")
    return "\n".join(lines) + "\n"


def main():
    a = sys.argv[1:]
    if a[:1] == ["start"]:
        cmd_start(int(a[1]) if len(a) > 1 else 150)
        return
    if a[:1] == ["mark"] and len(a) >= 3:
        cmd_mark(a[1], a[2])
        return
    if "--watch" in a:
        try:
            while True:
                text = render()
                (ROOT / "BOARD.md").write_text(text, encoding="utf-8")
                sys.stdout.write("\033[2J\033[H" + text)
                sys.stdout.flush()
                time.sleep(5)
        except KeyboardInterrupt:
            return
    text = render()
    (ROOT / "BOARD.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
