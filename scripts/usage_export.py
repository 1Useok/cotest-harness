#!/usr/bin/env python3
"""AI 사용 내역(대화 기록)을 제출용 여러 형식으로 바꾼다.

읽는 것: logs/raw/claude/*.jsonl (Claude Code), logs/raw/codex/*.jsonl (Codex CLI),
         logs/codex_<방식>_<pN>_<시각>.log (Codex 호출 기록, 이름표 붙이기용), logs/EXAM.json,
         logs/raw/side_questions.json (곁 질문 /btw. 부모 창마다 가짜 세션 하나로 넣어 다른 기록과 똑같이 그린다)
쓰는 것: submit/ai_usage/ (--out 으로 바꿈). 다른 프로그램은 돌리지 않는다. 네트워크도 쓰지 않는다.

사용:
  scripts/usage_export.sh                       모든 형식을 만든다
  scripts/usage_export.sh --formats md,csv      일부 형식만 (md,txt,html,docx,csv,json)
  scripts/usage_export.sh --check               파일을 쓰지 않고 개수와 경고만 보인다
  scripts/usage_export.sh --zip light           만든 파일만 zip 으로
  scripts/usage_export.sh --zip full --max-mb 20  만든 파일 + 원본 기록 + Codex 호출 기록. 크면 나눈다
  --out DIR  --since EPOCH  --tool-limit N(기본 2000)  --full(줄이지 않음)
"""
import argparse
import csv
import html
import io
import json
import re
import sys
import time
import zipfile
import zlib
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
SCRIPT_NAME = "scripts/usage_export.py"
ALL_FORMATS = ["md", "txt", "html", "docx", "csv", "json"]

# Claude Code 기록에서 읽지 않고 넘기는 줄 종류(알려진 것)
CLAUDE_SKIP_TYPES = {
    "api-request", "api-request-blob", "api-request-shape", "session-owner", "atis-latch", "last-prompt",
    "ai-title", "file-history-snapshot", "file-history-delta", "tools-used", "summary", "custom-title",
    "progress", "tag", "agent-name", "pr-link",
}
MODE_KO = {"ambig": "모호점 찾기(ambig)", "alt": "독립 구현(alt)", "review": "코드 리뷰(review)",
           "cases": "정답 사례 교차 확인(cases)"}
CMD_KO = {"intake": "접수(intake)", "finish": "마무리(finish)", "solve": "풀이", "probe": "확인(probe)",
          "explain": "설명서(explain)", "ask": "질문 창(ask)"}


# ---------- 공통 도구 ----------

def parse_ts(s):
    """ISO 시각 또는 epoch 를 UTC datetime 으로. 실패하면 None"""
    if s is None or s == "":
        return None
    try:
        if isinstance(s, (int, float)):
            return datetime.fromtimestamp(float(s), timezone.utc)
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def kst(s, fmt="%Y-%m-%d %H:%M:%S"):
    d = parse_ts(s)
    return d.astimezone(KST).strftime(fmt) if d else "-"


