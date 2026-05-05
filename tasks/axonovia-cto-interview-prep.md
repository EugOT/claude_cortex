# Axonovia CTO — interview prep (Friday)

**Counterparty:** CTO of Axonovia (Mimi Karassane's company)
**Use case framing:** decision-making storage and retrieval, not code implementation
**Their adjacent product:** Vigilo (memory + audit brick)
**Source signal:** "transforming mails + human corrections into reliable memory (proofs, rules, history)"
**Sector:** transport (logistics? freight? regulated industry → audit-grade requirements likely mandatory)

The interview is exploratory — they're feeling out whether Cortex can be a building
block, not buying. Goal of the call: leave them wanting a follow-up technical deep
dive with a defined evaluation scope.

## The 30-second pitch (don't memorize, internalize)

> Cortex is a long-term memory architecture that treats retrieval as provenance. Every
> decision your operator makes can be traced back to which memories supported it,
> when those memories entered the system, and which biological mechanisms ranked them.
> It's PostgreSQL-native, open source, and we just published per-mechanism ablation
> evidence on three benchmarks showing the architecture beats published baselines —
> including a +20-point R@10 jump on LongMemEval and the strongest BEAM-10M result.

## The five things they probably actually want to know

| Their question (often unstated) | What you say | Backing evidence |
|---|---|---|
| "Will it scale to our throughput?" | PostgreSQL + pgvector with HNSW; recall is a single PL/pgSQL call (~50–200ms p95 on 1M memories). No new infra. | Latency benchmark in `benchmarks/results/latency_benchmark/` |
| "Can we audit every decision?" | Every retrieval returns the memories + per-mechanism contribution scores. Reconsolidation logs which memories were read. ingested_at separates *when we learned* from *when the event happened* — load-bearing for backfilled mail history. | 26-mech enum + ablation evidence + commit `6c51bce` (cadence fix) |
| "How does it learn from human corrections?" | Predictive-coding write gate + heat updates on access + reconsolidation on retrieval. A correction ingested as a new memory immediately re-ranks against the prior one via the contradiction-detection mechanism. | Paper §4-§6, write_gate.py + reconsolidation.py |
| "Is it production-ready?" | 2700+ tests, 45 ablation rows, two production fixes shipped *during* the verification campaign (cadence + plasticity). Verification surfaced bugs the system was designed to catch. | E1 v3 results + commits `6c51bce`, `5f737fe` |
| "How does this compare to LangChain Memory / Mem0 / Zep?" | LangChain Memory has no provenance and no decay. Mem0 has multi-tenant + good production posture but a thinner theoretical foundation (no per-mechanism evidence). Zep is closest in pitch but their published evidence is qualitative. Cortex's differentiator is the 45-row paper-bearing ablation campaign. | Paper draft + repo |

## Demo flow (15 minutes if they're engaged)

Pick ONE realistic transport-sector scenario before the call. Suggested:
*"An operator handling a freight booking is asked: 'Should we route this through
Hamburg or Rotterdam given our customer history with this shipper?'"*

1. **Live the problem (2 min):** Show the question and what a stateless agent would do (re-derive everything from scratch, miss the human-corrected preference).
2. **`recall` + show the per-mechanism scores (4 min):** Type the question into the Cortex MCP. Show that the top-3 results are: (a) past Hamburg routings for this customer, (b) a manual correction noting "customer prefers Rotterdam after the Q3 strike", (c) a contradiction-resolution memory that flagged the strike. Open `cortex:open_visualization` to show the entity graph linking customer → routes → corrections.
3. **Audit trail (3 min):** Click into the correction memory; show its `ingested_at` (when the operator typed it), `created_at` (when the strike happened), the heat trajectory (every recall bumped it), and the reconsolidation log (every operator that read it).
4. **Backfill scenario (3 min):** Mention the cadence-fix story (`6c51bce`) — when they import last year's email history, Cortex doesn't immediately compress it into uselessness because age is measured from ingest, not from event date. This is exactly the bug they'd hit with a naive system.
5. **Their "what about" (3 min):** Pause and let them push.

## Questions to ask THEM (the interview is two-way)

- "What does an operator's decision look like in your system today? Is it a single tool call, a chain, or a full agent loop?"
- "What's the audit format Vigilo needs? Per-decision provenance? Cumulative session log? Regulatory format like SOX-compatible?"
- "Where do the 'human corrections' come from — operators flagging in real time, or batch review of past decisions?"
- "What's the data residency requirement? On-prem mandatory or cloud-OK?"
- "What's the cardinality: roughly how many decisions per operator per day, how many operators?"
- "What's the longest time window a decision needs to reference? Hours, weeks, years?"

These let you size the conversation. Their answers determine which Cortex subset is
load-bearing for them.

## Where Cortex fits cleanly

- ✅ Long-term memory across many operator sessions
- ✅ Provenance: every retrieval explains which memories + which mechanisms ranked them
- ✅ Backfill of historic email/decision data (commit `6c51bce` makes this work)
- ✅ Contradiction resolution between original and corrected memories
- ✅ Temporal reasoning (LongMemEval shows 0.8 MRR on temporal-reasoning category)
- ✅ Open source MIT + self-hostable (matches transport-sector data-residency)
- ✅ PostgreSQL-native (likely matches their existing stack; no new vector DB)

## Where Cortex doesn't fit out of the box (be honest)

- ❌ **Multi-tenant isolation:** current `domain` field is a soft partition, not Postgres
  row-level security. If they need hard tenant isolation per customer, that's a small
  but explicit extension (RLS policies + per-tenant connection pooling).
- ❌ **Signed audit logs:** the audit trail is journaling + heat, not cryptographic
  attestation. Regulated industries may need digital signatures on every recall
  result. Buildable on top, not in the box today.
- ❌ **Rule engine overlay:** Cortex stores facts and learned patterns; it does NOT
  have an if-then policy engine. If their operators need "always escalate to a human
  if the customer is on the embargo list", that's a separate layer (probably their
  existing system; Cortex feeds it, doesn't replace it).
- ❌ **Computer-use integration:** no native hooks into their computer-use stack;
  the integration would be application-level (their operator captures a screen
  observation → calls Cortex `remember` with that observation → Cortex stores +
  later retrieves). Mention it as light glue work, not a blocker.
- ❌ **Real-time streaming:** Cortex is a request/response system. If they're
  capturing high-frequency telemetry from operators (e.g. mouse movement, gaze),
  that goes to a different system; Cortex stores the *decisions* not the *signals*.

The honest framing: **Cortex is the audit-grade long-term memory layer; it composes
with your existing computer-use, rule engine, and tenant management.**

## Numbers to have at hand (don't recite, refer naturally)

- **LongMemEval R@10 = 98.4%** (vs paper-best 78.4% → +20 pts)
- **LoCoMo R@10 = 94.3%** (vs paper 92.6%)
- **BEAM-10M = +33.4%** over flat retrieval (the hardest published long-context memory benchmark)
- **45 row ablation** spanning 2 benchmarks, 26 wired biological mechanisms
- **2 production fixes shipped during verification** (cadence + plasticity)
- **30-page paper** with 45 cited papers, arXiv submission in progress
- **MIT licensed** open source (their procurement team will care)

## Likely objections + your response

**"Why neuroscience metaphors? Sounds academic."**
> The metaphors are scaffolding for the math. Each mechanism is a real algorithm with
> a paper citation; the names just make the architecture easier to navigate. The
> ablation evidence is what matters — disabling RECONSOLIDATION costs 0.0091 MRR on
> LoCoMo, which is a measurable, defensible claim independent of the metaphor.

**"You're the only person on this. What's the bus factor?"**
> The system is 13K LOC of PostgreSQL + Python, MIT-licensed. The paper plus code
> means an in-house team could pick it up if needed. I have a backlog of work but
> the architecture is documented in 30 pages, not just in my head.

**"How much does it cost to run?"**
> One PostgreSQL instance with pgvector. At your scale (need their numbers) probably
> single-digit cores, 16-32 GB RAM, NVMe storage. No GPU required for retrieval; the
> embedder runs CPU-only via sentence-transformers. Inference cost is whatever LLM
> they're already paying for.

**"What's your business model? Why would I use you instead of forking?"**
> Fork it. The MIT license means you can. What I offer beyond the code is the paper
> defensibility for your customers' procurement teams, the active maintenance, the
> ablation-driven calibration of new mechanisms, and the willingness to integrate
> against your specific use case. If forking is the right call for you, I'd rather
> see Cortex used than not.

(This last one is important — Axonovia is a startup; you don't want to position as a
license-fee vendor when you should position as a collaborator who happens to ship
open source.)

## What you want out of the call

In order of preference:

1. **A defined PoC scope.** "Let's wire Cortex to your operator's email-correction
   loop and measure provenance recall on N decisions over M weeks." Even if it's
   small, this is the start of a real engagement.
2. **An introduction to the Vigilo team** if Vigilo is a separate product/customer.
3. **Reviewer / endorser intro for arXiv** (Mimi's husband angle still active).
4. **Validation that the framing resonates** even if no immediate next step.

## What you do NOT want

- A long unpaid "let us evaluate" period that ends in silence.
- A request to integrate against undisclosed proprietary systems before scope is
  defined.
- An NDA that prevents you from using the engagement as a reference (Cortex's value
  comes partly from being seen as a working production system).

## Pre-call mechanical checklist

- [ ] arxiv.org account created (so the endorser code is ready if Mimi's husband angle comes up)
- [ ] `docs/arxiv-thermodynamic/main.pdf` and `docs/arxiv-context-assembly/main.pdf` open in tabs
- [ ] Cortex 3D visualization running locally so you can pivot to live demo
- [ ] At least one transport-sector example you've seeded into your local Cortex (so the demo isn't theoretical)
- [ ] Discord / Slack / WhatsApp for follow-up handoffs after the call
- [ ] Phone fully charged; quiet room; backup network

## The narrative arc to leave them with

> "Cortex was built to make AI memory defensible. We measured it; we found bugs;
> we fixed them; we documented everything. If your operators need to explain WHY
> they made a decision, this is the memory layer that lets them. Let's pick a
> small slice of your workflow and wire it up."
