# Contributing to nostos

Thanks for considering a contribution. This guide covers the dev loop end to end: clone, set up, test, lint, type-check, open a PR.

## Code of Conduct

Participation in this project is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). By contributing, you agree to abide by it.

## Security issues

Please **do not** file public GitHub issues for security vulnerabilities. See [SECURITY.md](SECURITY.md) for the private reporting channel.

## Local dev setup

nostos is a pure-Python project with a single required dependency (`argcomplete`). Python 3.10+ and git are required.

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/nostos.git
cd nostos

# (recommended) Isolated venv
python -m venv .venv
source .venv/bin/activate            # Unix
# .venv\Scripts\activate            # Windows PowerShell

# Install in editable mode + test / lint / type-check tools
pip install -e .
pip install ruff mypy
```

## Running the tests

Tests are written with `unittest` and are safe to run offline (network-touching paths are mocked).

```bash
# Full suite
python -m unittest discover -s tests

# One module
python -m unittest tests.test_portable -v

# One test method
python -m unittest tests.test_portable.TestImportBundle.test_merge_adds_missing_repos -v
```

The suite is 469+ tests and typically runs in under 15 seconds.

## Linting and type-checking

The CI pipeline runs ruff and mypy. Please run them locally before pushing so the PR lands green.

```bash
ruff check core/ nostos.py tests/
mypy core/ nostos.py
```

Configuration for both tools is in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`).

## Smoke-test the CLI from source

Without installing:

```bash
python nostos.py --version
python nostos.py --help
python nostos.py pull --dry-run /path/to/scratch
```

## Commit style

- One logical change per commit.
- First line: imperative, `<=72` characters, prefixed with the area when helpful (`pull:`, `portable:`, `docs:`, `ci:`).
- Empty line, then a body explaining *why* the change was made. Describe the observed behaviour before and after if it's a fix. Link issues or releases where relevant.
- Never mention AI / Claude / Copilot / Codex in commit messages, PR descriptions, code comments, or commit trailers. This is a project-wide policy.
- Never add `Co-Authored-By:` trailers unless a human co-author actually participated.

## Pull requests

1. Fork and branch off `master`. Name your branch after the change: `portable/schema-v3`, `fix/clone-timeout-on-windows`.
2. Keep PRs scoped. If a PR mixes unrelated changes, it will be asked to split.
3. Include tests for new behaviour and regression tests for fixes.
4. Update [CHANGELOG.md](CHANGELOG.md) under the `[Unreleased]` section.
5. Update the README and `docs/` if you change user-visible behaviour.
6. Run the local lint / mypy / test loop before pushing.
7. Open the PR against `master`. CI runs on push and pull_request; all three jobs (lint, type-check, test matrix) must be green.

## Release process (maintainer reference)

1. Merge all PRs for the release onto `master`.
2. Move the `[Unreleased]` entries in CHANGELOG.md under a new versioned heading. Update the compare links at the bottom of the file.
3. Bump `VERSION` and the badge in README.md to match.
4. Commit: `Release vX.Y.Z`.
5. `git tag -a vX.Y.Z -m "..."` and `git push origin vX.Y.Z`. The tag push triggers the PyPI publish workflow automatically.
6. Create the GitHub release from the tag with notes lifted from CHANGELOG.md.
7. Verify the new version appears on PyPI and TestPyPI, then verify `nostos update --check` reports it.

## Design principles

In descending order of priority:

1. **Opsec.** Anything that can make a network call is gated by explicit configuration. Default-off is preferred over default-on.
2. **Local-first.** The metadata index, config, logs, and state all live on the operator's machine. No telemetry.
3. **Cross-OS parity.** Linux, macOS, and Windows get the same feature set. Native Windows (not WSL) is a first-class target.
4. **Small dependency surface.** One runtime dep (`argcomplete`). Any new dep needs explicit justification in the PR.
5. **Clear exit codes.** `0` on success, `1` on any failure. No partial-success exit codes.
6. **Readable code before clever code.** Type hints everywhere; functions do one thing.

When a PR trades against any of these, call it out explicitly in the description.
