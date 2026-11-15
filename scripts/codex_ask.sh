#!/usr/bin/env bash
# Codex(다른 회사 모델)에게 독립된 일을 맡긴다.
# 사용:
#   scripts/codex_ask.sh ambig  p1   # 문제만 보고 애매한 점과 자기 선택을 적는다 -> AMBIG_codex.md
#   scripts/codex_ask.sh alt    p1   # 문제와 출력 규칙만 보고 독립 구현을 쓴다   -> alt.cpp
#   scripts/codex_ask.sh review p1   # 제출 코드를 명세·실무 함정과 대조해 읽는다 -> REVIEW_codex.md
#   scripts/codex_ask.sh cases  p1   # 정답 사례의 입력만 보고 출력을 따로 구한다     -> xcheck/*.out (정답 사례 교차 확인)
#                                    #   이미 확인한 사례는 건너뛴다. 전부 다시 하려면 XCHECK_ALL=1
#
# 독립성을 지키려고 빈 임시 폴더에 필요한 파일만 복사해서 실행한다.
# - alt 를 쓰는 쪽은 제출 코드(pN.cpp)를 볼 수 없다.
# - alt 에게는 DECISIONS.md 의 "## 구현 메모" 절을 지우고 준다. 두 구현이 같은 방법을 쓰면 같은 곳에서 함께 틀린다.
# - cases 를 하는 쪽은 기대 출력(tests/*.out)도 제출 코드도 볼 수 없다. 입력과 원문, 결정 기록만 본다.
# 모델과 강도: CODEX_MODEL (기본 gpt-6.1-sol), CODEX_EFFORT (기본 high)
#   우선순위는 환경 변수 > 작업 폴더의 models.conf > 기본값.
#   models.conf 는 `CODEX_MODEL=...`, `CODEX_EFFORT=...`, `CODEX_TIMEOUT=...` 줄만 읽는다(# 뒤는 설명). source 하지 않는다.
#   CODEX_TIMEOUT 은 호출 하나의 제한 시간(초, 기본 900). 강도를 높이면 오래 걸리므로 scripts/models.sh 가 함께 늘린다.
# review 가 시간 초과나 오류로 끝나도 REVIEW_codex.md 가 비어 있지 않으면 부분 결과로 받는다("OK(부분):", 종료 코드 0).
# 종료 코드: 0 성공, 3 Codex 없음, 4 Codex 실패(종료 코드가 0이 아니거나 결과물이 없거나 컴파일되지 않음)
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:?ambig | alt | review | cases}"
arg="${2:?문제 이름 (예: p1)}"
if [ -d "$arg" ]; then pdir="$(cd "$arg" && pwd)"; else pdir="$ROOT/problems/$arg"; fi
[ -d "$pdir" ] || { echo "문제 폴더가 없습니다: $pdir"; exit 2; }
name="$(basename "$pdir")"

# Codex 실행 파일 찾기: CODEX_BIN > VS Code 확장에 든 것 > PATH 의 리눅스용
codex="${CODEX_BIN:-}"
if [ -z "$codex" ]; then
  codex="$(ls -d "$HOME"/.vscode-server/extensions/openai.chatgpt-*-linux-x64/bin/linux-x86_64/codex 2>/dev/null | sort -V | tail -1)"
