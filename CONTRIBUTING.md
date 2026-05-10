# Contributing

Crypt is meant to stay easy to fork. Keep changes small, testable, and aligned
with the existing module boundaries.

## Setup

```bash
python -m pip install -e ".[dev]"
python -m crypt doctor
```

## Development Loop

1. Read the owning module before editing it.
2. Keep one responsibility per file when adding runtime behavior.
3. Add or update focused tests for behavior changes.
4. Run the smallest relevant test first.
5. Run the release check before pushing.

## Checks

```bash
python -m ruff check .
python -m compileall -q main.py benchmarks core tools crypt tests
python -m pytest
python -m build
python -m pip_audit -r requirements.txt
```

## Style

- Prefer existing helpers over new abstractions.
- Keep model-visible tool behavior in `tools/`.
- Keep cross-tool policy in `core/`.
- Keep UI styling primitives in `core/ui_kit/`.
- Avoid broad refactors unless they remove real complexity.
- Do not commit generated caches, build output, local auth, or traces.

## Release Checklist

- `ruff` passes.
- Tests pass with coverage gate.
- `python -m crypt doctor` passes locally.
- Wheel builds and installs cleanly.
- Runtime dependencies pass `pip-audit`.
- Secret scan finds no live credentials.
- README and docs describe any new user-facing behavior.
