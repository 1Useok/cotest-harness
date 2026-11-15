#!/usr/bin/env python3
"""원본 대화 기록을 logs/raw/ 로 모으고 목록(logs/MANIFEST.md)을 만든다. AI 사용 내역 제출용.

사용: scripts/collect_logs.sh [--quiet] [--hours N]

모으는 것 (작업 시작 10분 전부터의 것만. 시계가 꺼져 있으면 최근 N시간, 기본 12)
- Claude Code: 이 작업 폴더에서 연 세션의 기록 (~/.claude/projects/<이 폴더>/ 아래의 *.jsonl)
- Codex: ~/.codex 아래의 기록
logs/raw/claude, logs/raw/codex 는 돌 때마다 비우고 다시 채운다. 그래서 지난 연습의 기록이 섞이지 않는다.
(logs/raw/side_questions.json 은 비우지 않고 쌓는다. 범위 안 세션의 곁 질문만 남긴다)

/export 로 내보낸 대화 기록(claude_session*.txt)이 폴더 맨 위에 있으면 logs/ 로 옮긴다.

Claude Code 가 응답을 마칠 때마다 자동으로 돈다(.claude/settings.json 의 Stop 훅).
마지막 응답 한 번은 훅이 돈 뒤에 쓰일 수 있으므로, 제출 직전에 터미널에서 한 번 더 돌린다.

곁 질문(/btw, VS Code 의 옆 대화 패널)은 대화 기록(.jsonl)에 남지 않는다. 그래서 따로 모은다.
- VS Code 가 Windows 쪽에 둔 작업 폴더 저장소(workspaceStorage/<해시>/state.vscdb)에서 읽어
  logs/raw/side_questions.json 에 쌓는다. 확장은 창마다 최근 20개만 두므로, 한 번 모은 것은 지우지 않는다.
- 확장 기록(~/.vscode-server/data/logs/*/exthost*/Anthropic.claude-code/Claude VSCode.log)에서
  곁 질문 요청 시각을 세어, 모은 것보다 많으면 MANIFEST 에 경고를 쓴다.
- 찾은 저장소 경로는 logs/.vscode_state_path 에 적어 두고 다음부터 바로 쓴다(/mnt/c 는 느리다).

시험용 환경 변수
- COTEST_SOURCE_ROOT: 하네스 경로를 이 값으로 보고 Claude 세션 폴더와 VS Code 작업 폴더를 찾는다
  (복사본 /tmp/... 에서 돌릴 때 원래 경로 /home/.../cotest 를 준다)
- COTEST_VSCODE_DB: state.vscdb 경로를 직접 준다(찾기와 캐시를 건너뜀)
"""
import fcntl
import glob
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = Path(os.environ.get("COTEST_SOURCE_ROOT") or ROOT)
HOME = Path.home()
quiet = "--quiet" in sys.argv
hours = 12.0
if "--hours" in sys.argv:
    hours = float(sys.argv[sys.argv.index("--hours") + 1])


def since_epoch():
    exam = ROOT / "logs" / "EXAM.json"
    if exam.exists():
        try:
            return json.loads(exam.read_text(encoding="utf-8"))["start"] - 600, True
        except Exception:  # noqa: BLE001
            pass
    return time.time() - hours * 3600, False


def summarize(path):
    """(처음 시각, 마지막 시각, 모델들, 줄 수)"""
    first = last = ""
    models = set()
    n = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for ln in f:
                n += 1
                try:
                    o = json.loads(ln)
                except Exception:  # noqa: BLE001
                    continue
                ts = o.get("timestamp") or ""
                if isinstance(ts, str) and ts:
                    first = first or ts
                    last = ts
                msg = o.get("message")
                if isinstance(msg, dict) and isinstance(msg.get("model"), str):
                    models.add(msg["model"])
                pl = o.get("payload")
                if isinstance(pl, dict) and isinstance(pl.get("model"), str):
                    models.add(pl["model"])
    except OSError:
        pass
    models.discard("<synthetic>")
    return first[:19], last[:19], sorted(models), n


