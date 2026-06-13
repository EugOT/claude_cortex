# supersession_gate — regression guards

Locks the result of the **KU-via-supersession investigation** (session
`fba48610`, 2026-06-13): session-granularity contradiction-supersession **cannot
move LongMemEval knowledge-update (KU) MRR**. The thread is closed; baseline KU
**MRR 0.9246 / R@10 1.0000** stands with no code change. These guards exist so a
future change to the supersede gate or the contradiction detector cannot silently
reverse that conclusion without a maintainer noticing.

## The four-layer falsification (all durable in Cortex, `agent_topic=cortex`)

| Layer | Finding | Cortex id | Guard |
|---|---|---|---|
| Session granularity | 0 edges form (jaccard>0.5 binds) | 4197865 | `guard_session_granularity.py` |
| Chunk granularity (decomposed turn-pairs) | 0 edges form | 4197880 | `guard_chunk_granularity.py` |
| Atomic granularity (A2 upper bound, 12 clean pairs) | jaccard SOLVED (6/12) but `detect_contradictions` blind to value swaps → 0/12 fire | 4197901 | `guard_atomic_upperbound.py` |
| Metric semantics (DECISIVE) | `compute_mrr` credits BOTH old+new evidence sessions; supersession demotes the OLD (credited) session → monotonically non-improving for MRR. Lever points the wrong way. | 4197905 | *(not mechanizable — documented here)* |

The decisive layer kills **any** supersession approach (including an LLM
value-change detector): "prefer new over old" is a reader/generation property,
not something the Cortex retrieval benchmark (session-id R@10 / MRR) measures.
The first three guards mechanize the *gate-firing* sub-results; the fourth is a
property of the metric and lives in this README as the reason the others matter.

## Running

```bash
# all three (read-only; no DB writes, no recall change)
for g in guard_session_granularity guard_chunk_granularity guard_atomic_upperbound; do
  Cortex/.venv/bin/python3 benchmarks/supersession_gate/$g.py || echo "REGRESSION in $g"
done
```

Use `Cortex/.venv/bin/python3` (provides numpy); plain `python3` lacks it.

## PASS criteria (exit 0 = PASS, 1 = deviation)

- **session / chunk guards**: `full_gate == 0`. Any edge forming is a regression
  in the supersede gate (`mcp_server/handlers/remember_helpers.py:344-360`) or
  its thresholds — re-open the investigation before trusting the gate.
- **atomic guard**: `fired == 0`. A non-zero result is not necessarily a bug — it
  means `detect_contradictions` gained value-swap sensitivity (the binding
  constraint the investigation identified). Either way a maintainer must look,
  because it would re-open the A2 supersession path.
