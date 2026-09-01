# AI Collaboration Rules

1. Read `AI_CONTEXT.md` before working.
2. Read `AI_TASKS.md` before modifying files.
3. Check `AI_CHANGES.md` for recent work.
4. Read `AI_CONTRACTS.md` before creating or changing a cross-module API.
5. Check `git status` before editing.
6. Do not modify files owned by another active task unless the dependency requires it and the owner is informed.
7. Do not rewrite unrelated systems.
8. Prefer small, scoped changes.
9. Preserve backward compatibility unless the task explicitly changes behavior.
10. Update `AI_CHANGES.md` when finishing.
11. Update the task status when finishing.
12. Run relevant tests/build checks before marking work complete.
13. Document timing-sensitive, path-sensitive, or platform-specific details.
14. Integrate with an existing subsystem instead of duplicating it.
15. If another feature needs shared functionality, expose a clean contract rather than coupling directly to implementation details.

## Merge-conflict prevention

Claim files in `AI_TASKS.md` before editing. Keep changes narrowly scoped, avoid formatting-only rewrites, and use separate branches or worktrees for parallel agents whenever possible.