def iso(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def epoch(s):
    d = parse_ts(s)
    return d.timestamp() if d else None


def clip(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


def one_line(s, n):
    return clip(re.sub(r"\s+", " ", s or ""), n)


def shorten(s, limit):
    """도구 출력 등을 limit 글자로 줄이고 (본문, 줄인 글자 수)"""
    s = s or ""
    if limit is None or len(s) <= limit:
        return s, 0
    return s[:limit], len(s) - limit


def cut_note(n, src):
    return f"(… {n}자 줄임. 전체는 raw 기록에 있음: {src})"


def flatten_text(v):
    """여러 모양의 content 를 글자로"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict):
                t = x.get("type", "")
                if "text" in x and isinstance(x["text"], str):
                    out.append(x["text"])
                elif t == "image" or t == "input_image":
                    out.append("[이미지]")
                elif "content" in x:
                    out.append(flatten_text(x["content"]))
                else:
                    out.append(json.dumps(x, ensure_ascii=False))
            else:
                out.append(str(x))
        return "\n".join(out)
    if isinstance(v, dict):
        if isinstance(v.get("text"), str):
            return v["text"]
        if "output" in v:
            return flatten_text(v["output"])
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def read_jsonl(path, stats, kind):
    """(줄 번호, 객체) 를 돌려준다. 깨진 줄은 세고 넘긴다"""
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        stats["warnings"].append(f"{path.name} 을 읽지 못함: {e}")
        return
    lines = data.split("\n")
    last_nonempty = max((i for i, ln in enumerate(lines) if ln.strip()), default=-1)
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            stats["bad_lines"][kind] += 1
            if i == last_nonempty:
                stats["warnings"].append(f"{path.name}: 마지막 줄이 잘려 있어 건너뜀(기록 중이었을 수 있음)")
            else:
                stats["warnings"].append(f"{path.name}: {i + 1}번째 줄이 JSON 이 아니어서 건너뜀")
            continue
        if isinstance(o, dict):
            yield i + 1, o
        else:
            stats["unknown"][f"{kind}:(객체 아님)"] += 1


def new_item(kind, ts, src, **kw):
    it = {"kind": kind, "ts": ts, "ts_kst": kst(ts), "src": src}
    it.update(kw)
    return it


# ---------- Claude Code 읽기 ----------

TAG_STRIP = re.compile(r"<(ide_opened_file|ide_selection|system-reminder|ide_diagnostics)>.*?</\1>", re.S)


def claude_human_text(text):
    """사람 입력 글에서 슬래시 명령을 '/cmd args' 로 바꾸고 IDE 가 붙인 꼬리표를 뗀다. (글, 뗀 것)"""
    m = re.search(r"<command-name>\s*(/?[^<\s]+)\s*</command-name>", text)
    if m:
        name = m.group(1) if m.group(1).startswith("/") else "/" + m.group(1)
        a = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
        args = a.group(1).strip() if a else ""
        return (name + (" " + args if args else "")).strip(), ""
    stripped = "\n".join(x.group(0) for x in TAG_STRIP.finditer(text))
    return TAG_STRIP.sub("", text).strip(), stripped


def compact_input(name, inp):
    """도구 호출 입력을 사람이 읽을 글로"""
    if not isinstance(inp, dict):
        return flatten_text(inp)
    if isinstance(inp.get("command"), str):
        s = "$ " + inp["command"]
        if inp.get("description"):
            s = f"# {inp['description']}\n" + s
        return s
    parts = []
    for k, v in inp.items():
        if isinstance(v, str):
            parts.append(f"{k}: {v}" if "\n" not in v else f"{k}:\n{v}")
        else:
            parts.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    return "\n".join(parts)


def parse_claude(path, since, stats):
    rel = f"logs/raw/claude/{path.name}"
    s = {"tool": "claude", "tool_ko": "Claude Code", "id": path.stem, "file": rel, "items": [],
         "models": [], "ai_responses": 0, "cut_before_since": 0, "sidechain_file": path.name.startswith("agent-"),
         "parent_session": None}
    models = OrderedDict()
    msg_ids = set()
    pending_human_q = []
    for ln, o in read_jsonl(path, stats, "claude"):
        t = o.get("type")
        src = f"{rel}:{ln}"
        ts = o.get("timestamp")
        if ts and since is not None and (epoch(ts) or 0) < since:
            s["cut_before_since"] += 1
            continue
        if o.get("sessionId") and s["parent_session"] is None and s["sidechain_file"]:
            s["parent_session"] = o.get("sessionId")
        side = bool(o.get("isSidechain"))
        msg = o.get("message")
        if isinstance(msg, str):
            try:
                msg = json.loads(msg)
            except ValueError:
                msg = {"content": msg}
        if t in CLAUDE_SKIP_TYPES:
            stats["skipped"][f"claude:{t}"] += 1
            continue
        if t == "assistant" and isinstance(msg, dict):
            model = msg.get("model")
            if model and model != "<synthetic>":
                models[model] = 1
            if msg.get("id"):
                msg_ids.add(msg["id"])
            content = msg.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for b in content or []:
                bt = b.get("type") if isinstance(b, dict) else None
                if bt == "text" and (b.get("text") or "").strip():
                    s["items"].append(new_item("assistant", ts, src, text=b["text"], model=model, sidechain=side))
                elif bt == "thinking":
                    if (b.get("thinking") or "").strip():
                        s["items"].append(new_item("thinking", ts, src, text=b["thinking"], model=model, sidechain=side))
                    else:
                        stats["skipped"]["claude:thinking(내용 없음)"] += 1
                elif bt == "redacted_thinking":
                    stats["skipped"]["claude:thinking(가려짐)"] += 1
                elif bt in ("tool_use", "server_tool_use"):
                    s["items"].append(new_item("tool_call", ts, src, name=b.get("name", "?"), tool_id=b.get("id"),
                                               input=b.get("input"), text=compact_input(b.get("name"), b.get("input")),
                                               model=model, sidechain=side))
                elif bt:
                    stats["unknown"][f"claude:assistant/{bt}"] += 1
            continue
        if t == "user" and isinstance(msg, dict):
            content = msg.get("content")
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
            has_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks)
            texts = []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result":
                    s["items"].append(new_item("tool_result", ts, src, tool_id=b.get("tool_use_id"),
                                               text=flatten_text(b.get("content")), is_error=bool(b.get("is_error")),
                                               sidechain=side))
                elif b.get("type") == "text":
                    texts.append(b.get("text") or "")
                elif b.get("type") == "image":
                    texts.append("[이미지]")
                else:
                    stats["unknown"][f"claude:user/{b.get('type')}"] += 1
            text = "\n".join(texts).strip()
            if not text:
                continue
            origin = o.get("origin") if isinstance(o.get("origin"), dict) else {}
            if has_result:
                s["items"].append(new_item("system", ts, src, sub="도구 결과에 붙은 글", text=text, sidechain=side))
            elif o.get("isMeta"):
                sub = "스킬 지시문 펼침" if "Base directory for this skill" in text else "자동으로 붙은 글(meta)"
                s["items"].append(new_item("system", ts, src, sub=sub, text=text, sidechain=side))
            elif o.get("isCompactSummary"):
                s["items"].append(new_item("system", ts, src, sub="대화 요약(compact)", text=text, sidechain=side))
            elif origin and origin.get("kind") != "human":
                sub = "백그라운드 작업 알림" if "task-notification" in str(origin.get("kind")) else f"자동 입력({origin.get('kind')})"
                s["items"].append(new_item("system", ts, src, sub=sub, text=text, sidechain=side))
            elif not origin and re.match(r"\s*(<task-notification>|<local-command-std|<system-reminder>|Caveat:|\[Request interrupted|<bash-std)", text):
                sub = "사람이 중단함" if "[Request interrupted" in text else ("명령 출력" if "local-command" in text or "bash-std" in text else "자동으로 붙은 글")
                s["items"].append(new_item("system", ts, src, sub=sub, text=text, sidechain=side))
            elif side:
                # 하위 에이전트에게 준 지시는 사람이 친 것이 아니다
                s["items"].append(new_item("instruction", ts, src, text=text, sidechain=True, by="AI"))
            else:
                ht, stripped = claude_human_text(text)
                if stripped:
                    s["items"].append(new_item("system", ts, src, sub="IDE 가 붙인 정보", text=stripped))
                if ht:
                    s["items"].append(new_item("human", ts, src, text=ht, raw_text=text, how="입력"))
            continue
        if t == "queue-operation":
            c = o.get("content")
            if o.get("operation") == "remove" and isinstance(c, str) and c.strip() and not c.lstrip().startswith("<"):
                if o.get("reason") == "absorbed_mid_turn":
                    s["items"].append(new_item("human", ts, src, text=c.strip(), raw_text=c, how="작업 중에 입력"))
                    continue
                stats["notes"].append(f"{path.name}: 대기열에서 빠진 사람 입력(전달 안 됨으로 보임, 이유 {o.get('reason')}): {one_line(c, 60)}")
            stats["skipped"]["claude:queue-operation"] += 1
            continue
        if t == "attachment":
            a = o.get("attachment") if isinstance(o.get("attachment"), dict) else {}
            if a.get("type") == "queued_command" and isinstance(a.get("prompt"), str) and not a["prompt"].lstrip().startswith("<"):
                pending_human_q.append(new_item("human", ts, src, text=a["prompt"].strip(), raw_text=a["prompt"], how="작업 중에 입력"))
                s["items"].append(pending_human_q[-1])
                continue
            stats["skipped"][f"claude:attachment/{a.get('type')}"] += 1
            continue
        if t == "system":
            c = o.get("content") if isinstance(o.get("content"), str) else ""
            if o.get("subtype") == "local_command" and "<command-name>" in c:
                ht, _ = claude_human_text(c)
                s["items"].append(new_item("human", ts, src, text=ht, raw_text=c, how="명령"))
            elif o.get("subtype") == "local_command" and c:
                s["items"].append(new_item("system", ts, src, sub="명령 출력", text=c))
            elif o.get("subtype") == "compact_boundary":
                s["items"].append(new_item("system", ts, src, sub="대화 압축(compact) 경계", text=c or "(내용 없음)"))
            else:
                stats["skipped"][f"claude:system/{o.get('subtype')}"] += 1
            continue
        stats["unknown"][f"claude:{t}"] += 1
    # 같은 사람 입력이 두 번 잡힌 것(대기열 + 실제 입력)을 하나로
    dedup, seen = [], []
    for it in s["items"]:
        if it["kind"] == "human":
            e = epoch(it["ts"]) or 0
            if any(t2 == it["text"] and abs(e - e2) < 180 for t2, e2 in seen):
                continue
            seen.append((it["text"], e))
        dedup.append(it)
    s["items"] = dedup
    s["models"] = list(models)
    s["ai_responses"] = len(msg_ids)
    return s


# ---------- Codex 읽기 ----------

def parse_codex(path, since, stats):
    rel = f"logs/raw/codex/{path.name}"
    s = {"tool": "codex", "tool_ko": "Codex CLI", "id": path.stem, "file": rel, "items": [], "models": [],
         "ai_responses": 0, "cut_before_since": 0, "codex": {}}
    models = OrderedDict()
    resp_ids = set()
    n_assist = 0
    for ln, o in read_jsonl(path, stats, "codex"):
        t = o.get("type")
        p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
        ts = o.get("timestamp") or p.get("timestamp")
        src = f"{rel}:{ln}"
        if ts and since is not None and (epoch(ts) or 0) < since:
            s["cut_before_since"] += 1
            continue
        if t == "session_meta":
            s["codex"].update({"session_id": p.get("id") or p.get("session_id"), "cwd": p.get("cwd"),
                               "cli_version": p.get("cli_version"), "originator": p.get("originator"),
                               "start": p.get("timestamp") or ts})
            if isinstance(p.get("model"), str):
                models[p["model"]] = 1
            continue
        if t == "turn_context":
            if isinstance(p.get("model"), str):
                models[p["model"]] = 1
            s["codex"]["effort"] = p.get("effort") or s["codex"].get("effort")
            continue
        if t == "world_state":
            cm = (p.get("state") or {}).get("collaboration_mode") if isinstance(p.get("state"), dict) else None
            if isinstance(cm, dict) and isinstance(cm.get("model"), str):
                models[cm["model"]] = 1
            stats["skipped"]["codex:world_state"] += 1
            continue
        if t == "token_usage_record":
            if p.get("response_id"):
                resp_ids.add(p["response_id"])
            stats["skipped"]["codex:token_usage_record"] += 1
            continue
        if t == "event_msg":
            if p.get("type") == "thread_settings_applied":
                m = (p.get("thread_settings") or {}).get("model")
                if isinstance(m, str):
                    models[m] = 1
            stats["skipped"][f"codex:event_msg/{p.get('type')}"] += 1
            continue
        if t != "response_item":
            stats["unknown"][f"codex:{t}"] += 1
            continue
        pt = p.get("type")
        if pt == "message":
            role = p.get("role")
            text = flatten_text(p.get("content")).strip()
            if not text:
                continue
            if role == "assistant":
                n_assist += 1
                s["items"].append(new_item("assistant", ts, src, text=text, phase=p.get("phase")))
            elif role == "developer" or role == "system":
                s["items"].append(new_item("system", ts, src, sub="Codex 기본 지시(developer)", text=text))
            elif role == "user":
                if text.startswith("<environment_context>") or text.startswith("<user_instructions>") or text.startswith("# AGENTS.md"):
                    s["items"].append(new_item("system", ts, src, sub="환경 정보(자동)", text=text))
                else:
                    s["items"].append(new_item("instruction", ts, src, text=text, by="AI"))
            else:
                stats["unknown"][f"codex:message/{role}"] += 1
        elif pt == "reasoning":
            summ = flatten_text(p.get("summary")).strip()
            cont = flatten_text(p.get("content")).strip() if p.get("content") else ""
            if summ or cont:
                s["items"].append(new_item("thinking", ts, src, text=summ or cont))
            else:
                stats["skipped"]["codex:reasoning(암호화, 요약 없음)"] += 1
        elif pt in ("custom_tool_call", "function_call"):
            inp = p.get("input") if pt == "custom_tool_call" else p.get("arguments")
            if isinstance(inp, str) and pt == "function_call":
                try:
                    inp = json.loads(inp)
                except ValueError:
                    pass
            s["items"].append(new_item("tool_call", ts, src, name=p.get("name", "?"), tool_id=p.get("call_id"),
                                       input=inp, text=compact_input(p.get("name"), inp) if isinstance(inp, dict) else flatten_text(inp)))
        elif pt == "local_shell_call":
            act = p.get("action") or {}
            cmd = act.get("command")
            s["items"].append(new_item("tool_call", ts, src, name="shell", tool_id=p.get("call_id"), input=act,
                                       text="$ " + (" ".join(cmd) if isinstance(cmd, list) else str(cmd))))
        elif pt in ("custom_tool_call_output", "function_call_output", "local_shell_call_output"):
            s["items"].append(new_item("tool_result", ts, src, tool_id=p.get("call_id"), text=flatten_text(p.get("output"))))
        elif pt == "web_search_call":
            s["items"].append(new_item("tool_call", ts, src, name="web_search", input=p.get("action"),
                                       text=json.dumps(p.get("action"), ensure_ascii=False)))
        elif pt in ("additional_tools",):
            stats["skipped"][f"codex:response_item/{pt}"] += 1
        else:
            stats["unknown"][f"codex:response_item/{pt}"] += 1
    s["models"] = list(models)
    s["ai_responses"] = len(resp_ids) or n_assist
    return s


# ---------- 이름표, 주고받기 나누기 ----------

def problem_of(text):
    m = re.search(r"\b(p\d+)\b", text or "")
    return m.group(1) if m else None


def label_claude(s):
    humans = [it for it in s["items"] if it["kind"] == "human"]
    if s.get("sidechain_file"):
        return "하위 에이전트(subagent)", "subagent", None
    cmds = []
    for it in humans:
        m = re.match(r"/([\w:-]+)\s*(.*)", it["text"])
        if m:
            cmds.append((m.group(1).split(":")[-1], m.group(2).strip()))
    probs = sorted({problem_of(a) for _, a in cmds if problem_of(a)})
    if cmds:
        labels, slugs = [], []
        for c, a in cmds:
            pid = problem_of(a)
            if c == "export":
                continue
            if c in ("solve", "probe", "explain") and pid:
                lab = f"문제 {pid} {CMD_KO[c]}"
                slug = f"{pid}_{c}"
            else:
                lab = CMD_KO.get(c, "/" + c)
                slug = c
            if lab not in labels:
                labels.append(lab)
                slugs.append(slug)
        if labels:
            return " + ".join(labels), "_".join(slugs), (probs[0] if len(probs) == 1 else None)
    if humans:
        pid = problem_of(humans[0]["text"])
        return "대화: " + one_line(humans[0]["text"], 24), (pid or "chat"), pid
    return "사람 입력 없는 세션", "noinput", None


CODEX_LOG_RE = re.compile(r"codex_(\w+?)_(p\d+)_(\d{4})_(\d{6})\.log$")


def match_codex_logs(sessions, stats):
    """Codex 세션을 logs/codex_<방식>_<pN>_<시각>.log 와 짝짓는다(세션 번호, 없으면 시각+프롬프트)"""
    logs = []
    for p in sorted((ROOT / "logs").glob("codex_*.log")):
        m = CODEX_LOG_RE.search(p.name)
        if not m:
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sid = re.search(r"session id:\s*([0-9a-f-]{20,})", txt)
        prompt = ""
        pm = re.search(r"# ---- 프롬프트 ----\n(.*?)\n# ---- 출력 ----", txt, re.S)
        if pm:
            prompt = pm.group(1).strip()
        logs.append({"path": p, "name": p.name, "mode": m.group(1), "pid": m.group(2), "stamp": m.group(3) + m.group(4),
                     "sid": sid.group(1) if sid else None, "prompt": prompt, "used": False})
    cx = [s for s in sessions if s["tool"] == "codex"]
    for s in cx:
        sid = s["codex"].get("session_id")
        hit = next((lg for lg in logs if sid and lg["sid"] == sid), None)
        if not hit:
            st = parse_ts(s["codex"].get("start") or s["start"])
            instr = next((it["text"] for it in s["items"] if it["kind"] == "instruction"), "")
            best = None
            for lg in logs:
                if lg["used"] or not st:
                    continue
                try:
                    lt = datetime.strptime(f"{st.astimezone(KST).year}{lg['stamp']}", "%Y%m%d%H%M%S").replace(tzinfo=KST)
                except ValueError:
                    continue
                gap = abs((lt - st).total_seconds())
                same = bool(lg["prompt"]) and lg["prompt"][:200] == instr.strip()[:200]
                if gap <= 180 and (same or not lg["prompt"]):
                    if best is None or gap < best[0]:
                        best = (gap, lg)
            hit = best[1] if best else None
        if hit:
            hit["used"] = True
            s["codex"].update({"log_file": f"logs/{hit['name']}", "mode": hit["mode"], "problem": hit["pid"]})
    for lg in logs:
        if not lg["used"]:
            stats["warnings"].append(f"Codex 호출 기록 logs/{lg['name']} 에 맞는 원본 기록(rollout)이 없음")
    for s in cx:
        if not s["codex"].get("log_file"):
            stats["warnings"].append(f"Codex 원본 기록 {s['file']} 에 맞는 logs/codex_*.log 가 없음(이름표를 프롬프트로 추정)")


def label_codex(s):
    c = s["codex"]
    instr = next((it["text"] for it in s["items"] if it["kind"] == "instruction"), "")
    mode, pid = c.get("mode"), c.get("problem")
    if not mode:
        if "xcheck/" in instr:
            mode = "cases"
        elif "alt.cpp" in instr:
            mode = "alt"
        elif "AMBIG" in instr:
            mode = "ambig"
        elif "리뷰" in instr or "review" in instr.lower():
            mode = "review"
    pid = pid or problem_of(instr)
    mko = MODE_KO.get(mode, mode or "호출")
    lab = f"Codex: {pid + ' ' if pid else ''}{mko}"
    slug = "_".join(x for x in (pid, mode) if x) or "call"
    return lab, slug, pid, mode


def find_callers(sessions):
    """Codex 를 부른 Claude 창(codex_ask 를 돌린 도구 호출)을 찾는다"""
    calls = []
    for s in sessions:
        if s["tool"] != "claude":
            continue
        for it in s["items"]:
            if it["kind"] == "tool_call" and "codex_ask" in (it.get("text") or ""):
                # 문제 자리에 반복문 변수($p)가 오면 어느 문제든 맞는 것으로 본다
                for m in re.finditer(r"codex_ask(?:\.sh)?\s+['\"]?(\w+)['\"]?\s+['\"]?(p\d+|\$\{?\w+\}?)", it["text"]):
                    calls.append((m.group(1), m.group(2), epoch(it["ts"]) or 0, s, it))
    for s in sessions:
        if s["tool"] != "codex":
            continue
        st = epoch(s["start"]) or 0
        cands = [c for c in calls if c[0] == s["codex"].get("mode") and (c[1] == s["problem"] or c[1].startswith("$"))
                 and st - 900 <= c[2] <= st + 5]
        if cands:
            c = max(cands, key=lambda x: x[2])
            s["codex"]["caller"] = c[3]["label"]
            s["codex"]["caller_file"] = c[3]["file"]
            s["codex"]["caller_src"] = c[4]["src"]


def split_turns(s):
    """주고받기 = 사람(또는 AI 가 준 지시) 한 번 + 다음 입력 전까지의 AI 작업"""
    starts = ("human",) if s["tool"] == "claude" else ("instruction",)
    turns, cur = [], None
    for it in s["items"]:
        if it["kind"] in starts and not it.get("sidechain"):
            cur = {"start": it["ts"], "starter": "사람" if it["kind"] == "human" else "AI가 다른 AI에게",
                   "instruction": it["text"], "items": []}
            if turns and not turns[-1]["instruction"] and len(turns) == 1 and not any(
                    x["kind"] in ("assistant", "tool_call") for x in turns[0]["items"]):
                cur["items"] = turns.pop()["items"]  # 앞쪽의 자동 글은 첫 주고받기에 붙인다
            turns.append(cur)
        elif cur is None:
            cur = {"start": it["ts"], "starter": "시작 전(자동)", "instruction": "", "items": []}
            turns.append(cur)
        cur["items"].append(it)
    for i, t in enumerate(turns, 1):
        t["index"] = i
        t["start_kst"] = kst(t["start"])
        last = [x["text"] for x in t["items"] if x["kind"] == "assistant"]
        t["result"] = last[-1] if last else ""
        t["n_tool_calls"] = sum(1 for x in t["items"] if x["kind"] == "tool_call")
    return turns


SIDE_HOW = "곁 질문(/btw)"


def side_question_sessions(raw_dir, since, sessions, stats):
    """logs/raw/side_questions.json 의 곁 질문을 부모 창마다 가짜 세션 하나로 만든다(나머지 그리기는 그대로 쓴다)"""
    p = raw_dir / "side_questions.json"
    if not p.is_file():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        entries = [e for e in doc.get("entries", []) if isinstance(e, dict) and e.get("session_id")]
    except (OSError, ValueError, AttributeError) as e:
        stats["warnings"].append(f"{p.name} 을 읽지 못함: {e}")
        return []
    c = doc.get("counts") or {}
    if c.get("missing"):
        stats["warnings"].append(f"확장 기록에는 곁 질문 요청이 {c.get('log_requests')}번 있는데 {c.get('collected')}건만 모였다. "
                                 "빠진 것은 logs/side_questions_manual.txt 에 손으로 옮긴다")
    by_id = {s["id"]: s for s in sessions}
    groups = OrderedDict()
    for e in sorted(entries, key=lambda e: (e["session_id"], e.get("pos", 0))):
        groups.setdefault(e["session_id"], []).append(e)
    out = []
    for sid, es in groups.items():
        par = by_id.get(sid)
        s = {"tool": "claude", "tool_ko": "Claude Code", "id": f"btw-{sid}", "file": "logs/raw/side_questions.json",
             "items": [], "models": list(par["models"]) if par else [], "ai_responses": 0, "cut_before_since": 0,
             "sidechain_file": False, "parent_session": sid, "side_question": True}
        for e in es:
            ep = e.get("request_epoch")
            how = SIDE_HOW
            if not ep:
                ep = e.get("first_seen_epoch")
                how = SIDE_HOW + ", 시각은 어림(처음 모은 시각)"
            if not ep:
                continue
            if since is not None and ep < since:
                s["cut_before_since"] += 1
                continue
            ts = iso(datetime.fromtimestamp(ep, timezone.utc))
            src = f"logs/raw/side_questions.json#{sid}/{e.get('pos')}"
            q = (e.get("question") or "").strip() or "(질문 글 없음)"
            s["items"].append(new_item("human", ts, src, text=q, raw_text=q, how=how))
            r = (e.get("response") or "").strip()
            if e.get("kind") not in (None, "answer"):
                r = f"(종류: {e.get('kind')})\n{r}".strip()
            if r:
                s["items"].append(new_item("assistant", ts, src, text=r, model=(s["models"] or [None])[0], sidechain=False))
                s["ai_responses"] += 1
        if not s["items"]:
            continue
        ts = [it["ts"] for it in s["items"]]
        s["start"] = min(ts, key=lambda x: epoch(x) or 0)
        s["end"] = max(ts, key=lambda x: epoch(x) or 0)
        if par:
            s["label"], s["slug"], s["problem"] = f"곁 질문(/btw) · {par['label']}", f"btw_{par['slug']}", par["problem"]
        else:
            s["label"], s["slug"], s["problem"] = f"곁 질문(/btw) · 세션 {sid[:8]}", f"btw_{sid[:8]}", None
            stats["warnings"].append(f"곁 질문의 부모 창(세션 {sid})이 원본 기록에 없음. 모델과 문제를 모른다")
        s["mode"] = None
        s["note"] = ("곁 질문(/btw): 옆 대화 패널에서 물은 것. 대화 기록(.jsonl)에 남지 않아 VS Code 저장소에서 따로 모았다. "
                     f"답한 모델은 부모 창({par['label'] if par else '모름'})의 모델이다")
        out.append(s)
    return out


def build_model(raw_dir, since, stats):
    sessions = []
    for p in sorted((raw_dir / "claude").glob("*.jsonl")) if (raw_dir / "claude").is_dir() else []:
        sessions.append(parse_claude(p, since, stats))
    for p in sorted((raw_dir / "codex").glob("*.jsonl")) if (raw_dir / "codex").is_dir() else []:
        sessions.append(parse_codex(p, since, stats))
    kept = []
    for s in sessions:
        ts = [it["ts"] for it in s["items"] if it.get("ts")]
        if not s["items"]:
            stats["notes"].append(f"{s['file']}: 범위 안의 내용이 없어 뺐다(범위 전 {s['cut_before_since']}줄)")
            continue
        s["start"] = min(ts, key=lambda x: epoch(x) or 0) if ts else None
        s["end"] = max(ts, key=lambda x: epoch(x) or 0) if ts else None
        if s["cut_before_since"]:
            stats["notes"].append(f"{s['file']}: 범위 전의 줄 {s['cut_before_since']}개를 뺐다")
        kept.append(s)
    sessions = kept
    match_codex_logs(sessions, stats)
    for s in sessions:
        if s["tool"] == "claude":
            s["label"], s["slug"], s["problem"] = label_claude(s)
            s["mode"] = None
        else:
            s["label"], s["slug"], s["problem"], s["mode"] = label_codex(s)
    # 하위 에이전트 파일은 부모 세션의 문제를 따른다
    by_id = {s["id"]: s for s in sessions}
    for s in sessions:
        if s.get("sidechain_file") and s.get("parent_session") in by_id:
            par = by_id[s["parent_session"]]
            s["problem"] = par["problem"]
            s["label"] = f"하위 에이전트({par['label']})"
    sessions += side_question_sessions(raw_dir, since, sessions, stats)
    for s in sessions:
        s["problem"] = s["problem"] or "공통"
    sessions.sort(key=lambda s: epoch(s["start"]) or 0)
    # 같은 이름표가 여럿이면 두 번째부터 '(2번째)' 를 붙인다
    seen = Counter()
    for s in sessions:
        orig = s["label"]
        seen[orig] += 1
        if seen[orig] > 1:
            s["label"] = f"{orig} ({seen[orig]}번째)"
            s["slug"] += f"_{seen[orig]}"
    find_callers(sessions)
    for i, s in enumerate(sessions, 1):
        s["no"] = i
        s["start_kst"], s["end_kst"] = kst(s["start"]), kst(s["end"])
        s["turns"] = split_turns(s)
        if s.get("side_question"):
            for t in s["turns"]:
                t["starter"] = "사람(곁 질문 /btw)"
        s["out_name"] = f"{i:02d}_{s['tool']}_{s['slug']}"
        k = Counter(it["kind"] for it in s["items"])
        s["counts"] = {"human": k["human"], "instruction": k["instruction"], "assistant": k["assistant"],
                       "thinking": k["thinking"], "tool_call": k["tool_call"], "tool_result": k["tool_result"],
                       "system": k["system"], "ai_responses": s["ai_responses"]}
        if s["tool"] == "claude" and not s.get("sidechain_file") and k["human"] == 0:
            stats["warnings"].append(f"{s['file']} ({s['label']}): 사람 입력이 하나도 없음")
        if not s["models"]:
            stats["warnings"].append(f"{s['file']} ({s['label']}): 모델 이름을 찾지 못함")
        del s["items"]  # 항목은 turns 안에 있다
    return sessions


# ---------- 요약 표 ----------

def all_items(s):
    for t in s["turns"]:
        for it in t["items"]:
            yield t, it


def tools_models_rows(sessions):
    g = OrderedDict()
    for s in sessions:
        for m in (s["models"] or ["(모름)"]):
            key = (s["tool_ko"], m)
            r = g.setdefault(key, {"sessions": 0, "human": 0, "ai": 0, "tools": 0, "first": None, "last": None})
            r["sessions"] += 1
            r["human"] += s["counts"]["human"]
            r["ai"] += s["counts"]["ai_responses"]
            r["tools"] += s["counts"]["tool_call"]
            if not r["first"] or (epoch(s["start"]) or 0) < (epoch(r["first"]) or 0):
                r["first"] = s["start"]
            if not r["last"] or (epoch(s["end"]) or 0) > (epoch(r["last"]) or 0):
                r["last"] = s["end"]
    head = ["도구", "모델", "세션 수", "사람 입력 수", "AI 응답 수", "도구 호출 수", "처음(한국 시각)", "마지막(한국 시각)"]
    rows = [[k[0], k[1], v["sessions"], v["human"], v["ai"], v["tools"], kst(v["first"]), kst(v["last"])] for k, v in g.items()]
    return head, rows


def human_rows(sessions):
    rows = []
    for s in sessions:
        for t, it in all_items(s):
            if it["kind"] == "human":
                rows.append((epoch(it["ts"]) or 0, [it["ts_kst"], s["label"], s["problem"], it.get("how", "입력"), it["text"], it["src"]]))
    rows.sort(key=lambda x: x[0])
    head = ["시각(한국)", "창", "문제", "방식", "사람이 친 글", "원본 위치"]
    return head, [r for _, r in rows]


def interaction_rows(sessions):
    rows = []
    for s in sessions:
        for t in s["turns"]:
            if s["tool"] == "codex" and t["starter"] != "AI가 다른 AI에게":
                continue
            who = t["starter"]
            if s["tool"] == "codex":
                who = "AI가 다른 AI에게" + (f" ({s['codex']['caller']} 창의 Claude 가 부름)" if s["codex"].get("caller") else "")
            rows.append((epoch(t["start"]) or 0, [t["start_kst"], s["problem"], s["tool_ko"], ", ".join(s["models"]) or "-",
                                                 who, clip(t["instruction"], 300), clip(t["result"], 300),
                                                 t["n_tool_calls"], s["label"], s["file"]]))
    rows.sort(key=lambda x: x[0])
    head = ["번호", "시각(한국)", "문제", "도구", "모델", "누가 시작", "지시(앞 300자)", "결과 요약(마지막 답의 앞 300자)",
            "도구 호출 수", "창", "원본 파일"]
    return head, [[i] + r for i, (_, r) in enumerate(rows, 1)]


def md_cell(v):
    return str(v).replace("\\", "\\\\").replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def md_table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(md_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def write_csv(path, head, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        for r in rows:
            w.writerow([str(c) for c in r])


# ---------- 읽기 쉬운 대화 기록: 블록으로 만든 뒤 형식마다 그린다 ----------
# 블록: (종류, 제목, 본문, 덧붙임)  종류: h1 h2 h3 p human ai think call result meta

def session_blocks(s, limit, level=1):
    H = lambda n: f"h{min(n + level - 1, 3)}"  # noqa: E731
    B = []
    B.append((H(1), f"{s['no']:02d}. {s['label']}  [{s['tool_ko']}]", "", ""))
    info = [f"도구: {s['tool_ko']}", f"모델: {', '.join(s['models']) or '-'}", f"문제: {s['problem']}",
            f"시간(한국): {s['start_kst']} ~ {s['end_kst']}", f"원본 파일: {s['file']}",
            f"사람 입력 {s['counts']['human']}개, AI 응답 {s['counts']['ai_responses']}개, 도구 호출 {s['counts']['tool_call']}개"]
    if s["tool"] == "codex":
        c = s["codex"]
        if c.get("log_file"):
            info.append(f"Codex 호출 기록: {c['log_file']}")
        if c.get("caller"):
            info.append(f"부른 곳: Claude Code 창 '{c['caller']}' 의 도구 호출 ({c.get('caller_src')})")
        if c.get("effort"):
            info.append(f"추론 강도: {c['effort']}")
    if s.get("note"):
        info.append(s["note"])
    B.append(("p", "", "\n".join(info), ""))
    for t in s["turns"]:
        B.append((H(2), f"주고받기 {t['index']} · {t['start_kst']} · 시작: {t['starter']}", "", ""))
        for it in t["items"]:
            tm = it["ts_kst"][11:] if it["ts_kst"] != "-" else "-"
            side = " (하위 에이전트)" if it.get("sidechain") else ""
            k = it["kind"]
            if k == "human":
                B.append(("human", f"[{tm}] 사람{' (' + it['how'] + ')' if it.get('how') not in (None, '입력') else ''}", it["text"], ""))
            elif k == "instruction":
                B.append(("human", f"[{tm}] 지시 (AI 가 쓴 프롬프트){side}", it["text"], ""))
            elif k == "assistant":
                B.append(("ai", f"[{tm}] AI 답{side}" + (f" ({it['phase']})" if it.get("phase") else ""), it["text"], ""))
            elif k == "thinking":
                B.append(("think", f"[{tm}] AI 생각(thinking){side}", it["text"], ""))
            elif k == "tool_call":
                body, n = shorten(it["text"], limit)
                B.append(("call", f"[{tm}] 도구 호출: {it.get('name')}{side}", body, cut_note(n, it["src"]) if n else ""))
            elif k == "tool_result":
                body, n = shorten(it["text"], limit)
                lab = "도구 결과(오류)" if it.get("is_error") else "도구 결과"
                B.append(("result", f"[{tm}] {lab}{side} · {len(it['text'])}자", body, cut_note(n, it["src"]) if n else ""))
            else:
                # 자동 글(기본 지시, 스킬 지시문 등)은 더 짧게
                body, n = shorten(it["text"], None if limit is None else min(limit, 800))
                B.append(("meta", f"[{tm}] 자동 글: {it.get('sub', '')}{side} · {len(it['text'])}자", body, cut_note(n, it["src"]) if n else ""))
    return B


def fence(text):
    run = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, run + 1)


def render_md(blocks):
    out = []
    for kind, title, body, note in blocks:
        if kind in ("h1", "h2", "h3"):
            out.append("#" * int(kind[1]) + " " + title + "\n")
        elif kind == "p":
            out.append("\n".join("- " + ln for ln in body.split("\n")) + "\n")
        elif kind == "human":
            out.append(f"**{title}**\n")
            out.append("\n".join("> " + ln if ln else ">" for ln in body.split("\n")) + "\n")
        elif kind == "ai":
            out.append(f"**{title}**\n\n{body}\n")
        elif kind == "think":
            out.append(f"*{title}*\n")
            out.append("\n".join("> *" + ln + "*" if ln.strip() else ">" for ln in body.split("\n")) + "\n")
        else:
            f = fence(body)
            out.append(f"**{title}**\n\n{f}text\n{body}\n{f}\n" + (f"\n{note}\n" if note else ""))
    return "\n".join(out)


def render_txt(blocks):
    out = []
    for kind, title, body, note in blocks:
        if kind == "h1":
            out += ["", "=" * 78, title, "=" * 78]
        elif kind == "h2":
            out += ["", "-" * 78, title, "-" * 78]
        elif kind == "h3":
            out += ["", "## " + title]
        elif kind == "p":
            out.append(body)
        else:
            out += ["", f"<{title}>"]
            ind = "    " if kind in ("call", "result", "meta") else "  "
            out += [ind + ln for ln in body.split("\n")]
            if note:
                out.append(ind + note)
    return "\n".join(out) + "\n"


HTML_CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--mute:#666;--line:#ddd;--hum:#eef5ff;--ai:#f7f7f7;--code:#f3f3f0;--think:#fbf8ee}
@media (prefers-color-scheme: dark){:root{--bg:#18181a;--fg:#e6e6e6;--mute:#9a9a9a;--line:#333;--hum:#1d2a3a;--ai:#222;--code:#202020;--think:#2a2618}}
body{background:var(--bg);color:var(--fg);font-family:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;
max-width:980px;margin:0 auto;padding:16px;line-height:1.55}
h1{border-bottom:2px solid var(--line);padding-bottom:4px;margin-top:2em}h2{font-size:1.1em;margin-top:1.6em;color:var(--mute)}
.b{border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin:8px 0}
.human{background:var(--hum)}.ai{background:var(--ai)}.think{background:var(--think);font-style:italic}
.t{font-weight:bold;font-size:.9em;color:var(--mute);margin-bottom:4px}
.txt{white-space:pre-wrap;word-break:break-word}
pre{background:var(--code);padding:8px;overflow-x:auto;white-space:pre-wrap;word-break:break-all;font-size:.85em;margin:4px 0}
summary{cursor:pointer;color:var(--mute);font-size:.9em}.note{color:var(--mute);font-size:.85em}
nav li{margin:2px 0}table{border-collapse:collapse}td,th{border:1px solid var(--line);padding:2px 6px;font-size:.9em}
"""


def render_html(blocks, title, toc):
    e = html.escape
    out = [f"<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
           f"<title>{e(title)}</title><style>{HTML_CSS}</style></head><body>", f"<h1>{e(title)}</h1>"]
    if toc:
        out.append("<nav><ul>" + "".join(f"<li><a href=\"#{a}\">{e(t)}</a></li>" for a, t in toc) + "</ul></nav>")
    sec = 0
    for kind, ttl, body, note in blocks:
        if kind == "h1":
            sec += 1
            out.append(f"<h1 id=\"s{sec}\">{e(ttl)}</h1>")
        elif kind in ("h2", "h3"):
            out.append(f"<{kind}>{e(ttl)}</{kind}>")
        elif kind == "p":
            out.append("<ul>" + "".join(f"<li>{e(ln)}</li>" for ln in body.split("\n")) + "</ul>")
        elif kind in ("human", "ai", "think"):
            out.append(f"<div class=\"b {kind}\"><div class=\"t\">{e(ttl)}</div><div class=\"txt\">{e(body)}</div></div>")
        else:
            n = f"<div class=\"note\">{e(note)}</div>" if note else ""
            if len(body) > 400 or kind == "meta":
                out.append(f"<details class=\"b\"><summary>{e(ttl)}</summary><pre>{e(body)}</pre>{n}</details>")
            else:
                out.append(f"<div class=\"b\"><div class=\"t\">{e(ttl)}</div><pre>{e(body)}</pre>{n}</div>")
    out.append("</body></html>")
    return "\n".join(out)


XML_BAD = re.compile("[^\u0009\u000A\u000D\u0020-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")


def xml_text(s):
    return html.escape(XML_BAD.sub("", s or ""), quote=False)


def render_docx(blocks, path, title):
    """손으로 만든 최소 Word 파일. 제목 + 문단만"""
    def para(text, style=None):
        ppr = f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>" if style else ""
        return f"<w:p>{ppr}<w:r><w:t xml:space=\"preserve\">{xml_text(text)}</w:t></w:r></w:p>"

    body = [para(title, "Title")]
    for kind, ttl, txt, note in blocks:
        if kind in ("h1", "h2", "h3"):
            body.append(para(ttl, "Heading" + kind[1]))
            continue
        if kind == "p":
            body += [para(ln) for ln in txt.split("\n")]
            continue
        body.append(para(ttl, "Label"))
        style = {"human": "Human", "ai": None, "think": "Think"}.get(kind, "Code")
        body += [para(ln, style) for ln in txt.split("\n")]
        if note:
            body.append(para(note, "Note"))
    doc = ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
           "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body>"
           + "".join(body) +
           "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/><w:pgMar w:top=\"1134\" w:right=\"1134\" w:bottom=\"1134\" w:left=\"1134\" "
           "w:header=\"567\" w:footer=\"567\" w:gutter=\"0\"/></w:sectPr></w:body></w:document>")

    def sty(sid, name, rpr="", ppr="", based="Normal"):
        return (f"<w:style w:type=\"paragraph\" w:styleId=\"{sid}\"><w:name w:val=\"{name}\"/><w:basedOn w:val=\"{based}\"/>"
                f"<w:qFormat/><w:pPr>{ppr}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>")
    styles = ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
              "<w:styles xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
              "<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii=\"Malgun Gothic\" w:hAnsi=\"Malgun Gothic\" "
              "w:eastAsia=\"Malgun Gothic\" w:cs=\"Malgun Gothic\"/><w:sz w:val=\"20\"/><w:lang w:val=\"ko-KR\" w:eastAsia=\"ko-KR\"/></w:rPr>"
              "</w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after=\"0\" w:line=\"264\" w:lineRule=\"auto\"/></w:pPr></w:pPrDefault></w:docDefaults>"
              "<w:style w:type=\"paragraph\" w:default=\"1\" w:styleId=\"Normal\"><w:name w:val=\"Normal\"/><w:qFormat/></w:style>"
              + sty("Title", "Title", "<w:b/><w:sz w:val=\"36\"/>", "<w:spacing w:after=\"240\"/>")
              + sty("Heading1", "heading 1", "<w:b/><w:sz w:val=\"30\"/>", "<w:keepNext/><w:spacing w:before=\"360\" w:after=\"120\"/><w:outlineLvl w:val=\"0\"/>")
              + sty("Heading2", "heading 2", "<w:b/><w:sz w:val=\"24\"/>", "<w:keepNext/><w:spacing w:before=\"240\" w:after=\"80\"/><w:outlineLvl w:val=\"1\"/>")
              + sty("Heading3", "heading 3", "<w:b/><w:sz w:val=\"22\"/>", "<w:keepNext/><w:spacing w:before=\"160\"/><w:outlineLvl w:val=\"2\"/>")
              + sty("Label", "Label", "<w:b/><w:color w:val=\"555555\"/>", "<w:keepNext/><w:spacing w:before=\"160\"/>")
              + sty("Human", "Human", "<w:color w:val=\"1F4E79\"/>", "<w:ind w:left=\"284\"/>")
              + sty("Think", "Think", "<w:i/><w:color w:val=\"7F6000\"/>", "<w:ind w:left=\"284\"/>")
              + sty("Code", "Code", "<w:rFonts w:ascii=\"Consolas\" w:hAnsi=\"Consolas\"/><w:sz w:val=\"16\"/>", "<w:ind w:left=\"284\"/>")
              + sty("Note", "Note", "<w:i/><w:color w:val=\"808080\"/><w:sz w:val=\"16\"/>")
              + "</w:styles>")
    ct = ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
          "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
          "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
          "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
          "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
          "<Override PartName=\"/word/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml\"/>"
          "<Override PartName=\"/docProps/core.xml\" ContentType=\"application/vnd.openxmlformats-package.core-properties+xml\"/>"
          "</Types>")
    rels = ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
            "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>"
            "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties\" Target=\"docProps/core.xml\"/>"
            "</Relationships>")
    drels = ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
             "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
             "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>"
             "</Relationships>")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    core = ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" "
            "xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:dcterms=\"http://purl.org/dc/terms/\" "
            "xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">"
            f"<dc:title>{xml_text(title)}</dc:title><dc:creator>{SCRIPT_NAME}</dc:creator>"
            f"<dcterms:created xsi:type=\"dcterms:W3CDTF\">{now}</dcterms:created></cp:coreProperties>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", drels)
        z.writestr("docProps/core.xml", core)