def move_stray_exports():
    """폴더 맨 위에 내보낸 대화 기록을 logs/ 로 옮긴다. 같은 이름이 있으면 시각을 붙인다."""
    moved = []
    for p in sorted(ROOT.glob("claude_session*.txt")):
        target = ROOT / "logs" / p.name
        if target.exists():
            stamp = time.strftime("%m%d_%H%M%S", time.localtime(p.stat().st_mtime))
            target = ROOT / "logs" / f"{p.stem}_{stamp}{p.suffix}"
        try:
            shutil.move(str(p), str(target))
            moved.append(target.name)
        except OSError:
            pass
    return moved


# ---------- 곁 질문(/btw) ----------

SQ_PATH = ROOT / "logs" / "raw" / "side_questions.json"
VSC_CACHE = ROOT / "logs" / ".vscode_state_path"
EXT_LOG_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(\.\d+)? .*?Received message from webview: (\{.*\})\s*$")


def find_state_db():
    """VS Code 작업 폴더 저장소(state.vscdb). (경로, 못 찾은 이유)"""
    env = os.environ.get("COTEST_VSCODE_DB")
    if env:
        return (Path(env), "") if Path(env).is_file() else (None, f"COTEST_VSCODE_DB 로 준 파일이 없다: {env}")
    try:
        cached = Path(VSC_CACHE.read_text(encoding="utf-8").strip())
        if cached.is_file():
            return cached, ""
    except OSError:
        pass
    want = str(SRC_ROOT).rstrip("/")
    pats = ["/mnt/c/Users/*/AppData/Roaming/Code/User/workspaceStorage/*/workspace.json",
            "/mnt/c/Users/*/AppData/Roaming/Code - Insiders/User/workspaceStorage/*/workspace.json",
            str(HOME / ".config" / "Code" / "User" / "workspaceStorage" / "*" / "workspace.json")]
    hits = []
    for pat in pats:
        for w in glob.glob(pat):
            try:
                txt = Path(w).read_text(encoding="utf-8", errors="replace")
                if want.rsplit("/", 1)[-1] not in txt:
                    continue
                folder = urllib.parse.unquote(str(json.loads(txt).get("folder") or ""))
            except (OSError, ValueError, AttributeError):
                continue
            db = Path(w).parent / "state.vscdb"
            if folder.rstrip("/").endswith(want) and db.is_file():
                hits.append(db)
    if not hits:
        return None, "VS Code 작업 폴더 저장소(state.vscdb)를 찾지 못했다(VS Code 를 안 썼거나 저장 위치가 바뀌었다)"
    hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    try:
        VSC_CACHE.write_text(str(hits[0]) + "\n", encoding="utf-8")
    except OSError:
        pass
    return hits[0], ""


def _find_threads(o, out, depth=0):
    """값 안 어디에 있든 sideQuestionThreads 를 찾는다(안쪽 JSON 글자도 푼다)"""
    if depth > 6:
        return
    if isinstance(o, str):
        if "sideQuestionThreads" in o:
            try:
                _find_threads(json.loads(o), out, depth + 1)
            except ValueError:
                pass
        return
    if isinstance(o, dict):
        th = o.get("sideQuestionThreads")
        if isinstance(th, dict):
            for sid, t in th.items():
                if not isinstance(t, dict) or not isinstance(t.get("entries"), list):
                    continue
                old = out.get(sid)
                key = (t.get("updatedAt") or 0, len(t["entries"]))
                if old is None or key > (old.get("updatedAt") or 0, len(old["entries"])):
                    out[sid] = t
        for k, v in o.items():
            if k != "sideQuestionThreads":
                _find_threads(v, out, depth + 1)
    elif isinstance(o, list):
        for v in o:
            _find_threads(v, out, depth + 1)


