# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x (main) | ✅ |
| < 0.1   | ❌ |

## Reporting a Vulnerability

Please **do not open a public Issue** for security problems.

Use **GitHub Private Vulnerability Reporting**:
<https://github.com/floydiamarkv-byte/floydia-suite-desktop/security/advisories/new>

Expected response window: **7 days**. If a report is confirmed, a fix is
released as a patch version and credited in `CHANGELOG.md` (unless you prefer
otherwise).

Please include: affected version/commit, reproduction steps, impact assessment
and, if possible, a minimal PoC.

## Threat Model

FloydIA Suite runs with local user privileges and touches security-sensitive
surfaces. The following are **in scope**:

- The MCP Cockpit writes agent-harness configuration files
  (`opencode.jsonc`, `hermes/config.yaml`, DSH `cordis.patch.yml`). A write
  path that injects permissive directives (sandbox / approval policy) is a
  **P0**.
- The API Manager propagates multi-provider API keys into agent configs.
  Leaking a key through logs, telemetry, exports or backups is a **P0**.
- The SRE Cleaner deletes files. Bypassing the protected-path allowlist
  (SSH keys, GPG, Bitwarden, browser extensions, `/etc`, `/usr`, `.git`,
  `memory-bank`) is a **P0**.
- Any code path that executes shell commands with unvalidated user input.

Out of scope: vulnerabilities in upstream dependencies (please report those
upstream) and issues in the operator's own network configuration.

## Security Controls in Place

- `gitleaks` secret scanning in CI and in the pre-commit hook
  (`.gitleaks.toml`).
- Atomic, lock-guarded writes (`fcntl.flock`) with automatic `.bak` backups.
- Credential sanitization (`sanitize_for_persistence`) before any persistence
  of telemetry, logs or reports.
- Protected-path allowlist with `realpath` resolution to close symlink bypass.
- Policy guard: the MCP → DSH sync must never inject sandbox or approval
  policy (`tests/test_audit_remediation.py::test_dsh_sync_does_not_inject_danger_policy`).
- No third-party analytics SDK: telemetry is stored locally only.

## Hardening Rules for Contributors

1. Never hardcode absolute paths of a user machine. Use `modules/_paths.py`
   (`$FLOYDIA_WORKSPACE` + upward search) so the project works in any clone.
2. Never read or print credential values; reference key **names** only.
3. Any new write to a harness config must go through the authorized,
   auditable write path with a `reason` trace.
4. New behavior needs a test. `python3 -m pytest tests/` must exit 0.
