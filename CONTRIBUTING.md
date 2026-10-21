# Contributing to FloydIA Suite

Thanks for taking the time to contribute. This project is a PyQt6 desktop
command center for LLM fleets, MCP servers and agent-harness configuration.

## Quick Start

```bash
git clone https://github.com/floydiamarkv-byte/floydia-suite-desktop.git
cd floydia-suite-desktop
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/ -v
```

The suite must also run **headless** in CI: `QT_QPA_PLATFORM=offscreen` is
required for the test suite.

## Ground Rules

1. **One concern per PR.** Keep diffs small and reviewable.
2. **Tests are mandatory.** Any behavior change needs a test. The suite must
   stay green: `python3 -m pytest tests/` → exit code 0.
3. **No absolute user paths.** Use `modules/_paths.py`
   (`ensure_scripts_on_path()` / `resolve_env_line()`) instead of hardcoding
   `$HOME` or workspace directories. CI enforces this.
4. **No secrets.** Never commit API keys. Reference key *names* only. The
   `gitleaks` pre-commit hook and CI job will fail the build otherwise.
5. **Do not relax security policy.** The MCP → DSH sync must not inject sandbox
   or approval directives; the cleaner must not weaken its protected-path
   allowlist. There are regression tests for both.
6. **Conventional commits.** `feat(scope): ...`, `fix(scope): ...`,
   `docs: ...`, `test: ...`, `refactor: ...` (the project is bilingual; the
   subject line may be in English or Spanish).
7. **Deterministic tests.** No sleeps as synchronization, no network calls, no
   dependency on the developer's machine layout.

## Reporting Bugs

Open an Issue with the template and include:

- version/commit and OS + Python version
- what you expected vs. what happened
- steps to reproduce (and logs with secrets redacted)
- for UI issues: a screenshot

## Security Issues

Do **not** open a public Issue. See [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