def read_threads(db):
    """저장소를 임시 폴더에 복사해 읽는다(VS Code 가 열어 두고 있다). (스레드들, 문제)"""
    tmp = tempfile.mkdtemp(prefix="cotest_vsc_")
    try:
        for suf in ("", "-wal", "-shm"):
            if Path(str(db) + suf).is_file():
                shutil.copy2(str(db) + suf, f"{tmp}/state.vscdb{suf}")
        q = "SELECT key, value FROM ItemTable WHERE CAST(value AS TEXT) LIKE '%sideQuestionThreads%'"
        try:
            con = sqlite3.connect(f"file:{tmp}/state.vscdb?mode=ro", uri=True, timeout=2)
            rows = con.execute(q).fetchall()
        except sqlite3.OperationalError:
            con = sqlite3.connect(f"{tmp}/state.vscdb", timeout=2)  # 복사본이라 쓰기로 열어도 원본은 그대로다
            rows = con.execute(q).fetchall()
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    threads = {}
    for _, v in rows:
        if isinstance(v, bytes):
            v = v.decode("utf-8", errors="replace")
        _find_threads(v, threads)
    problem = ""
    if rows and not threads:
        problem = "저장소에 곁 질문 자리는 있는데 모양을 읽지 못했다(확장의 저장 형식이 바뀌었을 수 있다)"
    return threads, problem


def scan_ext_log(since):
    """확장 기록에서 곁 질문 요청을 찾는다. 시각은 이 컴퓨터의 현지 시각으로 적혀 있다"""
    reqs, files = [], []
    for base in (".vscode-server", ".vscode-server-insiders"):
        for f in glob.glob(str(HOME / base / "data" / "logs" / "*" / "exthost*" / "Anthropic.claude-code" / "*.log")):
            try:
                if os.path.getmtime(f) < since:
                    continue
                fh = open(f, encoding="utf-8", errors="replace")
            except OSError:
                continue
            files.append(f)
            with fh:
                for ln in fh:
                    if "side_question" not in ln or "Received message from webview" not in ln:
                        continue
                    m = EXT_LOG_RE.match(ln)
                    if not m:
                        continue
                    try:
                        o = json.loads(m.group(3))
                        t = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) + float(m.group(2) or 0)
                    except (ValueError, OverflowError):
                        continue
                    r = o.get("request") if isinstance(o.get("request"), dict) else {}
                    if r.get("type") != "side_question" or t < since:
                        continue
                    h = re.match(r"<array\((\d+)\)>", str(r.get("history", "<array(0)>")))
                    reqs.append({"time": m.group(1), "epoch": round(t, 3), "channel": o.get("channelId"),
                                 "request_id": o.get("requestId"), "history": int(h.group(1)) if h else None,
                                 "session_id": None})
    reqs.sort(key=lambda r: r["epoch"])
    return reqs, files


def merge_threads(entries, threads, in_scope, now):
    """새로 읽은 스레드를 모아 둔 것에 더한다. 이미 있는 것은 지우지 않는다(확장은 최근 20개만 둔다)"""
    by_sid = {}
    for e in entries:
        by_sid.setdefault(e["session_id"], []).append(e)
    added = 0
    for sid, th in threads.items():
        if sid not in in_scope:
            continue
        old = by_sid.setdefault(sid, [])
        upd = th.get("updatedAt")
        ents = [x for x in th["entries"] if isinstance(x, dict)]
        used, hits = set(), []
        for x in ents:
            q, r = str(x.get("question") or ""), str(x.get("response") or "")
            h = next((o for o in old if id(o) not in used and o["question"] == q and o["response"] == r), None)
            if h is not None:
                used.add(id(h))
            hits.append(h)
        # 위치: 이미 있는 항목에 맞춘다(앞쪽이 잘려 나갔어도 번호가 밀리지 않게)
        offset = next((h["pos"] - i for i, h in enumerate(hits) if h is not None), None)
        if offset is None:
            offset = max((o["pos"] for o in old), default=-1) + 1
        for i, (x, h) in enumerate(zip(ents, hits)):
            if h is not None:
                h["thread_updated_at"] = upd
                continue
            q, r, pos = str(x.get("question") or ""), str(x.get("response") or ""), offset + i
            part = next((o for o in old if o["pos"] == pos and o["question"] == q and id(o) not in used), None)
            if part is not None:   # 지난번엔 답을 쓰는 중이었다
                part.update({"kind": x.get("kind"), "response": r, "thread_updated_at": upd})
                continue
            old.append({"session_id": sid, "pos": pos, "kind": x.get("kind"), "question": q, "response": r,
                        "first_seen": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), "first_seen_epoch": round(now, 3),
                        "thread_updated_at": upd, "request_time": None, "request_epoch": None, "channel": None})
            added += 1
    out = [e for sid, es in by_sid.items() if sid in in_scope for e in es]
    out.sort(key=lambda e: (e["session_id"], e["pos"]))
    return out, added


