#!/usr/bin/env bash
# 제출 직전 관문. 사용: scripts/final_gate.sh p1
# verify 와 같은 검사를 처음부터 다시 돌리고, 통과하면 submit/p1.cpp 로 복사한다.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/verify.py" "$@" --final
