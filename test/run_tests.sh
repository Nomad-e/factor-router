#!/usr/bin/env bash
# Na raiz do repo: testes unitários + coverage HTML + relatório em test/result/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p test/result
uv run coverage run -m unittest discover -s test -v 2>&1 | tee test/result/unittest_output.txt
uv run coverage html
uv run coverage report -m > test/result/coverage_report.txt || true
uv run python test/make_report.py