# ---------- 파일 쓰기 ----------

def totals(sessions):
    c = Counter()
    for s in sessions:
        for k, v in s["counts"].items():
            c[k] += v
        c["turns"] += len(s["turns"])
    c["sessions"] = len(sessions)
    c["claude"] = sum(1 for s in sessions if s["tool"] == "claude" and not s.get("side_question"))
    c["side_sessions"] = sum(1 for s in sessions if s.get("side_question"))
    c["side_questions"] = sum(s["counts"]["human"] for s in sessions if s.get("side_question"))
    c["codex"] = sum(1 for s in sessions if s["tool"] == "codex")
    return c


def write_outputs(sessions, stats, out, formats, limit, since):
    out.mkdir(parents=True, exist_ok=True)
    for sub in ("transcripts", "by_problem"):
        d = out / sub
        if d.is_dir():
            for p in d.glob("*.md"):
                p.unlink()
    written = []
    T = totals(sessions)
    ts_all = [s["start"] for s in sessions] + [s["end"] for s in sessions]
    t0 = min(ts_all, key=lambda x: epoch(x) or 0) if ts_all else None
    t1 = max(ts_all, key=lambda x: epoch(x) or 0) if ts_all else None
    lim_txt = "줄이지 않음(--full)" if limit is None else f"{limit}자"

    def w(name, text):
        p = out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        written.append(p)

    h1, r1 = tools_models_rows(sessions)
    h2, r2 = human_rows(sessions)
    h3, r3 = interaction_rows(sessions)
    if "md" in formats:
        w("01_tools_and_models.md", "# 사용한 AI 도구와 모델\n\n원본 기록에서 계산했다(손으로 쓰지 않음). 시각은 한국 시각.\n\n"
          + md_table(h1, r1) + "\n\n## 세션(대화창)별\n\n"
          + md_table(["번호", "창", "도구", "모델", "문제", "처음", "마지막", "사람 입력", "AI 응답", "도구 호출", "원본 파일"],
                     [[s["no"], s["label"], s["tool_ko"], ", ".join(s["models"]) or "-", s["problem"], s["start_kst"], s["end_kst"],
                       s["counts"]["human"], s["counts"]["ai_responses"], s["counts"]["tool_call"], s["file"]] for s in sessions]) + "\n")
        w("02_human_inputs.md", "# 사람이 직접 친 입력 (모든 창, 시각 순)\n\n"
          "Claude Code 창에 사람이 친 글만 모았다. 도구 결과, 자동으로 붙은 글, 스킬 지시문, AI 가 다른 AI 에게 준 지시는 뺐다.\n"
          "슬래시 명령은 `/solve p1` 처럼 친 그대로 보인다. '작업 중에 입력' 은 AI 가 일하는 도중에 친 글이다.\n"
          "'곁 질문(/btw)' 은 옆 대화 패널에서 물은 것이다(대화 기록 밖이라 VS Code 저장소에서 따로 모았다).\n\n"
          f"모두 {len(r2)}개.\n\n" + md_table(h2, r2) + "\n")
        w("03_interactions.md", "# 주고받기 목록\n\n한 줄 = 사람의 입력 한 번과 그 뒤 다음 입력 전까지 AI 가 한 일. Codex 는 호출 한 번이 한 줄이다.\n"
          "지시와 결과는 앞 300자만 보인다. 전체는 transcripts/ 에 있다.\n\n" + md_table(h3, r3) + "\n")
    if "csv" in formats:
        for name, h, r in (("01_tools_and_models.csv", h1, r1), ("02_human_inputs.csv", h2, r2), ("03_interactions.csv", h3, r3)):
            write_csv(out / name, h, r)
            written.append(out / name)

    per = {s["no"]: session_blocks(s, limit) for s in sessions}
    allb = []
    for s in sessions:
        allb += per[s["no"]]
    head_md = (f"# AI 사용 대화 기록 전체\n\n원본 기록(logs/raw/)에서 {SCRIPT_NAME} 가 기계적으로 만들었다. 시각은 한국 시각(UTC+9).\n"
               f"긴 도구 출력은 {lim_txt}로 줄였다. 사람과 AI 의 글은 줄이지 않았다.\n\n## 차례\n\n"
               + "\n".join(f"{s['no']}. {s['label']} ({s['tool_ko']}, {s['start_kst']}) — transcripts/{s['out_name']}.md" for s in sessions) + "\n\n")
    if "md" in formats:
        for s in sessions:
            w(f"transcripts/{s['out_name']}.md", render_md(per[s["no"]]))
        w("transcript_all.md", head_md + render_md(allb))
        # 문제별 묶음
        probs = sorted({s["problem"] for s in sessions}, key=lambda x: (x == "공통", int(x[1:]) if re.fullmatch(r"p\d+", x) else 0, x))
        for pid in probs:
            ss = [s for s in sessions if s["problem"] == pid]
            hum = [r for r in r2 if r[2] == pid or (pid != "공통" and r[2] == "공통" and re.search(rf"\b{pid}\b", r[4]))]
            inter = [r for r in r3 if r[2] == pid]
            txt = (f"# 문제 {pid} 의 AI 사용 내역\n\n" if pid != "공통" else "# 특정 문제에 묶이지 않은 AI 사용 내역(공통)\n\n")
            txt += (f"이 문제에 쓴 창과 호출: " + ", ".join(f"{s['label']}" for s in ss) + "\n\n## 사람이 친 입력\n\n"
                    + (md_table(h2, hum) if hum else "(없음)") + "\n\n## 주고받기 목록\n\n" + (md_table(h3, inter) if inter else "(없음)")
                    + "\n\n## 대화 기록\n\n")
            for s in ss:
                txt += render_md(session_blocks(s, limit, level=2)) + "\n"
            w(f"by_problem/{'common' if pid == '공통' else pid}.md", txt)
    if "txt" in formats:
        w("transcript_all.txt", re.sub(r"[#`*>]", "", head_md.split("## 차례")[0]).strip() + "\n\n"
          + "\n".join(f"{s['no']}. {s['label']} ({s['tool_ko']}, {s['start_kst']})" for s in sessions) + "\n" + render_txt(allb))
    if "html" in formats:
        toc = [(f"s{i}", f"{s['no']:02d}. {s['label']} ({s['tool_ko']}, {s['start_kst']})") for i, s in enumerate(sessions, 1)]
        w("transcript_all.html", render_html(allb, "AI 사용 대화 기록 전체", toc))
    if "docx" in formats:
        p = out / "transcript_all.docx"
        intro = [("p", "", f"원본 기록(logs/raw/)에서 {SCRIPT_NAME} 가 기계적으로 만들었다.\n시각은 한국 시각(UTC+9).\n"
                  f"긴 도구 출력은 {lim_txt}로 줄였다. 사람과 AI 의 글은 줄이지 않았다.", "")]
        render_docx(intro + allb, p, "AI 사용 대화 기록 전체")
        written.append(p)
    if "json" in formats:
        model = {"made_by": SCRIPT_NAME, "made_at_kst": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                 "since_epoch": since, "timezone_note": "ts 는 UTC, ts_kst 는 한국 시각", "totals": dict(T),
                 "skipped_line_types": dict(stats["skipped"]), "unknown_line_types": dict(stats["unknown"]),
                 "sessions": sessions}
        w("sessions.json", json.dumps(model, ensure_ascii=False, indent=1))

    # 00_README 는 늘 쓴다
    names = sorted(p.relative_to(out).as_posix() for p in written)
    desc = {
        "01_tools_and_models": "사용한 도구와 모델, 세션 수, 응답 수, 처음과 마지막 시각(원본 기록에서 계산)",
        "02_human_inputs": "사람이 직접 친 입력만, 모든 창을 시각 순으로. 사람이 무엇을 정했는지 보인다",
        "03_interactions": "주고받기 한 번이 한 줄인 표(시각, 문제, 도구, 모델, 누가 시작, 지시, 결과 요약, 도구 호출 수)",
        "transcript_all": "모든 대화 기록을 한 파일로",
        "sessions.json": "정리한 기록 전체(기계용). 다른 형식이 더 필요하면 이것에서 만든다",
    }
    lines = ["# AI 사용 내역 묶음 안내", "",
             f"이 폴더의 파일은 원본 대화 기록(`logs/raw/claude/*.jsonl`, `logs/raw/codex/*.jsonl`)에서 `{SCRIPT_NAME}` 가 "
             "기계적으로 만들었다. 사람이 손으로 고친 것은 없다.", "",
             f"- 만든 시각(한국): {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 기록 범위(한국): {kst(t0)} ~ {kst(t1)}",
             f"- 포함 기준: {kst(iso(datetime.fromtimestamp(since, timezone.utc))) + ' 이후의 줄만(작업 시작 10분 전)' if since else '원본 폴더의 모든 줄'}",
             f"- 세션: {T['sessions']}개 (Claude Code 창 {T['claude']}개, Codex 호출 {T['codex']}개"
             + (f", 곁 질문 묶음 {T['side_sessions']}개" if T["side_sessions"] else "") + ")",
             f"- 사람이 친 입력: {T['human']}개" + (f"(곁 질문 {T['side_questions']}개 포함)" if T["side_questions"] else "")
             + f" / AI 가 다른 AI 에게 준 지시: {T['instruction']}개",
             f"- 주고받기: {T['turns']}번 / AI 응답: {T['ai_responses']}개 / AI 글: {T['assistant']}개 / 도구 호출: {T['tool_call']}개",
             "- 시각은 모두 한국 시각(UTC+9)이다. 원본 기록에는 UTC 로 적혀 있다.", "",
             "## 곁 질문(/btw)", "",
             "- 곁 질문은 VS Code 의 Claude Code 창 옆 대화 패널에서 따로 물은 것이다(`/btw`). 부모 창의 대화를 보고 "
             "부모 창의 모델이 답하지만, 대화 기록(.jsonl)에는 남지 않는다. 그래서 `scripts/collect_logs.py` 가 VS Code 저장소에서 "
             "따로 모아 `logs/raw/side_questions.json` 에 쌓는다.",
             f"- 이 폴더에서는 부모 창마다 '곁 질문(/btw) · 부모 창' 이라는 세션 하나로 넣었다(지금 {T['side_questions']}개). "
             "`02_human_inputs` 의 방식 칸에 '곁 질문(/btw)' 으로, `03_interactions`, `transcript_all`, `transcripts/*_btw_*.md`, "
             "`by_problem/` 에도 들어 있다. 시각은 확장 기록의 요청 시각이고, 찾지 못한 것은 '시각은 어림' 이라고 적었다.",
             "- 옆 대화 패널에서 손으로 옮긴 글이 있으면 `logs/side_questions_manual.txt` 에 있다(원본 묶음 zip 에 들어 있다).", "",
             "## 줄인 것", "",
             f"- 읽기용 파일에서 도구 출력, 도구 입력(예: 파일 내용), 자동으로 붙은 글은 {lim_txt}로 줄였다. "
             "줄인 곳에는 '(… N자 줄임. 전체는 raw 기록에 있음: 파일:줄)' 이 적혀 있다.",
             "- 사람의 글과 AI 의 답은 줄이지 않았다. AI 의 생각(thinking)은 기록에 글이 남은 것만 넣었다(대부분은 암호화되어 글이 없다).",
             "- 원본 기록의 중복 사본(API 요청 사본), 환경 정보, 토큰 수 같은 기계용 줄은 읽기용 파일에 넣지 않았다. 원본 기록에는 모두 있다.", "",
             "## 파일", ""]
    for n in names:
        key = next((k for k in desc if n.startswith(k)), None)
        if key:
            d = desc[key]
        elif n.startswith("transcripts/") and "_btw_" in n:
            d = "창 하나에서 물은 곁 질문(/btw)과 답"
        elif n.startswith("transcripts/"):
            d = "세션(대화창 또는 Codex 호출) 하나의 전체 대화 기록"
        elif n.startswith("by_problem/"):
            d = "문제 하나에 관한 것을 한 파일에(그 문제의 Claude 창, Codex 호출, 사람 입력)"
        else:
            d = ""
        lines.append(f"- `{n}`: {d}")
    lines += ["", "## 세션 목록", "",
              md_table(["번호", "창", "도구", "모델", "문제", "시간(한국)", "읽기용 파일"],
                       [[s["no"], s["label"], s["tool_ko"], ", ".join(s["models"]) or "-", s["problem"],
                         f"{s['start_kst']} ~ {s['end_kst'][11:]}", f"transcripts/{s['out_name']}.md"] for s in sessions]), ""]
    if stats["warnings"]:
        lines += ["## 경고", ""] + [f"- {x}" for x in stats["warnings"]] + [""]
    w("00_README.md", "\n".join(lines))
    return written


