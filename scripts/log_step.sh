#!/usr/bin/env bash
# 단계 하나를 기록한다: AI_USAGE.md 에 한 줄 추가 + git 커밋.
# 사용: scripts/log_step.sh "<누가>" "<무엇을>"
#  예: scripts/log_step.sh "Claude Code (Opus 5.5)" "p1 SPEC, EDGE 작성"
#  예: scripts/log_step.sh "사람" "p1 D2 결정: A 선택"
# 여러 대화창에서 동시에 불러도 되도록 잠금을 건다.
#
# "누가"가 "사람"으로 시작하면 사람이 한 일만 커밋한다(AI_USAGE.md, DECISIONS.md, HUMAN_OK.txt).
# AI가 고친 코드와 테스트가 "사람"의 커밋에 섞이지 않게 하려는 것이다. 그래서 사람의 답은
# 그 답을 반영해 파일을 고치기 **전에** 기록한다.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
who="${1:?누가 했는지 적어 주세요}"
what="${2:?무엇을 했는지 적어 주세요}"
cd "$ROOT" || exit 1
mkdir -p logs

exec 9> logs/.log_step.lock
flock -w 30 9 || { echo "잠금을 얻지 못했습니다. 잠시 뒤 다시 하세요."; exit 1; }

now="$(date '+%Y-%m-%d %H:%M:%S')"
printf '| %s | %s | %s |\n' "$now" "$who" "$what" >> AI_USAGE.md

if [ ! -d .git ]; then
  git init -q
fi
ident=()
if [ -z "$(git config user.name)" ]; then
  ident=(-c user.name=cotest -c user.email=cotest@localhost)
fi
case "$who" in
  사람*)
    paths=(AI_USAGE.md)
    while IFS= read -r f; do
      [ -n "$f" ] && paths+=("$f")
    done < <(git ls-files -m -o --exclude-standard -- 'problems/*/DECISIONS.md' 'problems/*/tests/HUMAN_OK.txt')
    git add -- "${paths[@]}"
    git "${ident[@]}" commit -q -m "[$who] $what" -- "${paths[@]}" && echo "기록했습니다: $now $what (사람의 기록만 커밋)"
    ;;
  *)
    git add -A
    git "${ident[@]}" commit -q -m "[$who] $what" && echo "기록했습니다: $now $what"
    ;;
esac
