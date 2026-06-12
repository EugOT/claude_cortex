# Slim graph wire format — design from graphify reverse-engineering

Date: 2026-06-12. Source analysis: `safishamsi/graphify` (cloned at
/tmp/graphify, shallow). Decision driver: user direction — "the
information of a node should be MCP on-demand access, not preloaded;
streaming would have only the position, type and n-1/n+1 index".

## What graphify actually does (verified in source)

1. **Nodes are pointers, never content** (`ARCHITECTURE.md`,
   `extract.py` schema): a node is `{id, label, source_file,
   source_location, community}`. The corpus stays on disk; the graph
   stores WHERE things are. Even the MCP `get_node` tool
   (`serve.py:717`) returns six text lines (label, id, source, type,
   community, degree) — the body is never in the graph.
2. **Every consumer gets a budgeted slice, never the graph**
   (`serve.py:371` `_subgraph_to_text`): MCP `query_graph` scores
   seeds by IDF over labels, BFS-expands, renders text, and HARD-CUTS
   at 2,000 tokens (3 chars/token) with explicit truncation guidance.
   `benchmark.py` exists solely to prove the claim (~2k tokens/query
   vs ~670k naive corpus dump).
3. **The viz refuses scale by design** (`export.py:156`
   `MAX_NODES_FOR_VIZ = 5_000`): graph.html inlines graph.json only
   under the cap. The full graph lives behind queries, not behind the
   renderer.

## Confirmed problem on our side (measured)

- SSE replay of the full galaxy: **107,387,469 bytes for 414,462
  items = 259 bytes/item**. Every node ships its full record (label,
  color, path, symbol_type, domain_id, domain, memory metadata) even
  though the on-demand drill already exists (`/api/graph/node` +
  `_node_index`, added 2026-06-12) and the renderer paints a dot from
  position+type alone.
- The browser then holds 143k full dicts in `JUG.state.lastData` —
  client memory/GC pressure is the residual "not browsable" feel.
- `query_workflow_graph` (MCP) rebuilds the whole graph per call with
  no token budget — the exact inverse of graphify's slice discipline.

## Principle correction (user direction 2026-06-12)

Graphify's 2,000-token HARD CAP is NOT adopted. Cortex is a second
brain used for scientific accuracy — a view that silently shows 1/3
of the results reads as a BUG to a scientific user, not as a feature.
The rule, consistent with `core/response_budget.py`: a bounded
response may DEFER (pagination / fetch-by-id continuation) but never
DISCARD. Completeness over latency — a few seconds of on-demand
loading is acceptable; silent truncation is not. What IS adopted from
graphify: nodes as pointers, light wire payloads, on-demand detail.

## Design

### 1. Light JSON wire (SSE `/api/graph/events`) — no mapper

Plain light JSON, no enum tables, no index↔id translation layer —
the codec/mapper class of solutions (CXGB, LayoutAuthority protocol)
is what kept breaking. Batch events keep the existing shape, with
nodes and edges as minimal tuples:
```json
{"label":"L6 3/10 ap-graph",
 "nodes":[["symbol:3e20b08fc93e","symbol",1234.5,-567.8], ...],
 "edges":[["symbol:a","symbol:b","calls"], ...]}
```
- Per node: id, kind, x, y. Per edge: source, target, kind. Nothing
  else — no label, color, path, domain, metadata on the wire.
- Color = f(kind) client-side (palette already keyed by kind).
  Positions are server-baked — the client never runs a 143k-node
  force sim.
- Measured projection (real id lengths): ~45 B/node + ~55 B/edge ⇒
  **~21 MB total vs 107 MB (≈5× smaller)**, with zero new
  abstraction. If measurement later shows 21 MB still too slow,
  binary is the follow-on — only then.

### 2. On-demand node access (exists — becomes the ONLY detail path)

- Click: `/api/graph/node?id=` serves the full record from
  `_node_index` (O(1), built 2026-06-12). A few-hundred-ms fetch on
  click is accepted UX.