# ---------- zip ----------

def make_zips(out, mode, max_mb, stats):
    base = out.parent
    stem = f"{out.name}_{mode}"
    for p in base.glob(f"{stem}*.zip"):
        p.unlink()
    readable = [(p, f"{out.name}/{p.relative_to(out).as_posix()}") for p in sorted(out.rglob("*")) if p.is_file()]
    extra, raw = [], []
    if mode == "full":
        for p in sorted((ROOT / "logs").glob("codex_*.log")):
            extra.append((p, f"logs/{p.name}"))
        for name in ("MANIFEST.md", "EXAM.json", "TIMELINE.tsv"):
            if (ROOT / "logs" / name).exists():
                extra.append((ROOT / "logs" / name, f"logs/{name}"))
        raw = [(p, p.relative_to(ROOT).as_posix()) for p in sorted((ROOT / "logs" / "raw").rglob("*")) if p.is_file()]
    limit = max_mb * 1024 * 1024 if max_mb else None

    def write(path, entries):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for src, arc in entries:
                z.write(src, arc)
        return path.stat().st_size

    one = base / f"{stem}.zip"
    size = write(one, readable + extra + raw)
    if not limit or size <= limit:
        return [one]
    one.unlink()
    # 압축 크기 어림값으로 순서대로 나눠 담는다(읽기용 → Codex 호출 기록 → 원본). 첫 묶음에 안내 파일이 들어간다
    est = [(src, arc, len(zlib.compress(src.read_bytes(), 6)) + 200) for src, arc in readable + extra + raw]
    parts, cur, cur_size = [], [], 0
    for src, arc, n in est:
        if cur and cur_size + n > limit * 0.95:
            parts.append(cur)
            cur, cur_size = [], 0
        cur.append((src, arc))
        cur_size += n
        if n > limit:
            stats["warnings"].append(f"{arc} 하나만으로 한도 {max_mb}MB 를 넘음")
    if cur:
        parts.append(cur)
    res = []
    for i, entries in enumerate(parts, 1):
        p = base / f"{stem}_part{i}.zip"
        sz = write(p, entries)
        res.append(p)
        if sz > limit:
            stats["warnings"].append(f"{p.name} 가 {sz / 1048576:.2f}MB 로 한도를 넘음")
    stats["notes"].append(f"zip 하나가 {size / 1048576:.1f}MB 로 {max_mb:g}MB 를 넘어 {len(res)}개로 나눴다. "
                          f"part1 에 안내(00_README.md)와 읽기용 파일이, 뒤쪽에 원본 기록이 들어 있다. 모두 함께 보낸다")
    return res


