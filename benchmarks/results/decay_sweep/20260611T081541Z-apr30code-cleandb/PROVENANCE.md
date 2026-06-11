# Forensic re-run: Apr-30 code on a CLEAN database

- Code: commit cfa96e8 (the exact commit that produced the committed artefact
  20260430T111134Z cited by Paper 2 §decay-dose), checked out in a detached
  worktree at /tmp/cortex-apr30.
- DB: freshly created `cortex_bench_decay_apr30` (CREATE DATABASE + vector,
  pg_trgm extensions only — zero prior contents).
- Command: `.venv/bin/python -m benchmarks.lib.decay_sweep_runner --lambda 0.95 1.0 --quick`
  (same quick mode = 3 BEAM conversations as the Apr-30 artefact; confirmed
  `"quick": true` in 20260430T111134Z/lambda_*.json).
- Date: 2026-06-11, run 20260611T081541Z.

## Result
| λ | MRR | R@10 |
|---|---|---|
| 0.95 | 0.671 | 0.867 |
| 1.00 | 0.671 | 0.867 |

Gap = 0.000. The committed Apr-30 artefact reported 0.671 vs 0.399 (+0.272)
on the SAME code and SAME quick sample — the only changed factor is database
cleanliness. Conclusion: the +0.272 decay benefit in 20260430T111134Z was a
dirty-database confound, not a property of the decay mechanism.

The original JSON artefacts were written inside the temporary worktree
(/tmp/cortex-apr30/benchmarks/results/decay_sweep/20260611T081541Z/) and were
lost when the worktree was removed; sweep-stdout.log is the runner's full
stdout/stderr capturing both per-λ lines and the curve analysis.
