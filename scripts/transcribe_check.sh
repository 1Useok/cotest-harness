#!/usr/bin/env bash
# 옮겨 적기 확인. 사용: scripts/transcribe_check.sh p1 [견줄 글 파일]
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
exec python3 scripts/transcribe_check.py "$@"
