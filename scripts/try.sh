#!/usr/bin/env bash
# 입력 하나를 제출 코드와 독립 구현에 넣어 출력을 나란히 본다. (사람의 "이러면 어떻게 되지?"를 바로 확인)
# 사용: scripts/try.sh p1 < 입력파일      또는      scripts/try.sh p1 입력파일
# 출력은 problems/p1/probe/ 에 번호를 붙여 남긴다.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
name="${1:?문제 이름 (예: p1)}"
pdir="$ROOT/problems/$name"
[ -f "$pdir/$name.cpp" ] || { echo "제출 파일이 없습니다: $pdir/$name.cpp"; exit 2; }
mkdir -p "$pdir/build" "$pdir/probe"
n=1; while [ -e "$pdir/probe/$(printf '%02d' "$n").in" ]; do n=$((n + 1)); done
base="$pdir/probe/$(printf '%02d' "$n")"
if [ $# -ge 2 ]; then cat "$2" > "$base.in"; else cat > "$base.in"; fi

g++ -std=c++20 -O2 -o "$pdir/build/try_main" "$pdir/$name.cpp" || { echo "제출 코드가 컴파일되지 않습니다"; exit 1; }
timeout 5 "$pdir/build/try_main" < "$base.in" > "$base.main.out"; rc1=$?
echo "== 입력 ($base.in)"; cat "$base.in"
echo "== 제출 코드의 출력 (종료 코드 $rc1)"; cat "$base.main.out"
if [ -f "$pdir/alt.cpp" ] && g++ -std=c++20 -O2 -o "$pdir/build/try_alt" "$pdir/alt.cpp" 2>/dev/null; then
  timeout 5 "$pdir/build/try_alt" < "$base.in" > "$base.alt.out"; rc2=$?
  if cmp -s "$base.main.out" "$base.alt.out"; then
    echo "== 독립 구현의 출력: 같다"
  else
    echo "== 독립 구현의 출력: 다르다 (종료 코드 $rc2)"; cat "$base.alt.out"
  fi
else
  echo "== 독립 구현: 없음"
fi
