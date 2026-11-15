#!/usr/bin/env python3
"""제출 묶음을 만든다. 메일을 보내기 직전에 터미널에서 돌린다.

사용: scripts/pack.sh

만드는 것 (submit/ 안)
- pN.cpp ...            답안. final_gate 가 이미 복사해 둔 것 그대로다.
- ai_usage_logs.zip     AI 사용 내역 묶음:
    AI_USAGE.md, HARNESS.md, AI_GUIDELINE.md, SUBMIT_RULES.md
    logs/ (내보낸 대화 기록, 원본 기록, 곁 질문 기록, Codex 호출 기록, 목록, 시간표, git 기록)
    problems/pN/ (문제, 요구사항, 예외 표, 결정, 보고서, 검증 결과, 테스트, 독립 구현, 생성기, 검사기, 리뷰)
    ai_usage/ (원본 기록에서 기계로 만든 읽기 쉬운 대화 기록, 사람이 입력한 것, 도구와 모델 표)
- ai_usage/             같은 내용을 여러 형식으로 풀어 둔 폴더(글, 표, 워드, 웹 문서, 문제별 파일).
                        과제 안내문이 다른 형식을 요구하면 여기서 골라 첨부한다 (scripts/usage_export.sh)
- SUBMIT_LIST.md        첨부할 파일의 목록과 크기, 확인할 것

먼저 원본 기록을 다시 모은다(이 응답 직전까지 들어가도록).
대화창마다 /export 를 치지 않아도 된다. 읽기 쉬운 대화 기록은 원본 기록에서 만든다.
지난 연습의 대화 기록(작업 시작 전의 claude_session*.txt)은 넣지 않는다.
과제 안내문이 다른 제출 형식을 요구하면 그것을 따른다(SUBMIT_RULES.md).
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBMIT = ROOT / "submit"
SKIP_DIRS = {"build", "__pycache__", "fuzz_fail", "probe"}
MAIL_LIMIT = 20 * 1024 * 1024


def exam_start():
    try:
        return json.loads((ROOT / "logs" / "EXAM.json").read_text(encoding="utf-8"))["start"] - 600
    except Exception:  # noqa: BLE001
        return None


def sha16(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def answer_check(pdir, warn, facts):
    """submit/pN.cpp 가 지금의 풀이 파일이고, 마지막 최종 관문을 통과한 것인지 본다"""
    name = pdir.name
    sub, cur = SUBMIT / f"{name}.cpp", pdir / f"{name}.cpp"
    if not cur.exists():
        warn.append(f"**{name}: problems/{name}/{name}.cpp 가 없다.** submit/{name}.cpp 가 무엇인지 사람이 본다")
        return
    cur_sha = sha16(cur)
    if sha16(sub) != cur_sha:
        warn.append(f"**submit/{name}.cpp 는 지금의 problems/{name}/{name}.cpp 와 다르다(먼저 통과한 옛 판이다). "
                    "어느 것을 낼지 사람이 정한다**")
    try:
        v = json.loads((pdir / "VERIFY.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        warn.append(f"**{name}: VERIFY.json 이 없거나 읽지 못했다.** `scripts/final_gate.sh {name}` 을 다시 돌린다")
        return
    bad = []
    if v.get("sha") != cur_sha:
        bad.append("마지막 검증이 지금의 풀이 파일의 것이 아니다")
    if v.get("verdict") == "FAIL":
        bad.append("마지막 검증이 FAIL 이다")
    if not v.get("final"):
        bad.append("마지막 검증이 최종 관문(final_gate)이 아니다")
    elif not v.get("copied"):
        bad.append("마지막 최종 관문이 submit/ 에 복사하지 않았다")
    if bad:
        warn.append(f"**{name}: " + ", ".join(bad) + f".** `scripts/final_gate.sh {name}` 을 다시 돌린다")
    elif v.get("accept"):
        facts.append(f"{name}: 조건부, 사람이 받아들임: {v['accept']}")


def main():
    warn, facts = [], []
    if not os.environ.get("COTEST_SKIP_COLLECT"):      # 시험용: 이미 모아 둔 logs/raw 를 그대로 쓴다
        collect = [sys.executable, str(ROOT / "scripts" / "collect_logs.py")]
        # --quiet 를 주지 않는다: 다른 수집이 잠금을 오래 쥐고 있으면 종료 코드 3 으로 알 수 있다. 실패하면 한 번 더
        ok = any(subprocess.run(collect, capture_output=True).returncode == 0 for _ in range(2))
        if not ok:
            warn.append("**대화 기록 수집이 실패했다. `scripts/pack.sh` 를 다시 돌린다**")
    SUBMIT.mkdir(exist_ok=True)
    since = exam_start()

    log_txt = subprocess.run(["git", "log", "--date=format:%Y-%m-%d %H:%M:%S", "--format=%ad %h %s"],
                             cwd=ROOT, capture_output=True, text=True).stdout
    (ROOT / "logs" / "GIT_LOG.txt").write_text(log_txt, encoding="utf-8")

    files = []
    for name in ("AI_USAGE.md", "HARNESS.md", "AI_GUIDELINE.md", "SUBMIT_RULES.md"):
        if (ROOT / name).exists():
            files.append(ROOT / name)
    for p in sorted((ROOT / "logs").rglob("*")):
        if not p.is_file() or any(x.startswith(".") for x in p.relative_to(ROOT / "logs").parts):
            continue      # 숨은 파일, 수집 도중의 임시 폴더(logs/raw/.claude.tmp 등)는 넣지 않는다
        if p.name.startswith("claude_session") and since and p.stat().st_mtime < since:
            warn.append(f"`logs/{p.name}` 은 작업 시작 전의 것이라 넣지 않았다")
            continue
        files.append(p)
    answers = sorted(SUBMIT.glob("*.cpp"))
    for pdir in sorted((ROOT / "problems").glob("*")):
        if not pdir.is_dir():
            continue
        for p in sorted(pdir.rglob("*")):
            if p.is_file() and not (set(p.relative_to(pdir).parts) & SKIP_DIRS) and p.suffix != ".pyc":
                files.append(p)
        if not (SUBMIT / f"{pdir.name}.cpp").exists():
            warn.append(f"**{pdir.name} 의 답안이 submit/ 에 없다.** `scripts/final_gate.sh {pdir.name}` 을 돌린다(조건부면 사람의 승인이 필요하다)")
        else:
            answer_check(pdir, warn, facts)

    exports = [p for p in files if p.name.startswith("claude_session")]
    if not any("raw/claude" in str(p) for p in files):
        warn.append("**Claude Code 원본 기록이 없다.** `logs/MANIFEST.md` 를 본다")

    # 곁 질문(/btw): 대화 기록 밖이라 collect_logs 가 따로 모은다. 확장 기록보다 적으면 손으로 옮겨야 한다
    sq_counts, sq_problem = {}, None
    try:
        sq = json.loads((ROOT / "logs" / "raw" / "side_questions.json").read_text(encoding="utf-8"))
        sq_counts, sq_problem = sq.get("counts") or {}, sq.get("source_problem")
    except Exception:  # noqa: BLE001
        sq_problem = "logs/raw/side_questions.json 이 없거나 읽지 못했다"
    manual = ROOT / "logs" / "side_questions_manual.txt"
    if manual.is_file() and manual not in files:
        files.append(manual)
    if sq_counts.get("missing"):
        warn.append(f"**곁 질문(/btw) {sq_counts['missing']}건이 기록에 없다** (확장 기록의 요청 {sq_counts.get('log_requests')}번, "
                    f"모은 것 {sq_counts.get('collected')}건). 옆 대화 패널의 글을 손으로 복사해 `logs/side_questions_manual.txt` 에 "
                    "붙여 넣고 `scripts/pack.sh` 를 다시 돌린다"
                    + (" (손으로 옮긴 파일이 이미 있다. 빠진 것이 다 들어 있는지 본다)" if manual.is_file() else ""))

    # 원본 기록에서 읽기 쉬운 형식을 만든다 (submit/ai_usage/). 형식이 바뀌어도 여기서 골라 낸다.
    usage_dir = SUBMIT / "ai_usage"
    ue = subprocess.run([sys.executable, str(ROOT / "scripts" / "usage_export.py"), "--out", str(usage_dir)],
                        cwd=ROOT, capture_output=True, text=True)
    usage_files = sorted(p for p in usage_dir.rglob("*") if p.is_file()) if usage_dir.is_dir() else []
    readable = [p for p in usage_files if p.name.startswith("transcript_all")]
    if ue.returncode != 0 or not readable:
        warn.append("**읽기 쉬운 대화 기록을 만들지 못했다** (`scripts/usage_export.sh --check` 로 이유를 본다). "
                    "급하면 Claude Code 대화창마다 `/export logs/claude_session_p1.txt` 를 치고 다시 돌린다: "
                    + (ue.stderr.strip().splitlines()[-1][:160] if ue.stderr.strip() else "출력 없음"))
    in_warn = False
    for ln in ue.stdout.splitlines():
        s = ln.strip()
        if s.startswith("경고"):
            in_warn = "없음" not in s
            continue
        if in_warn and s.startswith("-") and "곁 질문 요청이" in s:
            continue      # 위에서 이미 적었다
        if in_warn and s.startswith("-"):
            warn.append("대화 기록 변환: " + s.lstrip("- ")[:200])
        elif not s.startswith("-"):
            in_warn = False
    human_md = usage_dir / "02_human_inputs.md"
    if human_md.exists() and "모두 0개" in human_md.read_text(encoding="utf-8", errors="replace"):
        warn.append("**대화 기록에서 사람이 입력한 것을 하나도 찾지 못했다.** Claude Code 원본 기록이 모였는지 `logs/MANIFEST.md` 를 본다")

    zpath = SUBMIT / "ai_usage_logs.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(ROOT).as_posix())
        for p in usage_files:
            if p.name != "sessions.json":      # 원본 기록과 겹치는 큰 파일은 묶음에서 뺀다(폴더에는 있다)
                z.write(p, "ai_usage/" + p.relative_to(usage_dir).as_posix())
    zsize = zpath.stat().st_size
    if zsize > MAIL_LIMIT:
        warn.append(f"묶음이 {zsize / 1e6:.0f}MB 다. 메일 첨부 한도(보통 20~25MB)를 넘을 수 있다. 드라이브 링크로 보내는 방법을 생각한다")

    lines = ["# 제출 목록", "", f"만든 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}", "",
             "## 메일에 첨부할 것", "", "| 파일 | 크기 | 내용 |", "|---|---|---|"]
    for a in answers:
        lines.append(f"| `submit/{a.name}` | {a.stat().st_size} 바이트 | 답안 |")
    lines.append(f"| `submit/ai_usage_logs.zip` | {zsize / 1e6:.1f}MB | AI 사용 내역 묶음 (파일 {len(files)}개) |")
    lines += ["", "## 묶음에 든 것",
              f"- 읽기 쉬운 대화 기록(원본에서 기계로 만든 것): ai_usage/ 아래 {len(usage_files)}개 파일. "
              "전체 한 파일(`transcript_all.md/.txt/.html/.docx`), 창별(`transcripts/`), 문제별(`by_problem/`), "
              "사람이 입력한 것만(`02_human_inputs`), 주고받은 일의 표(`03_interactions`), 도구와 모델 표(`01_tools_and_models`)",
              f"- 손으로 내보낸 대화 기록(/export): {', '.join(p.name for p in exports) or '없음 (없어도 된다)'}",
              f"- 원본 기록: Claude Code {sum(1 for p in files if 'raw/claude' in p.as_posix())}개, Codex {sum(1 for p in files if 'raw/codex' in p.as_posix())}개 (목록은 logs/MANIFEST.md)",
              "- 곁 질문(/btw, 옆 대화 패널) 기록: "
              + (f"`logs/raw/side_questions.json` {sq_counts.get('collected', 0)}건 (확장 기록의 요청 {sq_counts.get('log_requests', 0)}번)"
                 if sq_counts else "없음")
              + (f". 저장소 문제: {sq_problem}" if sq_problem else "")
              + (". 손으로 옮긴 것: `logs/side_questions_manual.txt`" if manual.is_file() else ""),
              "- AI_USAGE.md (쓴 도구와 모델, 문제별로 AI가 한 일과 사람이 한 일, 시간순 기록)",
              "- HARNESS.md (작업 방식 설명), 문제별 결정·보고서·검증 결과·테스트"]
    lines += ["", "## 안내문이 다른 형식을 요구할 때 (`submit/ai_usage/` 에서 골라 첨부한다)", "",
              "| 요구 | 낼 파일 |", "|---|---|",
              "| 압축 파일 하나 | `submit/ai_usage_logs.zip` (위와 같다) |",
              "| 글 파일 하나 / 문서 하나 | `ai_usage/transcript_all.txt` / `transcript_all.docx` (PDF 는 `transcript_all.html` 을 브라우저에서 열어 인쇄 → PDF 로 저장) |",
              "| 표(엑셀) | `ai_usage/03_interactions.csv` (주고받은 일 한 줄씩), `01_tools_and_models.csv`, `02_human_inputs.csv` |",
              "| 문제별로 따로 | `ai_usage/by_problem/p1.md` … |",
              "| 사람이 무엇을 입력했는지만 | `ai_usage/02_human_inputs.md` |",
              "| 메일 본문에 붙여 넣을 요약 | `AI_USAGE.md` 의 맨 위 두 절(도구와 모델, 문제별 요약) |",
              "| 원본 기록만 / 용량 제한 | `scripts/usage_export.sh --zip full --max-mb 20` (넘으면 나눠 담는다), 가벼운 묶음은 `--zip light` |",
              "| 정해진 양식(워드·한글 서식)을 채워야 함 | 양식 파일을 `inbox/` 에 넣고 Claude 에게 \"이 양식의 칸을 `submit/ai_usage/` 의 내용으로 채워 줘\"라고 한다 |",
              "", "## 보내기 전에 확인할 것"]
    lines += [f"- {w}" for w in warn] or ["- 걸리는 것이 없다"]
    lines += [f"- {f}" for f in facts]
    lines += ["- 과제 안내문의 제출 형식(파일 이름, 받는 주소, 제목)과 맞는지 본다. `SUBMIT_RULES.md` 가 있으면 그것이 기준이다",
              "- 묶음에는 대화 전체가 들어 있다. 보내면 안 되는 개인 정보가 대화에 있었는지 떠올려 본다",
              "- 메일은 사람이 직접 보낸다"]
    (SUBMIT / "SUBMIT_LIST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
