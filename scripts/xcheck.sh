#!/usr/bin/env bash
# 정답 사례 교차 확인의 상태를 본다. 사용: scripts/xcheck.sh status p1
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
exec python3 scripts/xcheck.py "$@"
