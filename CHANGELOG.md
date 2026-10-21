# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- MCP → DSH sync no longer injects `sandbox-policy` (`mode: danger-full-access`)
  nor `approval` (`policy: never`) into the generated `cordis.patch.yml`.
  Those directives belong to the operator's DSH profile and are never relaxed
  by an MCP synchronization.
- `SIGABRT` (exit 134) in `TabReboot.confirm_and_start_reboot`: building a
  `QPixmap` without a `QApplication` instance triggered a Qt `qFatal` that
  aborted the whole pytest session. The icon is now only built when a
  `QApplication` exists, degrading to the native `QMessageBox` icon in
  headless mode.
- Absolute user paths removed from `tab_reboot.py`, `tab_radar.py` and
  `tab_api_manager.py`. The `SCRIPTS` directory is now resolved through
  `modules/_paths.py` (`$FLOYDIA_WORKSPACE` + upward search).

### Added
- `SECURITY.md`: private vulnerability reporting, threat model and contributor
  hardening rules.
- `CONTRIBUTING.md`: local setup, ground rules and pre-flight checklist.
- Issue templates (bug report, feature request) and a pull request template.
- `CHANGELOG.md`.
- `gitleaks` secret scanning as a dedicated CI job.

### Changed
- The DSH sync degrades gracefully in a clean clone: when the canonical
  workspace synchronizer is not present, the atomic export is used as the
  canonical patch instead of raising.
- `.env` parsing goes through the canonical `env_loader` when available and
  falls back to an equivalent local parser otherwise.
- Test fixtures for protected paths are now portable (`expanduser`) instead of
  embedding a developer machine layout.

### Removed
- Personal absolute paths from the public test suite.

## [0.1.0] - 2026-10-21

### Added
- FloydIA Suite 2.0 (F-Suite): AI Radar & model observatory, MCP Cockpit &
  Skills Studio, multi-account API Manager, SRE BleachBit Cleaner, SRE
  Governor, infrastructure/Reboot Hub and network diagnostics.
- Real 1-click propagation of MCP configuration to OpenCode, Hermes and the
  DeepSeek Harness, with atomic writes, `.bak` backups and an auditable write
  path.
- PyQt6 GUI with HiDPI support, bilingual diagnostic output and a design-web
  skills preset.
- 51-test pytest suite with a CI matrix on Python 3.10–3.12.

[Unreleased]: https://github.com/floydiamarkv-byte/floydia-suite-desktop/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/floydiamarkv-byte/floydia-suite-desktop/releases/tag/v0.1.0
