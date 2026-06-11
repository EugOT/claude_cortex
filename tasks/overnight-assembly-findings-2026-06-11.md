# Overnight Paper Assembly — Findings & Blockers (2026-06-11)

Staged for review. **NOTHING sent.** No PDFs rebuilt for Paper 2. No outreach
dispatched. This memo is the deliverable that matters; read it before the diffs.

---

## TL;DR

The overnight compute chain finished (exit 0). Three of the planned runs
produced clean data; **two of them contradict Paper 2's central thesis**, and
one planned run (E2 subsample) failed on a bad CLI arg and produced nothing.

- ⚠️ **Paper 1 (context assembly)** — fresh crossover data *corroborates the
  thesis directionally*, BUT the fresh BEAM-10M temporal number (0.523) cannot be
  swapped for the paper's headline (0.471) without knowing which config produced
  0.471. Per your own guard ("prior config unknown → no improvement claim"),
  Paper 1 is **frozen on number-provenance**. NOT edited.
- 🛑 **Paper 2 (thermodynamic decay)** — fresh data **reverses** the load-bearing
  decay result. Frozen. Needs your adjudication before any submission. NOT edited.
- ⚠️ **E2 subsample sweep** — FAILED (`--benchmark beam` invalid; runner wants
  `beam-100K`). No subsample numbers exist. Do not cite any.

---

## 1. Paper 2 decay thesis — SIGN REVERSAL (submission blocker)

### What the committed paper claims (e4499a6, §6 `sec:decay-dose`, lines 596–620)
Source artefact cited: `decay_sweep/20260430T111134Z/` (a **2-point** sweep).

| λ_base | retrieval-proxy MRR | R@10 |
|---|---|---|
| 0.95 (decay on)  | **0.671** | **0.867** |
| 1.00 (decay off) | 0.399 | 0.567 |
| Δ (on − off) | **+0.272 (+68%)** | +0.300 |

Prose: *"the load-bearing evidence that decay is causal in the regime where
access history is heterogeneous."*

### What the fresh 6-point sweep measured tonight
Artefact: `decay_sweep/20260611T052523Z/` — BEAM-100K, 395 Qs, clean
`cortex_bench_papers` DB, **same `recall_memories()` code path**.

| λ_base | MRR | R@10 |
|---|---|---|
| 0.90  | 0.503 | 0.687 |
| 0.925 | 0.500 | 0.684 |
| 0.95 (decay on)  | 0.503 | 0.684 |
| 0.975 | 0.503 | 0.687 |
| 0.99  | 0.503 | 0.684 |
| **1.00 (decay off)** | **0.545** | **0.744** |

`analysis.json`: optimum_lambda = **1.0**, plateau ~0.503 across all λ<1.0
(`plateau_width: 0.0`, `slope_right: null`, `slope_left: 4.2`).

### The contradiction
- Old: decay ON beats decay OFF by **+0.272 MRR**.
- New: decay ON is **−0.042 MRR** *worse* than decay OFF, and every λ<1.0 is a
  flat plateau. **The sign flipped.** The paper's load-bearing result does not
  reproduce on the current code path.

### Most probable cause (hypothesis — not verified)
The April-30 0.671 number predates the bounded-I/O scoring work (Phase 0–4,
incl. Phase-2 confidence-weighting + source exclusions in `recall_memories()`).
Those changes altered how heat/decay feeds final ranking. Under current code,
decay no longer contributes positive retrieval value on BEAM-100K. **The paper's
empirical core was measured on a now-superseded code path.** This needs
confirmation: re-checkout the Apr-30 commit and re-run, or diff the stored proc.

### Decision you need to make
1. Is the Apr-30 result a clean-vs-dirty-DB confound, a pre-bounded-io artefact,
   or was it always fragile? (Re-run on the old commit to find out.)
2. If current code genuinely makes decay neutral-to-negative on retrieval, Paper
   2's thesis as written is **falsified** and must be either re-scoped (decay as
   a *capacity/cost* mechanism, not a *retrieval-quality* mechanism) or withdrawn.
3. Until resolved, Paper 2 is **not submittable**. I did not edit its decay
   section or rebuild its PDF.

---

## 2. Zipf E2 — independent corroboration that decay does not help retrieval

Artefact: `e2_zipf/20260611T015337Z/summary.csv`. Zipf α=1.5 (heterogeneous,
heavy-tailed access — the regime Paper 2 claims decay is *causal*).
`cortex_full` = decay+heat+consolidation ON; `cortex_flat` = decay OFF, heat≡0.5.

