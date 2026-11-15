#!/usr/bin/env bash
# 문제 폴더를 만든다. 사용: scripts/new_problem.sh p1
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
name="${1:?문제 이름을 주세요 (예: p1)}"
dir="$ROOT/problems/$name"
if [ -e "$dir" ]; then
  echo "이미 있습니다: $dir"
  exit 1
fi
mkdir -p "$dir/tests"
cp "$ROOT/templates/main.cpp" "$dir/$name.cpp"
cp "$ROOT/templates/gen.py" "$dir/gen.py"
cp "$ROOT/templates/check.py" "$dir/check.py"
: > "$dir/PROBLEM.md"
echo "만들었습니다: $dir"
echo "문제 원문을 $dir/PROBLEM.md 에 그대로 붙여 넣으세요."
