---
description: Bring docs/STATUS.md fully up to date so a new session can continue seamlessly
---

Prepare a clean handoff following CLAUDE.md section 17:

1. Run `git status`, `git log --oneline -10`, and the test suite (`.venv/bin/python -m pytest`).
2. Update `docs/STATUS.md`: current position, next steps, new decisions with reasons, verification status (only actually observed results), uncommitted work, open questions and pending manual tests, and a dated session-log entry for this session. Rewrite stale sections.
3. Show me a short summary of what changed in `docs/STATUS.md` and propose a commit if there is completed, test-passing work. Do not commit unless I confirm.

$ARGUMENTS
