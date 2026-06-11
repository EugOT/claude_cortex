# README Revision Plan (2026-06-11)

Editorial plan — **not executed**. The README needs a storytelling-but-verifiable
pass, and the data picture shifted overnight (see
`overnight-assembly-findings-2026-06-11.md`). Piecemeal number swaps are unsafe
until the Paper 2 decay question is resolved, so this is staged for your call.

## Done tonight (certain, safe)
- Version badge `3.18.3 → 3.19.0` (matches `plugin.json`).

## Must fix — internal contradictions (factual, verifiable once data settles)
1. **BEAM-10M double-labelled number (lines ~189 & ~206).** `0.471` is presented
   both as the assembler temporal MRR *and* as the oracle-comparison figure
   ("0.471 vs 0.429 with oracle plan_id"). One number cannot be both. Fresh
   BEAM-10M temporal run tonight = **0.523** (196 Qs, R@10 59.3%) — but that is a
   *different question count/config* than the run behind 0.471, so it is NOT a
   drop-in replacement. Decide which run is canonical, then state ONE temporal
   number with its Q count.
2. **False "no oracle labels, timestamps only" framing (line ~191, ~206).** The
   claim that temporal partitioning "outperforms BEAM's ground-truth topic
   labels" needs a paired oracle-vs-temporal run on the *same* split/Qs to stand.
   No such paired run exists tonight. Retire the "outperforms oracle" sentence
   until a paired measurement backs it; the defensible claim is the weaker,
   honest one: **label-free deployment retains the assembler benefit** (magnitude
   regime-dependent).
3. **Star count / social-proof figures** (per prior note → 52) — verify against
   GitHub before printing any count.

## Must reconcile to measured data (once canonical runs chosen)
Fresh, clean-bench numbers available to cite (all retrieval-proxy MRR, BEAM):
- 500K: plain 0.500 / assembler 0.570
- 1M:   plain 0.466 / assembler 0.535  (crossover durable with scale)
- 10M temporal: 0.523 (196 Qs)
README currently cites BEAM-100K 0.591/0.602 and BEAM-10M 0.353/0.471 from older
runs at other configs. Pick one consistent measurement family and label every
cell with split + Q count + date + artefact path.

## Blocked on Paper 2 decision
- Any README sentence asserting decay/thermodynamics *improves retrieval* is now
  in question (fresh λ-sweep + Zipf E2 both show decay neutral-to-negative on
  retrieval — see findings memo §1–2). Do NOT write a "decay makes retrieval
  better" claim into the README until Paper 2's thesis is adjudicated.

## Editorial (storytelling, not selling) — structure to keep
- Keep the 5 working screenshots in `docs/assets/`: wiki-project-tree,
  wiki-edit-preview, cortex-consolidation-board, cortex-memory-detail,
  cortex-workflow-graph (the OLD graph — keep until the new galaxy is validated).
- NO Trace screenshot (the image is broken) — a screenshot is a claim; don't ship
  a broken one.
- Cover all surfaces narratively: wiki / consolidation board / knowledge graph /
  workflow graph / trace — describe, don't oversell.
- Every benchmark number visible + ablation-traceable; honest caveat block on the
  retrieval-proxy-vs-LLM-judge metric distinction stays (line ~212 is good).
- No end-to-end competitor comparisons (our MRR is a retrieval proxy; their LIGHT
  is end-to-end QA — not comparable).

## Order of operations (when you greenlight)
1. Resolve Paper 2 decay (re-run Apr-30 commit to explain the sign flip).
2. Choose canonical BEAM measurement family; lock split/Qs/date per cell.
3. Run paired oracle-vs-temporal on one split IF the oracle claim is to survive.
4. Then revise README prose + tables in one coherent pass.