# ---------- 실행 ----------

def main():
    ap = argparse.ArgumentParser(description="AI 사용 내역을 제출용 여러 형식으로 바꾼다")
    ap.add_argument("--out", default="submit/ai_usage", help="쓸 폴더 (기본 submit/ai_usage)")
    ap.add_argument("--formats", default=",".join(ALL_FORMATS), help="md,txt,html,docx,csv,json 중에서 쉼표로")
    ap.add_argument("--since", type=float, default=None, help="이 epoch 뒤의 기록만 (기본: logs/EXAM.json 시작 - 10분)")
    ap.add_argument("--tool-limit", type=int, default=2000, help="읽기용 파일에서 도구 출력을 줄일 글자 수")
    ap.add_argument("--full", action="store_true", help="아무것도 줄이지 않음")
    ap.add_argument("--zip", choices=["light", "full"], help="light: 만든 파일만, full: + 원본 기록 + Codex 호출 기록")
    ap.add_argument("--max-mb", type=float, default=None, help="zip 한 개의 최대 크기(MB). 넘으면 원본을 나눠 담는다")
    ap.add_argument("--check", action="store_true", help="파일을 쓰지 않고 개수와 경고만")
    ap.add_argument("--raw", default="logs/raw", help=argparse.SUPPRESS)
    a = ap.parse_args()
    t_start = time.time()

    formats = [f.strip() for f in a.formats.split(",") if f.strip()]
    bad = [f for f in formats if f not in ALL_FORMATS]
    if bad:
        print(f"모르는 형식: {', '.join(bad)} (쓸 수 있는 것: {', '.join(ALL_FORMATS)})")
        return 2
    since = a.since
    since_basis = "--since 로 준 값"
    if since is None:
        try:
            since = json.loads((ROOT / "logs" / "EXAM.json").read_text(encoding="utf-8"))["start"] - 600
            since_basis = "logs/EXAM.json 의 시작 시각 - 10분"
        except Exception:  # noqa: BLE001
            since, since_basis = None, "제한 없음(logs/EXAM.json 이 없음)"
    stats = {"warnings": [], "notes": [], "skipped": Counter(), "unknown": Counter(), "bad_lines": Counter()}
    raw_dir = (ROOT / a.raw) if not Path(a.raw).is_absolute() else Path(a.raw)
    files = list(raw_dir.rglob("*.jsonl")) if raw_dir.is_dir() else []
    if not files:
        stats["warnings"].append(f"원본 기록 폴더({raw_dir.relative_to(ROOT) if raw_dir.is_relative_to(ROOT) else raw_dir})가 비어 있음. "
                                 "먼저 scripts/collect_logs.sh 를 돌린다")
    sessions = build_model(raw_dir, since, stats)
    T = totals(sessions)
    for k, v in stats["unknown"].items():
        stats["warnings"].append(f"모르는 형식의 줄 {v}개를 건너뜀: {k}")

    print(f"범위: {kst(iso(datetime.fromtimestamp(since, timezone.utc))) + ' 이후' if since else '전체'} ({since_basis})")
    print(f"세션 {T['sessions']}개 (Claude Code {T['claude']}, Codex {T['codex']}) · 사람 입력 {T['human']} · "
          f"AI→AI 지시 {T['instruction']} · 주고받기 {T['turns']} · AI 응답 {T['ai_responses']} · AI 글 {T['assistant']} · "
          f"생각 {T['thinking']} · 도구 호출 {T['tool_call']} · 도구 결과 {T['tool_result']} · 자동 글 {T['system']}"
          f" · 곁 질문 {T['side_questions']}")
    for s in sessions:
        print(f"  {s['no']:02d} {s['start_kst'][5:16]} {s['tool_ko']:<11} {s['problem']:<4} {s['label']}  "
              f"(사람 {s['counts']['human']}, 응답 {s['counts']['ai_responses']}, 도구 {s['counts']['tool_call']}, 모델 {', '.join(s['models']) or '-'})")

    if not a.check:
        out = (ROOT / a.out) if not Path(a.out).is_absolute() else Path(a.out)
        written = write_outputs(sessions, stats, out, formats, None if a.full else a.tool_limit, since)
        total = sum(p.stat().st_size for p in written)
        print(f"\n{out} 에 파일 {len(written)}개, 모두 {total / 1048576:.2f}MB 를 썼습니다.")
        if a.zip:
            for z in make_zips(out, a.zip, a.max_mb, stats):
                print(f"  zip: {z} ({z.stat().st_size / 1048576:.2f}MB)")
    else:
        print("\n(--check: 파일을 쓰지 않았습니다)")

    skipped = sum(stats["skipped"].values())
    print(f"\n읽지 않고 넘긴 줄(알려진 기계용 줄): {skipped}개" + (" — " + ", ".join(f"{k} {v}" for k, v in stats["skipped"].most_common(8)) + " …" if skipped else ""))
    print(f"모르는 형식이라 건너뛴 줄: {sum(stats['unknown'].values())}개" + (" — " + ", ".join(f"{k} {v}" for k, v in stats["unknown"].items()) if stats["unknown"] else ""))
    print(f"깨진 줄: {sum(stats['bad_lines'].values())}개")
    for n in stats["notes"]:
        print("참고: " + n)
    if stats["warnings"]:
        print("\n경고")
        for x in stats["warnings"]:
            print("  - " + x)
    else:
        print("\n경고: 없음")
    print(f"걸린 시간 {time.time() - t_start:.1f}초")
    return 0


if __name__ == "__main__":
    sys.exit(main())