| N | full (decay ON) MRR | flat (decay OFF) MRR |
|---|---|---|
| 1e3 | 0.980 | 0.998 |
| 1e4 | 0.645 | **1.000** |
| 1e5 | 0.622 | **1.000** |

Decay-OFF wins, and the gap *widens* with N. This is a **second** independent
measurement pointing the same way as §1. Caveat: the synthetic ground-truth may
structurally favour flat relevance retrieval, so weight BEAM-100K (§1) above
this — but the direction is consistent and worth noting honestly.

---

## 3. Paper 1 (context assembly) — corroborated directionally, NOT edited

**Provenance blocker:** the paper's headline is BEAM-10M assembler **0.471** MRR
(196 Qs). Tonight's fresh run (`CORTEX_USE_ASSEMBLER=1
CORTEX_STAGE_DETECTOR=temporal`) gives **0.523** at the same 196 Qs. I do not
know whether 0.471 came from a different stage-detector config or is the same
config measured earlier. Your guard forbids an "improved 0.471→0.523" claim with
unknown prior config, so I did **not** swap the number. Decide: is 0.523 the new
canonical assembler-temporal headline (then re-baseline the paper + README to it
with the config pinned), or is 0.471 a different variant to keep alongside it?

The numbers below are clean and corroborate the *direction* of Paper 1's thesis
(structured assembly beats flat WRRF, and the gap is durable with scale):

Fresh BEAM crossover (Fix 1.2), clean bench DB, 695 Qs / 35 convs per cell:

| split | plain WRRF MRR | assembler MRR | Δ |
|---|---|---|---|
| 500K | 0.500 | 0.570 | +0.070 |
| 1M | 0.466 | 0.535 | +0.069 |

BEAM-10M temporal stage detector: MRR **0.523**, R@10 59.3% (196 Qs, 102 min).

Interpretive guards applied (per your instruction):
- "5–10× faster than the previous monolithic version; 10M-token scaling now
  tractable" — NOT a flat 10×.
- temporal 0.523 **retains** the assembler benefit; magnitude is
  regime-dependent; the claim is **label-free deployment**, not a beat over
  oracle. No "improved 0.493→0.523" (prior config unknown).
- Fix 1.2 crossover is **durable with scale** (assembler holds +~0.07 at both
  500K and 1M while flat WRRF collapses 0.500→0.466). Do NOT claim "better
  everywhere." No end-to-end competitor comparisons.

---

## 4. Failed run — E2 subsample (no data)

`paper-compute-runs.sh:20` passed `--benchmark beam`; runner only accepts
`{longmemeval-s, locomo, beam-100K}`. Exited with argparse error, zero output.
**No subsample numbers exist.** If the subsample dose-response is needed, re-run
with `--benchmark beam-100K`.

---

## 5. What I changed tonight (minimal, certain only)

- **README:** version badge `3.18.3 → 3.19.0` (matches `plugin.json`). Nothing
  else — number reconciliation deferred to `readme-revision-plan.md` because the
  measurement families are mixed and Paper 2's story is unsettled.
- **Paper 1:** NOT edited (number-provenance blocker, §3).
- **Paper 2:** NOT edited (thesis sign-reversal blocker, §1). No PDF rebuilt.
- **Outreach drafts:** NOT refreshed — they lean on Paper 2's decay claim, which
  is now in question. Refreshing them now would propagate a falsified result.
- **New planning docs:** this memo + `tasks/readme-revision-plan.md`.

Files touched: `README.md` (1 line), `tasks/overnight-assembly-findings-2026-06-11.md`,
`tasks/readme-revision-plan.md`. New benchmark artefacts (untracked):
`benchmarks/results/decay_sweep/20260611T052523Z/`,
`benchmarks/results/e2_zipf/20260611T015337Z/`.

**Nothing pushed. Nothing sent. No PDFs rebuilt. Both papers frozen.**

## 6. The one thing to do first in the morning
Re-run the decay sweep on the **April-30 commit** (the one that produced 0.671)
against the **clean** `cortex_bench_papers` DB. Two outcomes:
- It reproduces 0.671 → the difference is the bounded-I/O scoring work; decay's
  retrieval benefit was real but the current code path neutralised it. Decide
  whether that is a regression to fix or a genuine finding to re-scope Paper 2.
- It also gives ~0.50 → the original 0.671 was a dirty-DB/config confound and
  Paper 2's decay thesis was never reproducible. Re-scope or withdraw.
Either way, the answer is one re-run away and it gates everything downstream.