def match_requests(entries, reqs):
    """확장 기록의 요청을 곁 질문과 짝짓는다.
    기록에는 세션 번호가 없어서, 창(channel)마다 마지막 요청 시각과 스레드의 updatedAt, 이전 질문 수(history)로 고른다"""
    by_sid = {}
    for e in entries:
        by_sid.setdefault(e["session_id"], []).append(e)
    chans = {}
    for r in reqs:
        chans.setdefault(r["channel"], []).append(r)
    for rs in chans.values():
        last = rs[-1]["epoch"]
        maxh = max((r["history"] for r in rs if r["history"] is not None), default=None)
        best = None
        for sid, es in by_sid.items():
            u = max((e.get("thread_updated_at") or 0) for e in es) / 1000
            if u and u < last - 5:      # 스레드가 이 창의 마지막 요청보다 먼저 끝났다 → 다른 창
                continue
            score = (0 if maxh is not None and maxh == max(e["pos"] for e in es) else 1, abs(u - last) if u else 1e12)
            if best is None or score < best[0]:
                best = (score, sid)
        for r in rs:
            r["session_id"] = best[1] if best else None
    for sid, es in by_sid.items():
        mine = [r for r in reqs if r["session_id"] == sid]
        by_h = {r["history"]: r for r in mine if r["history"] is not None}
        used, rest = set(), []
        for e in es:
            r = by_h.get(e["pos"])
            if r is not None and id(r) not in used:
                used.add(id(r))
                e.update({"request_time": r["time"], "request_epoch": r["epoch"], "channel": r["channel"]})
            elif not e.get("request_epoch"):
                rest.append(e)
        left = [r for r in mine if id(r) not in used and not any(e.get("request_epoch") == r["epoch"] for e in es)]
        # 남은 것은 끝에서부터 순서대로 맞춘다
        for e, r in zip(reversed(rest), reversed(left)):
            e.update({"request_time": r["time"], "request_epoch": r["epoch"], "channel": r["channel"]})


