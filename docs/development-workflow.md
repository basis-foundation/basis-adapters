# Development Workflow

How to work on `basis-adapters` day to day.

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The editable install (`-e`) means changes under `src/` take effect immediately
without reinstalling. Dev dependencies include pytest, ruff, mypy, and jsonschema
(used by the schema/example validation tests).

## Quality Gates

Run all four before opening a PR; CI-equivalent locally:

```bash
python -m pytest          # full test suite
ruff check .              # lint
ruff format --check .     # formatting (use `ruff format .` to fix)
mypy src                  # strict type checking
```

All four must pass. There are no known-failing tests and no lint/type suppressions
to work around.

## Recommended Workflow

1. **Create a branch** off `main`: `git checkout -b feature/<short-description>`
   (see CONTRIBUTING.md for naming).
2. **Make focused changes.** One concern per branch. If a change touches a contract
   (models, normalized output shape, mapping validation), update the matching
   schema, examples, docs, and contract tests in the same branch.
3. **Run the quality gates** (all four commands above).
4. **Open a PR.** The PR template includes the checklist; fill it in honestly.

## Generated Files

Never commit generated artifacts. `.gitignore` already covers `__pycache__/`,
`*.pyc`, `.venv/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`,
`pytest-cache-files-*/`, `dist/`, and `*.egg-info/`.

Before committing, a quick sanity check:

```bash
git status --short        # nothing unexpected staged
git ls-files | grep -E "__pycache__|\.pyc$"   # should print nothing
```

If a generated file ever gets tracked, remove it from the index with
`git rm --cached <path>` (the file stays on disk) and verify `.gitignore` covers it.

## Stale Git Lock Files

If git refuses to run because of a leftover `.git/index.lock` (usually after an
interrupted operation), confirm no git process is actually running, then remove the
lock file: `rm .git/index.lock`. Do not delete anything else under `.git/`.

## Automation and Git Operations

Claude or other automation may prepare changes in a working tree, but must not run
`git commit` or `git push` unless Brandon explicitly asks. All commits, merges, and
pushes are performed manually by the maintainer after review.
