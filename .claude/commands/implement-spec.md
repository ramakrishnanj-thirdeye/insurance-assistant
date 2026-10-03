---
description: Implement one spec end to end — plan, tests from acceptance criteria, code, gates
argument-hint: <spec path, e.g. specs/04-retrieval.md>
---
Implement the spec at `$ARGUMENTS` following CLAUDE.md.

1. Read `$ARGUMENTS`, every ADR and config file it names, and the interfaces of specs it depends on.
   Check `tasks.md` for the milestone and confirm earlier gates are green (`make test`).
2. Produce a plan and stop for my approval:
   - files to create or change, with one line each;
   - a table mapping every acceptance criterion (AC-NN-MM) to the test(s) that will prove it;
   - anything ambiguous in the spec, with your proposed resolution;
   - any interface change that would affect another spec (avoid unless essential).
3. After approval: write the failing tests first, named `test_AC_NN_MM_<what>`, then implement until they pass.
   Use the reference files in `specs/reference/` where the spec points to them; do not import the prototype.
4. Run `make lint test`. If the spec lists eval hooks, run `make eval-fast` and report the metrics it moves.
5. Tick the satisfied criteria in the spec (`- [x]`), update `tasks.md`, and summarise: what changed,
   test results, eval deltas, open questions. Propose a commit message `feat(spec-NN): ...`.

Never relax an acceptance criterion or a hard rule to make a test pass; flag it instead.
