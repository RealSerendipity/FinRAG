# Project Rules — finrag

These rules exist because the previous attempt (`rag-copilot`) drowned in
premature abstraction. They are non-negotiable until proven harmful by a
concrete need that the current code cannot accommodate.

## 1. No premature abstraction
- No `base/factory/providers/registry/discovery` triplets.
- Multi-provider switching is implemented as **single-file `if/elif` dispatch**.
  Split a file only when one provider's branch is genuinely getting unwieldy
  (rule of thumb: the file exceeds ~400 lines or one branch needs > 5 helpers).
- No abstract base classes "just in case". Add an interface only when there is
  a *second concrete implementation* that needs it — never before.
- No `domain/` plug-in registry. The current domain is financial filings;
  domain-specific code lives flat under `src/financial/`. New domains are
  handled by *forking + editing prompts*, not by abstraction.

## 2. Eval-driven changes
- Any change to retrieval, prompt, ranker, or agent loop must be followed by
  re-running `eval/run_eval.py` and committing the diff in metrics.
- Commit messages for such changes carry a one-line metric delta, e.g.
  `Wave 3a: parent-doc chunking — recall@10 0.62 → 0.71, faithfulness 0.81 → 0.84`.

## 3. Flat structure first
- Default to one file per concern. Add a subpackage only when ≥ 3 modules
  collaborate around a clearly named concept.
- `src/` mirrors the data flow: `ingest → retrieve → rag → agent → api/ui`.

## 4. No documentation sprawl
- The only sanctioned narrative documents are `README.md` and `PROJECT_RULES.md`.
- Wave-level write-ups go into `eval/reports/` as timestamped Markdown — these
  are evidence files, not prose.
- Do not create per-feature design docs. Code + git log + eval report should
  be enough to reconstruct intent.

## 5. Code budget
- Application code (everything under `src/`) stays under **3 000 lines**
  through Wave 5. Crossing that line is a strong signal of overengineering;
  refactor towards subtraction before continuing.

## 6. Comments
- Default to no comments. Add one only when the *why* is non-obvious and would
  surprise a reader (a workaround, an invariant, a constraint from an external
  API, etc.). Comments are in English.

## 7. Configuration
- Runtime knobs live in environment variables loaded via `.env`.
- Default values live next to the code that consumes them, not in a giant
  config object.

## 8. Tests
- Each Wave ends with `pytest` green.
- Tests that require network / API keys must `skip` cleanly when the key is
  absent — they never fail because the developer didn't configure the
  environment.