def collect_side_questions(since, in_scope):
    now = time.time()
    try:
        store = json.loads(SQ_PATH.read_text(encoding="utf-8"))
        entries = [e for e in store.get("entries", []) if isinstance(e, dict) and e.get("session_id")]
    except (OSError, ValueError, AttributeError):
        entries = []
        if SQ_PATH.is_file():   # 깨진 파일은 지우지 않고 옆에 남긴다
            shutil.copy2(SQ_PATH, SQ_PATH.with_name(f"side_questions_broken_{time.strftime('%H%M%S')}.json"))
    db, problem = find_state_db()
    added = 0
    if db is not None:
        try:
            threads, problem = read_threads(db)
            entries, added = merge_threads(entries, threads, in_scope, now)
        except Exception as e:  # noqa: BLE001
            problem = f"저장소를 읽지 못했다({type(e).__name__}: {e})"
    if problem:   # 읽지 못해도 모아 둔 것은 범위 안이면 둔다
        entries = [e for e in entries if e["session_id"] in in_scope]
    reqs, log_files = scan_ext_log(since)
    match_requests(entries, reqs)
    missing = max(0, len(reqs) - len(entries))
    doc = {"made_by": "scripts/collect_logs.py",
           "note": "곁 질문(/btw)은 대화 기록(.jsonl)에 남지 않아 VS Code 저장소에서 따로 모은 것. 한 번 모은 것은 지우지 않는다",
           "updated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), "since_epoch": since,
           "source": str(db) if db else None, "source_problem": problem or None, "ext_logs": log_files,
           "counts": {"collected": len(entries), "log_requests": len(reqs), "missing": missing, "added_now": added},
           "log_requests": reqs, "entries": entries}
    SQ_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SQ_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, SQ_PATH)

    lines = ["", "## 곁 질문 (/btw, VS Code 의 옆 대화 패널)", ""]
    if problem:
        lines.append(f"- 곁 질문 저장소를 읽지 못했다: {problem}")
    if not entries and not reqs:
        lines.append("- 곁 질문 0건")
        return lines, doc
    per = {}
    for e in entries:
        per[e["session_id"]] = per.get(e["session_id"], 0) + 1
    lines.append(f"- 모은 곁 질문 {len(entries)}건 (`logs/raw/side_questions.json`, 대화 기록(.jsonl)에는 남지 않는다)"
                 + (": " + ", ".join(f"세션 {s[:8]} {n}건" for s, n in per.items()) if per else ""))
    lines.append(f"- 확장 기록에 보이는 곁 질문 요청 {len(reqs)}건"
                 + (": " + ", ".join(r["time"][5:] for r in reqs) if reqs else ""))
    n_time = sum(1 for e in entries if e.get("request_epoch"))
    if entries:
        lines.append(f"- 요청 시각을 찾은 것 {n_time}건, 못 찾은 것 {len(entries) - n_time}건(처음 모은 시각으로 적는다)")
    if missing:
        lines.append(f"- **경고: 확장 기록에는 곁 질문 요청이 {len(reqs)}번 있는데 {len(entries)}건만 모였다. "
                     f"{missing}건은 기록에 없다.** 옆 대화 패널의 글을 손으로 복사해 `logs/side_questions_manual.txt` 에 "
                     "붙여 넣고 `scripts/pack.sh` 를 다시 돌린다")
    return lines, doc


def side_question_section(since, in_scope):
    """곁 질문 부분. 어떤 오류도 MANIFEST 의 한 줄로만 남긴다(훅은 20초 안에 끝나야 한다)"""
    try:
        return collect_side_questions(since, in_scope)
    except Exception as e:  # noqa: BLE001
        return ["", "## 곁 질문 (/btw, VS Code 의 옆 대화 패널)", "",
                f"- 곁 질문을 모으다 멈췄다(모아 둔 것은 그대로다): {type(e).__name__}: {e}"], None


LOCK_PATH = ROOT / "logs" / ".collect.lock"
LOCK_WAIT = 20


def main():
    """수집 전체를 파일 잠금으로 감싼다. 창마다 훅이 동시에 돌아도 서로 지우지 않게 한다"""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "a") as fh:
        # 훅의 제한 시간이 20초라 --quiet(훅)일 때는 조금 덜 기다린다
        deadline = time.time() + (LOCK_WAIT - 5 if quiet else LOCK_WAIT)
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= deadline:
                    if quiet:
                        return 0      # 다른 수집이 돌고 있다. 그것이 모은다
                    print(f"다른 수집이 돌고 있어 {LOCK_WAIT}초를 기다렸지만 끝나지 않았습니다. 잠시 뒤 다시 돌리세요: scripts/collect_logs.sh")
                    return 3
                time.sleep(0.2)
        try:
            collect()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return 0


