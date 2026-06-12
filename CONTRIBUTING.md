# Contributing to Cortex

Thanks for considering a contribution. Cortex is a persistent memory
engine built on **26 biological mechanisms** with **45 academic citations**
backing the algorithms. Every change is held to that bar.

---

## What this project is

A Python 3.10+ MCP server with **49 tools, 9 automatic hooks**, persisting
to PostgreSQL + pgvector. Implements rate-distortion forgetting,
predictive-coding write gating, retrieval-induced reconsolidation, pattern
separation, sleep-cycle consolidation, emotional-valence weighting, and
more. See [README](README.md) for the full architecture and benchmark
results (LongMemEval Recall@10 = 98.4%, LoCoMo Recall@10 = 94.3%, BEAM-10M
+33.4% over the published baseline).

---

## Dev setup

**Prerequisites:** Pixi 0.70+ on `linux-64` or `osx-arm64`, Python 3.10+
through Pixi, PostgreSQL 17 + pgvector extension. Intel macOS and Linux ARM
contributors should use a matching remote runner or development container for
Pixi-backed work until the `tree-sitter-language-pack` wheel set covers the
full Python matrix.

```bash
git clone https://github.com/cdeust/Cortex.git
cd Cortex

# Install the default Python 3.12 development environment
pixi install

# Or use the setup script (handles PostgreSQL + pgvector + DB init)
bash scripts/setup.sh        # macOS / Linux

# Verify everything is wired
pixi run doctor

# Run tests (3,000+ tests across functional + benchmark suites)
pixi run test

# Run a benchmark
pixi run -- python benchmarks/longmemeval/run_benchmark.py --variant s
```

---

## Branching + workflow

- `main` is the integration branch.
- Branch naming: `feature/<short-slug>`, `fix/<short-slug>`, `docs/<short-slug>`, `mechanism/<name>` (for new biological mechanisms), `benchmark/<name>` (for new benchmark integrations).
- One mechanism per PR when adding new biological mechanisms.
- Conventional commit messages preferred.

---

## Adding a biological mechanism

Cortex's 26 mechanisms are not metaphors — each maps to a specific
neuroscience finding with a specific algorithmic implementation.
A new mechanism PR must include:

1. **Primary citation.** What published neuroscience or cognitive-science
   work motivates this mechanism? Include the paper's bibliographic
   reference in `docs/papers/science.md`.
2. **The mathematical form.** Equations or pseudocode showing the exact
   computation. If you're adapting an algorithm from the literature,
   call out the divergence and justify it.
3. **The biological grounding.** Which brain region / circuit / molecular
   pathway does this mirror? A one-paragraph mapping is required.
4. **Empirical validation.** A benchmark or unit test demonstrating the
   mechanism behaves as predicted. Quantitative claims need numbers.
5. **Ablation.** A test showing the system's behavior with the mechanism
   disabled, so its contribution is observable.

A mechanism PR without these five elements does not pass review.

---

## Modifying retrieval signals

Cortex fuses five retrieval signals (vector similarity, full-text search,
trigram matching, thermodynamic heat, recency) plus a cross-encoder
reranker. Changes here:

1. **Run the full benchmark suite.** LongMemEval, LoCoMo, BEAM at both
   100K and 10M scales. A regression on any of those is blocking unless
   explicitly justified.
2. **Document the delta.** A markdown row in `benchmarks/results.md`
   showing before/after MRR + Recall@10 per category.
3. **Cite the source.** If you're adding a new signal, reference the IR
   literature (BM25 → Robertson; pgvector HNSW → Malkov et al.; trigram
   → Lehmann; etc.).
4. **Preserve the 22MB embedding-model footprint.** Cortex runs entirely
   on the user's machine; bringing in a 1GB model is out of scope.

---

## Coding standards (excerpt)

Standard Python style (`ruff`, with `pyright` tracked as a visible baseline)
plus
project-specific rules:

- **No `Any`** in production code. Use `Protocol` or generic typing.
- **§8 Source discipline.** Every numeric constant ≥3 significant digits
  needs a `# source:` annotation.
- **No mutable default arguments.** No globals except for read-once
  configuration objects.
- **No bare `except:`.** Catch the specific exception you mean.
- **Type-check visible.** Run `pixi run typecheck` and attach the output when
  touching typed contracts. It remains a non-blocking CI baseline until the
  existing project-wide debt is paid down.
- **§4.1 File ≤500 lines, §4.2 function ≤50 lines.**

The full standard lives in
[zetetic coding standards](https://github.com/cdeust/zetetic-team-subagents/blob/main/rules/coding-standards.md).

---

## Testing

```bash
pixi run test                                      # full suite (3,000+ tests)
pixi run -- python -m pytest tests_py/shared          # pure utilities
pixi run -- python -m pytest tests_py/infrastructure  # I/O layer
pixi run -- python -m pytest -k locomo                # subset
pixi run -- python -m pytest -x --ff                  # stop on first fail, run failures first
pixi run typecheck                                 # visible baseline, currently non-blocking in CI
```

Tests run against a local PostgreSQL instance. CI provisions a fresh DB
per run.

---

## Adding an MCP tool

49 tools currently. Adding a new one:

1. **Define the JSON schema** in the tool's module-level decorator.
2. **Implement the handler** following the `BaseTool` protocol.
3. **Add to the tool registry** at the canonical registration site.
4. **Document in `docs/MCP-TOOLS.md`** with the tool's purpose, inputs,
   outputs, and an example call.
5. **Add a unit test** for the tool's contract.
6. **Add an integration test** if the tool touches the database.

---

## What NOT to do

- Don't claim a benchmark improvement without committing the actual
  benchmark output. Numbers without a reproducible run are unverified.
- Don't add a mechanism without academic grounding. "It seems brain-like"
  is not a citation.
- Don't introduce a heavy ML model dependency that breaks the
  runs-on-your-machine guarantee.
- Don't hide new type errors. If `pixi run typecheck` still reports baseline
  debt, call out whether your change adds, removes, or leaves the count
  unchanged.
- Don't relax a test that fails on your branch. The test exists for a
  reason; understand the reason before changing it.

---

## Code of Conduct

This project follows [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

---

## Reporting security issues

See [`SECURITY.md`](SECURITY.md). The memory engine handles potentially
sensitive user data (PII in conversation transcripts); any data-exposure
or injection issue is high-priority. The `pre-tool-secret-shield` hook
already gates `.env`, `.aws/credentials`, `*.pem`, `*.key`, and shell
history — but new code paths that touch the filesystem need similar
review.

---

## License

MIT. Contributions are licensed under the same. See [`LICENSE`](LICENSE).
The neuroscience and IR algorithms remain attributable to the cited
sources; the MIT license covers this implementation.