- Labels: viewport/zoom-driven batched fetch; dots need no labels.

### 3. Complete MCP slices (`query_workflow_graph`)

Query the LIVE viz cache (single graph authority — fixes the
ecosystem divergence noted 2026-06-12, memory 4197486). Responses are
bounded per page but COMPLETE across continuation: same contract as
`response_budget.py` — every omitted item keeps its id + a cursor
(`offset`/`next`) so the consumer can drain the full result set.
Never a lossy cap; the response always states total counts.

## Acceptance criteria (external signals) — MEASURED 2026-06-12

1. Full-galaxy replay: **41.9 MB measured vs 107 MB (2.56×)**. The
   pre-implementation ≤25 MB estimate missed two facts the
   decomposition exposed: 73,706 entity nodes (9.8 MB) and 19.7 MB of
   edge tuples whose bytes are almost entirely the two endpoint id
   strings — the irreducible no-mapper floor. Squeezing further means
   id interning/enum tables, i.e. exactly the mapper class the user
   rejected. PASS with the measured number as the new baseline.
2. Browser heap for the loaded galaxy measurably reduced
   (Performance panel snapshot before/after).
3. Node click returns full record in <50 ms during build
   (`/api/graph/node?id=`) — measured 0.6 ms. PASS.
4. `query_workflow_graph` against the live 144k-node cache:
   source=live-cache, first call 0.7 s (slice drain + memo), repeat
   0.21 s (phase_seq memo hit); totals exact (94,437 symbols);
   continuation drain unions to the full matched set (101/101). PASS.
5. Contract tests green: 515 passed (server + handlers), including
   the slim-wire shape pin, slice completeness, pagination union,
   and live-cache preference tests. PASS.
6. Coordinate path verified on the wire: live pre-layout copy ships
   null x/y, post-bake re-emission carries 4-decimal coords, client
   backfills onto the deduped node. PASS.

## Remaining work — renderer static-draw + END of silent caps

User direction 2026-06-12: a hard cap is a truncation of the
scientific record — the completeness principle applies to the WHOLE
chain (build → cache → wire → render), not just the query surface.
Inventory of remaining silent caps, all to be removed:

| Cap | Where | What it amputates |
|---|---|---|
| `CORTEX_VIZ_MEMORY_LIMIT=25000` | build (`http_standalone_graph.py`) | REMOVED 2026-06-12: default now 0 (uncapped); unbounded path retains slim dicts per batch (builder discard kept — it bounds pydantic objects only) and memories get `_place_around` rays (DrL stays structural-only). Measured on the current DB (1,698 memories — the 107k/400k figures were the May dev DB, since purged): build 198 s, RSS 0.7 GB. The 10⁵-corpus behaviour is PROJECTED (~227 B/row stream + ~0.4 KB/dict retention ≈ hundreds of MB), not yet measured — re-measure when the corpus regrows. Env var stays as explicit opt-in subset. |
| `EXTREME > 25k` | renderer (`workflow_graph.js`) | REMOVED in static mode (69ba5b40) — never applies when server positions drive the draw |
| `HEAVY > 8k` | renderer | REMOVED in static mode (69ba5b40) |
| `ENTITY_TOPN` heat gate | renderer (~line 895) | inert in static mode (it only gated slot assignment for the simulation; static positions come from the server) |

These caps exist to keep the d3 force simulation alive; the
static-draw mode (server positions, client draws — memory 4197492)
removes their reason to exist. Display-level LOD (what is LEGIBLE at
a zoom level: labels, edge fading) remains allowed — it is a property
of the viewport, not of the data; every node and edge stays in the
scene and in the counts.

## Non-goals

- No binary codec, no enum/index mapper — light JSON only, per user
  direction. Binary is a follow-on ONLY if 21 MB measures too slow.
- No hard token caps anywhere in the query surface.
- No change to the build pipeline stages (L0–L6) or the SSE
  lifecycle fixed in aae4cbc.
