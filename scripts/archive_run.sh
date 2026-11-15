#!/usr/bin/env bash
# 연습 한 판을 치운다: problems/, submit/, inbox/, logs/ 의 내용을 runs/<이름>/ 으로 옮긴다.
# 다음 판(또는 실전)이 빈 상태에서 시작한다. 타이머도 꺼진다.
# 사용: scripts/archive_run.sh 1113_pr2
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
name="${1:?이름을 주세요 (예: 1113_pr2)}"
dest="$ROOT/runs/$name"
[ -e "$dest" ] && { echo "이미 있습니다: $dest"; exit 1; }
mkdir -p "$dest"
# 폴더 맨 위에 내보낸 대화 기록이 있으면 먼저 logs/ 로 옮긴다
python3 "$ROOT/scripts/collect_logs.py" --quiet || true
for d in problems submit inbox logs; do
  mkdir -p "$dest/$d" "$ROOT/$d"
  find "$ROOT/$d" -mindepth 1 -maxdepth 1 ! -name '.log_step.lock' -exec mv {} "$dest/$d/" \;
done
# limits.conf(안내문의 시간·메모리 제한)도 옮긴다. 다음 판이 지난 실행의 제한으로 검증하지 않게 한다
for f in AI_USAGE.md AI_GUIDELINE.md SUBMIT_RULES.md BOARD.md limits.conf; do
  [ -f "$ROOT/$f" ] && mv "$ROOT/$f" "$dest/$f"
done
# AI 사용 내역은 빈 양식에서 다시 시작한다(지난 판의 것은 위에서 옮겼다)
cp "$ROOT/templates/AI_USAGE.md" "$ROOT/AI_USAGE.md"
echo "옮겼습니다: $dest"
echo "problems/, submit/, inbox/, logs/ 가 비었고 AI_USAGE.md 는 빈 양식입니다. 타이머도 꺼졌습니다."
