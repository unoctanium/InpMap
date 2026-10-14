---
description: Resume project work from docs/STATUS.md (run at the start of every session)
---

Resume work on this project following CLAUDE.md section 16:

1. Read `docs/STATUS.md`, then `docs/roadmap.md` and `CLAUDE.md` if they are not already in context.
2. Run `git status` and `git log --oneline -10` and compare them with `docs/STATUS.md`. If they disagree (uncommitted changes, unmentioned commits, a step left in progress), treat the previous session as interrupted: inspect the changes, run `.venv/bin/python -m pytest`, and correct `docs/STATUS.md`.
3. Report in a few lines: current position, last completed work, verification status, next step, and any pending user decisions or manual tests.
4. Continue with the next step unless I redirect.

$ARGUMENTS