fi
if [ -z "$codex" ]; then
  cand="$(command -v codex 2>/dev/null || true)"
  case "$cand" in /mnt/*|"") ;; *) codex="$cand" ;; esac
fi
[ -n "$codex" ] && [ -x "$codex" ] || { echo "CODEX_NOT_FOUND: Codex 실행 파일을 찾지 못했습니다. 대비책(새 Claude 에이전트)을 쓰세요."; exit 3; }

# models.conf 에서 KEY=VALUE 하나를 읽는다. 마지막 줄이 이긴다. 영문·숫자·.-_: 만 받는다.
conf_get() {
  [ -f "$ROOT/models.conf" ] || return 0
  local v
  v="$(tr -d '\r' < "$ROOT/models.conf" | sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" \
       | sed 's/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"\(.*\)"$/\1/' | tail -1)"
  case "$v" in
    "") ;;
    *[!A-Za-z0-9._:-]*) echo "models.conf 의 $1 값이 이상해서 쓰지 않습니다: $v" >&2 ;;
    *) printf '%s' "$v" ;;
  esac
}
model="${CODEX_MODEL:-$(conf_get CODEX_MODEL)}"
model="${model:-gpt-6.1-sol}"
effort="${CODEX_EFFORT:-$(conf_get CODEX_EFFORT)}"
effort="${effort:-high}"
work="$(mktemp -d)"
mkdir -p "$ROOT/logs"
marker="$ROOT/logs/.running_${mode}_${name}"
trap 'rm -rf "$work"; rm -f "$marker"' EXIT
: > "$marker"
log="$ROOT/logs/codex_${mode}_${name}_$(date '+%m%d_%H%M%S').log"
ctimeout="${CODEX_TIMEOUT:-$(conf_get CODEX_TIMEOUT)}"
case "$ctimeout" in ""|*[!0-9]*) ctimeout=900 ;; esac

copy_if() { for f in "$@"; do [ -f "$pdir/$f" ] && cp "$pdir/$f" "$work/"; done; }
# DECISIONS.md 에서 "## 구현 메모" 절(다음 "## " 전까지)을 뺀다
copy_decisions_without_impl() {
  [ -f "$pdir/DECISIONS.md" ] || return 0
  awk '/^## /{skip = ($0 ~ /^## 구현 메모/)} !skip' "$pdir/DECISIONS.md" > "$work/DECISIONS.md"
}

case "$mode" in
  ambig)  copy_if PROBLEM.md;                                        out=AMBIG_codex.md ;;
  alt)    copy_if PROBLEM.md SPEC.md; copy_decisions_without_impl
          # 큰 입력을 어떤 모양으로 만들지(느린 구현이 드러나는 입력)만 준다. 속도 사전의 나머지는 주지 않는다.
          [ -f "$ROOT/knowledge/PERF.md" ] && awk '/^## /{keep = ($0 ~ /^## Z\. /)} keep' "$ROOT/knowledge/PERF.md" > "$work/BIG_SHAPES.md"
          [ -s "$work/BIG_SHAPES.md" ] || rm -f "$work/BIG_SHAPES.md"
          out=alt.cpp ;;
  review) copy_if PROBLEM.md SPEC.md EDGE.md DECISIONS.md "$name.cpp"
          [ -f "$ROOT/knowledge/TRAPS.md" ] && cp "$ROOT/knowledge/TRAPS.md" "$work/TRAPS.md"
          [ -f "$ROOT/knowledge/PERF.md" ] && cp "$ROOT/knowledge/PERF.md" "$work/PERF.md"
          out=REVIEW_codex.md ;;
  cases)  copy_if PROBLEM.md; copy_decisions_without_impl
          python3 "$ROOT/scripts/xcheck.py" prepare "$pdir" "$work" ${XCHECK_ALL:+--all} \
            || { echo "OK: 새로 확인할 정답 사례가 없습니다 ($(python3 "$ROOT/scripts/xcheck.py" status "$pdir" | head -1))"; exit 0; }
          out=XCHECK_NOTES.md ;;
  *) echo "모드는 ambig, alt, review, cases 중 하나입니다"; exit 2 ;;
esac
sandbox=workspace-write
[ -f "$work/PROBLEM.md" ] || { echo "PROBLEM.md 가 없습니다"; exit 2; }

prompt="$(sed "s/{NAME}/$name/g" "$ROOT/prompts/$mode.md")"

{
  echo "# codex_ask $mode $name"
  echo "# 시각: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "# 모델: $model, 강도: $effort, 실행 파일: $("$codex" --version 2>/dev/null)"
  echo "# 보여 준 파일: $(ls "$work" | tr '\n' ' ')"
  echo "# ---- 프롬프트 ----"
  echo "$prompt"
  echo "# ---- 출력 ----"
} > "$log"

timeout "$ctimeout" "$codex" exec \
  -m "$model" -c "model_reasoning_effort=\"$effort\"" \
  --sandbox "$sandbox" --skip-git-repo-check -C "$work" \
  "$prompt" >> "$log" 2>&1
rc=$?
echo "# ---- 종료 코드: $rc ($(date '+%H:%M:%S')) ----" >> "$log"

fail() {
  # 불완전한 결과물은 성공한 결과물을 덮어쓰지 않는다. 따로 남긴다.
  [ -f "$work/$out" ] && cp "$work/$out" "$pdir/$out.failed"
  echo "CODEX_FAILED: $1 (종료 코드 $rc). 기록: $log"
  tail -5 "$log"
  exit 4
}

partial=""
if [ "$mode" = review ] && [ "$rc" -ne 0 ] && [ -s "$work/$out" ]; then
  # 리뷰는 찾은 것부터 파일에 적게 했다. 끊겨도 쓴 만큼은 받는다.
  if [ "$rc" -eq 124 ]; then why="시간 제한(${ctimeout}초)에 걸려"; else why="오류(종료 코드 $rc)로"; fi
  { echo "> 부분 결과: 검토가 $why 중간에 끊겼다. 아래는 끊기기 전까지 쓴 것이다."; echo; cat "$work/$out"; } > "$work/$out.part"
  mv "$work/$out.part" "$work/$out"
  partial=1
  echo "# 부분 결과로 받음 ($why 끊김)" >> "$log"
fi
[ "$rc" -eq 0 ] || [ -n "$partial" ] || fail "Codex 가 오류로 끝났습니다"
[ -s "$work/$out" ] || fail "$out 이 만들어지지 않았거나 비어 있습니다"
if [ "$mode" = alt ]; then
  g++ -std=c++20 -O2 -o "$work/alt_check" "$work/alt.cpp" > "$work/alt_build.txt" 2>&1 \
    || { head -5 "$work/alt_build.txt"; fail "alt.cpp 가 컴파일되지 않습니다"; }
fi
if [ "$mode" = cases ]; then
  ls "$work"/xcheck/*.out > /dev/null 2>&1 || fail "xcheck/ 에 출력 파일이 하나도 없습니다"
fi

# 이전 결과가 있으면 회차 번호를 붙여 보관한다 (git 에 남는다)
if [ -f "$pdir/$out" ]; then
  n=1; while [ -e "$pdir/history/${out%.*}_r$n.${out##*.}" ]; do n=$((n + 1)); done
  mkdir -p "$pdir/history"
  cp "$pdir/$out" "$pdir/history/${out%.*}_r$n.${out##*.}"
  [ "$mode" = alt ] && [ -f "$pdir/ALT_NOTES.md" ] && cp "$pdir/ALT_NOTES.md" "$pdir/history/ALT_NOTES_r$n.md"
fi
[ -f "$work/ALT_NOTES.md" ] && cp "$work/ALT_NOTES.md" "$pdir/ALT_NOTES.md"
cp "$work/$out" "$pdir/$out"
extra=""
if [ "$mode" = alt ]; then
  # 두 번째 입력 생성기: 답안도 gen.py 도 보지 않은 쪽이 쓴 것. 돌아가는 것만 받는다.
  if [ -s "$work/gen2.py" ]; then
    if (cd "$work" && timeout 20 python3 -c "
import importlib.util, random
s = importlib.util.spec_from_file_location('gen2', 'gen2.py'); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
for seed in range(1, 21):
    x = m.gen(random.Random(seed)); assert isinstance(x, (str, bytes)) and len(x) < 200000
") > "$work/gen2_check.txt" 2>&1; then
      cp "$work/gen2.py" "$pdir/gen2.py"; extra=" + gen2.py"
    else
      cp "$work/gen2.py" "$pdir/gen2.py.failed"
      extra=" (gen2.py 는 돌아가지 않아 받지 않았다: $(tail -1 "$work/gen2_check.txt" | cut -c1-100))"
    fi
  else
    extra=" (gen2.py 는 오지 않았다)"
  fi
fi
if [ "$mode" = cases ]; then
  extra=" / $(python3 "$ROOT/scripts/xcheck.py" ingest "$pdir" "$work" "$model")"
fi
# 기록(log_step)의 "누가"에는 여기 찍힌 모델 이름을 그대로 쓴다.
if [ -n "$partial" ]; then
  echo "OK(부분): $pdir/$out (끊기기 전까지 쓴 것. 빠진 검토가 있을 수 있다) (모델: $model, 기록: $log)"
  exit 0
fi
echo "OK: $pdir/$out$extra (모델: $model, 기록: $log)"
exit 0
