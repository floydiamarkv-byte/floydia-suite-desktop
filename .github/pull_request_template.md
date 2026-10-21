## What does this PR change?

<!-- One or two sentences. Link the issue it closes: Closes #123 -->

## Type

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / cleanup
- [ ] Docs / CI / packaging

## Checklist

- [ ] `QT_QPA_PLATFORM=offscreen python3 -m pytest tests/` passes (exit 0).
- [ ] New behavior is covered by a test.
- [ ] No absolute user paths (`$HOME`, workspace dirs) were added; use `modules/_paths.py`.
- [ ] No credentials, tokens or personal data appear in the diff.
- [ ] No security guard was relaxed (sandbox/approval policy, protected-path allowlist).
- [ ] Commit messages follow Conventional Commits.

## Risk and rollback

<!--
What breaks if this is wrong? How do you revert it?
Note any config migration, write path or packaging impact.
-->
