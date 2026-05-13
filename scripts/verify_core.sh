#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

echo "== CryptCore verification =="
echo "root: $ROOT"

echo
echo "== Import and CLI smoke =="
python -m compileall -q main.py core tools crypt tests
python main.py --help >/dev/null
python -m crypt --help >/dev/null

echo
echo "== Lint =="
python -m ruff check .

echo
echo "== Benchmark inventory =="
python main.py bench --bench-list

echo
echo "== Tests =="
if [ "${1:-}" = "--quick" ]; then
  python -m pytest \
    tests/test_registry.py \
    tests/test_runtime_defaults.py \
  tests/test_production_runtime.py \
  tests/test_permissions.py \
  tests/test_mcp.py \
  tests/test_skills.py \
  tests/test_task_state.py \
  tests/test_project_index.py \
  tests/test_bash_safety.py \
    tests/test_read_tools.py \
    tests/test_edit_file.py \
    tests/test_write_file.py
else
  python -m pytest
fi

echo
echo "CryptCore verification passed."