def collect():
    dest = ROOT / "logs" / "raw"
    since, by_clock = since_epoch()
    moved = move_stray_exports()

    proj = HOME / ".claude" / "projects" / str(SRC_ROOT).replace("/", "-")
    all_claude = sorted(proj.rglob("*.jsonl")) if proj.is_dir() else []
    claude_files = [p for p in all_claude if p.stat().st_mtime >= since]
    codex_root = HOME / ".codex"
    codex_files = sorted(p for p in codex_root.rglob("*.jsonl") if p.stat().st_mtime >= since) if codex_root.is_dir() else []

    rows = []
    for kind, files in (("claude", claude_files), ("codex", codex_files)):
        # 임시 폴더에 모두 복사한 뒤 바꿔 끼운다. 도중에 멈춰도 옛 폴더가 남는다
        kdir = dest / kind
        tdir = dest / f".{kind}.tmp"
        odir = dest / f".{kind}.old"
        shutil.rmtree(tdir, ignore_errors=True)
        tdir.mkdir(parents=True, exist_ok=True)
        for f in files:
            target = tdir / f.name
            try:
                shutil.copy2(f, target)
            except OSError:
                continue
            first, last, models, n = summarize(target)
            sha = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
            rows.append((kind, f"logs/raw/{kind}/{f.name}", target.stat().st_size, n, first, last, ", ".join(models) or "-", sha))
        shutil.rmtree(odir, ignore_errors=True)
        if kdir.exists():
            kdir.rename(odir)
        tdir.rename(kdir)
        shutil.rmtree(odir, ignore_errors=True)

    since_text = time.strftime("%Y-%m-%d %H:%M", time.localtime(since))
    basis = "타이머를 켠 시각 10분 전" if by_clock else f"최근 {hours:g}시간(타이머가 꺼져 있다)"
    lines = ["# 원본 기록 목록", "",
             f"- 만든 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 범위: {since_text} 뒤에 바뀐 기록만 ({basis})",
             f"- Claude Code: `{proj}` 아래의 세션 {len(claude_files)}개 (범위 밖이라 뺀 옛 세션 {len(all_claude) - len(claude_files)}개)",
             f"- Codex: `~/.codex` 아래의 기록 {len(codex_files)}개",
             "- 시각은 기록 파일에 적힌 UTC 시각이다(한국 시각 = +9시간).", "",
             "| 도구 | 파일 | 크기(바이트) | 줄 수 | 처음 | 마지막 | 모델 | sha256 앞 16자리 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")

    exports = sorted((ROOT / "logs").glob("claude_session*.txt"))
    fresh = [p for p in exports if p.stat().st_mtime >= since]
    stale = [p for p in exports if p.stat().st_mtime < since]
    lines += ["", "## 읽기 쉬운 대화 기록 (/export 로 내보낸 것)"]
    if fresh:
        for p in fresh:
            lines.append(f"- `logs/{p.name}`: {p.stat().st_size} 바이트, {time.strftime('%m-%d %H:%M', time.localtime(p.stat().st_mtime))}")
    else:
        lines.append("- 없음 (없어도 된다. 읽기 쉬운 대화 기록은 `scripts/pack.sh` 가 원본 기록에서 만든다)")
    for p in stale:
        lines.append(f"- 주의: `logs/{p.name}` 은 범위 전의 것이다({time.strftime('%m-%d %H:%M', time.localtime(p.stat().st_mtime))}). 지난 연습의 기록이면 제출 묶음에서 빠진다")
    if moved:
        lines.append("- 폴더 맨 위에 있던 것을 logs/ 로 옮겼다: " + ", ".join(moved))
    in_scope = {p.stem for p in claude_files if p.parent == proj}
    sq_lines, sq = side_question_section(since, in_scope)
    lines += sq_lines
    (ROOT / "logs" / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not quiet:
        n_c = sum(1 for r in rows if r[0] == "claude")
        n_x = len(rows) - n_c
        print(f"Claude Code 기록 {n_c}개, Codex 기록 {n_x}개를 logs/raw/ 에 복사했습니다. 목록: logs/MANIFEST.md")
        if moved:
            print("폴더 맨 위의 대화 기록을 logs/ 로 옮겼습니다: " + ", ".join(moved))
        if n_c == 0:
            print("주의: Claude Code 기록을 찾지 못했습니다. /export 로 직접 내보내야 합니다.")
        if sq:
            c = sq["counts"]
            print(f"곁 질문(/btw) {c['collected']}건 (확장 기록의 요청 {c['log_requests']}건): logs/raw/side_questions.json")
            if c["missing"]:
                print(f"주의: 곁 질문 {c['missing']}건이 기록에 없습니다. 옆 대화 패널의 글을 logs/side_questions_manual.txt 에 붙여 넣으세요.")
        else:
            print("주의: " + sq_lines[-1].lstrip("- "))
        print("마지막 응답은 이 수집 뒤에 기록될 수 있습니다. 제출 직전에 한 번 더 돌리세요: scripts/pack.sh")


if __name__ == "__main__":
    sys.exit(main())
