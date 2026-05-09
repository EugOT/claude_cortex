# E1 v3 LoCoMo — STOP at sweep launch (concurrent product fix in flight)

**Status:** STOPPED before launching 14-row sweep. Harness flags committed
(`b68c5ac`); driver written (`benchmarks/lib/run_e1_v3_locomo.py`,
uncommitted). Awaiting human decision.

**Date:** 2026-05-03
**Code base SHA at stop:** `b68c5ac` (HEAD on main).

## What was done

1. Step 1 committed cleanly: `b68c5ac feat(verif): --ablate +
   --with-consolidation flags for LoCoMo harness`. 167 LOC, no push.
2. Step 2 written: `benchmarks/lib/run_e1_v3_locomo.py` driver, 14 rows,
   two-baseline design per Option B in `tasks/e1-v3-locomo-smoke-finding.md`.
   Mirrors LME-S driver structure (commit `ca7f9d4`). Currently uncommitted.
3. First launch attempt at 12:27:12 UTC: subprocess started running but
   exited inside ~10 minutes with no traceback, no per-conversation
   progress lines. Likely the parent shell's session was reaped under
   the Bash tool's worktree boundary; this is a launch-mechanism issue
   independent of the design.
4. Second launch attempt at ~12:35 UTC: driver's dirty-tree gate fired
   (`[FATAL] tree is dirty; refusing to launch`). Inspection showed 6
   files modified in `mcp_server/core/` and `mcp_server/infrastructure/`
   that did NOT exist when the harness commit was made (`b68c5ac`).

## What stopped me

A concurrent worktree agent is mid-flight implementing the exact follow-up
product fix referenced in `e1-v3-locomo-smoke-finding.md`:

```
mcp_server/core/compression.py         | 46 +++++++++++++++++++++---------
mcp_server/core/decay_cycle.py         | 52 ++++++++++++++++++++++++++++------
mcp_server/core/write_gate.py          | 10 +++++--
mcp_server/core/write_post_store.py    |  9 +++++-
mcp_server/infrastructure/pg_schema.py | 27 ++++++++++++++++++
mcp_server/infrastructure/pg_store.py  |  2 +-
6 files changed, 119 insertions(+), 27 deletions(-)
```

Diff sample from `compression.py`:

> Compression cadence asks "has this memory had time to be revisited
> in MY system" — that is elapsed time since ingest, NOT elapsed time
> since the original event. Backfilled / imported memories carry a
> backdated created_at (e.g. a 2023 conversation imported in 2026);
> using created_at would compress them on the first consolidation
> pass, before retrieval ever runs (see
> tasks/e1-v3-locomo-smoke-finding.md).

The concurrent agent is migrating consolidation cadence from `created_at`
(wall-clock-relative) to `ingested_at` (corpus-age-relative). This is
**the exact fix** the smoke finding pointed at, and it directly
invalidates the design premise of the two-baseline sweep:

- BASELINE_WITH_CONSOLIDATION on the current SHA (`b68c5ac`) shows
  MRR=0.222 (smoke). The 8 consolidation-only rows are designed to
  measure mechanism contribution within that collapse regime.
- After the concurrent agent's fix lands, BASELINE_WITH_CONSOLIDATION
  will likely return to ~0.866 (no first-pass corpus collapse). The
  collapse-regime ablation deltas become obsolete — and worse, would
  be reported in the paper as "mechanism contributions" when they are
  actually "rescue from a bug that was fixed before publication."

## Why I will not run the sweep on the current SHA

Three problems, any one of which is sufficient to stop:

1. **Tree is dirty.** Driver's pre-flight dirty-check refuses (matches
   the LME-S driver's gate). Sweep cannot launch without bypassing the
   gate, which would defeat the purpose of recording a single SHA.
2. **Code is mid-flight.** The 7h sweep would race a concurrent fix
   touching the very pipeline the sweep measures. Mid-sweep file
   changes would yield un-attributable deltas across rows.
3. **Design premise is dissolving.** The smoke evidence (0.222) is
   the artifact of a soon-to-be-fixed bug. Locking in 13 hours of
   measurement against that artifact and writing it into the paper
   would be precisely the kind of "confident wrong number that
   destroys trust" the Zetetic standard prohibits.

## Recommended next actions (FOR HUMAN DECISION)

### Option α — wait for the concurrent fix to land, then re-run
- Concurrent agent commits the `ingested_at` fix and merges to main.
- Re-smoke `--with-consolidation` to confirm BASELINE_WITH_CONSOLIDATION
  no longer collapses. Expected: MRR back near no-consolidation anchor
  (≈0.866), modulo whatever the 9 consolidation-only mechanisms actually
  contribute.
- If the new BASELINE_WITH_CONSOLIDATION is healthy, the two-baseline
  design simplifies: both baselines should be near each other, and the
  full 14 rows measure honest per-mechanism contributions.
- Then commit the driver and launch.

### Option β — collapse to single baseline post-fix
- Once the fix lands, BASELINE_NO_CONSOLIDATION ≈ BASELINE_WITH_CONSOLIDATION
  may make the two-baseline design unnecessary. Could simplify to a
  13-row design (one BASELINE + 12 mechanism rows) like LME-S.
- Cheaper sweep (~6.5h). Cleaner paper §6.3 narrative.

### Option γ — proceed now, document the regime
- Run the 14 rows on `b68c5ac` regardless. The numbers honestly describe
  the consolidation pipeline as it currently exists. The paper §6.3 must
  then disclose that the "consolidation regime" measured here was
  superseded by the ingested_at fix in a follow-up commit.
- This keeps deadline pressure but ships ablation evidence about a code
  state that no longer exists in main. Not recommended.

### Option δ — drop the LoCoMo half
- Reverts to LME-S only as in `de1d316`. Mechanisms remain in the
  codebase but are not supported by ablation evidence in §6.3.

## Driver artifact (uncommitted, ready for relaunch)

`benchmarks/lib/run_e1_v3_locomo.py` exists and parses cleanly. 14 rows,
two-baseline design, per-category breakdown, sanity gate against
CLAUDE.md headline (0.794 ±0.05). When the human picks Option α/β, the
driver can be committed (with adjusted ROWS list for β) and launched.

## Recommendation

**Option α.** The concurrent fix directly addresses the smoke-surfaced
collision; running the sweep before it lands measures a stale state.
~30 min wait + 7h sweep is cheaper than ~7h sweep + retraction.
