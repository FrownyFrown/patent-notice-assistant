#!/bin/sh
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
    python3 -X utf8 ui/server.py
else
    printf '%s\n' 'Python 3.10 이상을 설치하세요: https://www.python.org/downloads/'
    exit 1
fi
