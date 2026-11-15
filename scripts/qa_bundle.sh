#!/usr/bin/env bash
# 파일을 직접 읽지 못하는 검토자(웹 대화창)에게 줄 묶음을 만든다.
# 원본 대화(logs/raw), 지난 실행(runs), 다른 검토자의 보고서는 넣지 않는다.
#   qa/_bundle/cotest_review.txt : 규칙, 절차, 스크립트, 리허설의 핵심 문서를 한 파일로 이은 것
#   qa/_bundle/cotest_review.zip : git 이 관리하는 파일 전체(위의 것 제외)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 - <<'PY'
import subprocess, zipfile, pathlib, fnmatch
out = pathlib.Path("qa/_bundle"); out.mkdir(parents=True, exist_ok=True)
files = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()
files = [f for f in files if pathlib.Path(f).is_file()
         and not f.startswith(("runs/", "qa/", "logs/raw/")) and "/build/" not in f]
with zipfile.ZipFile(out / "cotest_review.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(f)
core = ["HARNESS_QA_BRIEF.md", "README.md", "HARNESS.md", "AGENTS.md", "CLAUDE.md", ".claude/*", "templates/*",
        "prompts/*", "CHECKLIST.md", "knowledge/*", "models.conf", "scripts/*", "SUBMIT_RULES.md", "AI_USAGE.md",
        "inbox/INDEX.md", "logs/TIMELINE.tsv", "submit/SUBMIT_LIST.md", "submit/*.cpp",
        "problems/*/PROBLEM.md", "problems/*/SPEC.md", "problems/*/EDGE.md", "problems/*/DECISIONS.md",
        "problems/*/REPORT.md", "problems/*/VERIFY.txt", "problems/*/REVIEW_codex.md", "problems/*/MUTANTS.txt"]
text_ext = {".md", ".sh", ".py", ".json", ".txt", ".tsv", ".cpp", ".conf", ""}
picked = []
for pat in core:
    for f in files:
        if fnmatch.fnmatch(f, pat) and f not in picked and pathlib.Path(f).suffix in text_ext:
            picked.append(f)
with open(out / "cotest_review.txt", "w", encoding="utf-8") as w:
    w.write("이 파일은 cotest 폴더의 문서와 스크립트를 한 파일로 이은 것이다. 구분선의 경로가 원래 파일 이름이다.\n")
    w.write("차례:\n" + "\n".join(f"- {f}" for f in picked) + "\n")
    for f in picked:
        try:
            body = pathlib.Path(f).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        w.write(f"\n\n===== FILE: {f} =====\n{body}")
for p in sorted(out.iterdir()):
    print(f"{p}  {p.stat().st_size / 1024:.0f} KB")
print(f"한 파일로 이은 것: {len(picked)}개, zip: {len(files)}개")
PY
echo "윈도우에서 여는 경로: \\\\wsl.localhost\\${WSL_DISTRO_NAME:-Ubuntu-24.04}\\${ROOT#/}\\qa\\_bundle" | sed 's#/#\\#g'
