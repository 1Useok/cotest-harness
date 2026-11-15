#!/usr/bin/env bash
# AI 사용 내역을 여러 형식으로 바꾼다. 자세한 것은 scripts/usage_export.py 맨 위.
cd "$(dirname "$0")/.." || exit 1
exec python3 scripts/usage_export.py "$@"
