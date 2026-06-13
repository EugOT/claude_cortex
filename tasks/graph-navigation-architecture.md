# Graph Navigation Architecture — second-brain research synthesis (2026-06-12)

Derived from a verified 6-agent crawl of 29 tools (Obsidian, Logseq, Roam, Foam, Dendron, TheBrain, InfraNodus, Kumu, Graphify, GitNexus, Sourcegraph, Sourcetrail, CodeSee, Neo4j Browser/Bloom, Linkurious, Gephi Lite, Connected Papers, Litmaps, OKM, Quartz, ...). Verification: VERIFIED with 5 corrections (appended).

# Competitive Synthesis: Graph Views at 150k+ Nodes

## 1. THE CONVERGENT PATTERN

**The dividing line is not renderer tech — it is whether the renderer's working set is bounded by node degree or by corpus size.** Every tool whose graph survives growth bounds the working set; every tool that ships the whole graph dies at a predictable ceiling.

**What the survivors all do:**

- **Default view is a small, bounded ego/curated set, never the world.** TheBrain renders exactly one active thought + parents/children/jumps/siblings (render cost = node degree, which is why a 572K-thought/1.12M-link brain stays navigable). Sourcetrail renders active symbol + 1-hop, with everything else bundled into "Files: N / Classes: N" aggregate nodes — even its "overview" is bundled-by-type, never raw. Connected Papers ships ~30–50 nodes from a corpus of hundreds of millions. Neo4j Browser opens EMPTY and truncates the first render at 300 nodes (`initialNodeDisplay`). Logseq's DB-version defaults to tag-nodes-only with progressive reveal.
- **Expansion is a fresh bounded server/store query per interaction, not an unfold of pre-shipped data.** Neo4j Browser: double-click = 1-hop Cypher with `LIMIT maxNewNeighbours` (cap 100, enforced *in the query*). Linkurious: 1-hop REST fetch; >50 neighbors triggers a Selective Expand refine dialog instead of dumping. Sourcetrail: every click re-queries SQLite (`getGraphForActiveTokenIds`). TheBrain: every click = local-API neighborhood query + animated recenter.
- **Caps live at the query level and DEFER, never discard.** Linkurious supernodes (degree > threshold, default 10k) render a "+" badge with approximate count instead of expanding; the data stays queryable. Neo4j Browser runs a count-only query when the cap is hit. Sourcetrail's collapsed members show the hidden count behind an expansion arrow. This is exactly the "defer behind queries" semantics Cortex requires — it exists in production tools and is the standard pattern.
- **Layout is deterministic for navigation-first tools; force simulation appears only in load-it-all tools.** TheBrain's plex (fixed zones), Sourcetrail's BucketLayouter (grid buckets left=incoming/right=outgoing), CodeSee (hierarchical containers), Litmaps (attribute axes), Open Knowledge Maps (server-precomputed ordination), GitNexus tree/circles modes (deterministic rings). Stable, reproducible positions are what make click-to-refocus usable; live force layout, not the renderer, is the first thing to break client-side (sigma FA2 degrades past ~50k edges; Kumu's "jiggly map... for minutes").
- **Long-range navigation is search, not graph-walking.** TheBrain states this explicitly: traversing 100K+ thoughts without instant search "would be cumbersome." Bloom and Sourcegraph are search/query-first by construction.

**Quantified norms:** upfront payload 30–300 nodes (Connected Papers ~40, OKM 100 hard, Neo4j Browser 300, TheBrain ≈ degree of active thought); per-expansion fetch 50–100 (Linkurious 50, Neo4j 100, Wikipedia Map 5–10, Bloom 100–10,000 user-set with 10k absolute ceiling); visible simulated working set ≤ a few thousand (Logseq force sim hard-bounded to ≤900 nodes; large draw caps 2,200 nodes/3,600 edges).

**The failure ceiling, replicated independently:** client force-graph dies at ~5k (Graphify `MAX_NODES_FOR_VIZ=5_000` ValueError; GitNexus "~5k files browser memory"), gets unusable at ~25k–50k (Obsidian moderator: ">25K files not practical"; 130k-note vault freezes even the depth-1 LOCAL graph on an RTX 4090, because the *data model* is still full-vault), and is an admitted dead end at 10⁴+ (Logseq's hard draw caps are the confession). 150k Cortex nodes is 6–30× past where every whole-graph client architecture has died.

## 2. WHERE THE USER'S SPEC MAPS

The spec is the empirically winning architecture — each requirement has direct precedent:

| Spec requirement | Precedent |
|---|---|
| Stream only position/type/n−1,n+1 index (slim skeleton) | Stronger than any PKM tool (Obsidian/Quartz ship full link index + titles). Matches SCIP's philosophy (Sourcegraph: index server-side, ship occurrences per view) and Logseq's worker-built `{nodes, links}` minimal wire shape. Carrying server positions in the skeleton = the OKM/Connected Papers precomputed-layout model — the only model shown to work at scale, since client layout is the first breaking component everywhere. |
| Node info via on-demand MCP/API call | TheBrain local REST API ("hundreds of thoughts/sec, no throttle"), Sourcetrail per-click SQLite query, Neo4j Browser per-expand Cypher. Detail-on-click is universal among scalable tools; only PKM toys inline full frontmatter per node (Foam — and it pays in payload). |
| No hard caps that discard; defer behind queries OK | Exactly the Linkurious supernode badge / Neo4j count-only fallback / Sourcetrail "expansion arrow with hidden-member count" pattern. The corpus shows deferral-with-count is *better* UX than silent caps (Obsidian/Logseq silently drop or freeze; Graphify just refuses). |
| FactSet-grade responsiveness | Achieved by the tools whose per-interaction cost is O(degree), not O(corpus): TheBrain (instant at 572k), Sourcetrail (instant per-view). Achieved by *deterministic layout + bounded fetch*, never by renderer heroics. |

One correction the corpus forces on the spec: streaming the n−1/n+1 adjacency index for **all 150k nodes** is itself the Obsidian failure mode if the client must hold and simulate it. The skeleton stream must be position+type+id only (render-ready dots, LOD-culled); adjacency should resolve per-node on demand (`/api/graph/node` neighbors page), or be streamed only for the currently expanded horizon. Obsidian's 130k-vault local graph freezes *despite depth-1 display* precisely because the full adjacency model is client-resident.

## 3. THE CORTEX DESIGN

Cortex already has the right assets; the work is demotion of the whole-graph path, not new construction.

**View hierarchy (TheBrain plex × Sourcetrail bundling, mapped to Cortex node kinds):**

- **L0 (cold open, <500 elements):** domains + projects + top wiki/schema nodes, each badged with deferred counts ("athena-swift — 1,243 files, 18,402 symbols, 312 memories") — the Sourcetrail `bundleNodesByType` overview. Server-side positions from **LayoutAuthority** (already exists: `layout_authority*.py`), streamed over the existing SSE channel `/api/graph/events`. Slim wire records: `{id, kind, x, y, degree_summary}` — nothing else.
- **L1 (click a domain/project):** one bounded fetch returns its ego network — child files bundled by directory, hot memories, entities — capped per-query at ~100 with a `deferred: {files: 1143}` remainder, page-through via cursor. The clicked node recenters; previous context collapses back to a badge (plex recenter gesture). Breadcrumb trail = the activation history (TheBrain's back/forward).
- **L2 (click a file):** symbols defined in it (bundled "referencing/referenced" style if degree is high), linked memories, wiki drift status. **L2 (click a memory):** entities, causal links, source session — served by `recall`/`navigate_memory`-backed queries.
- **Supernode rule:** any node with degree > threshold renders a "+N" badge and opens a refine dialog (filter by edge kind: defines/imports/mentions/causal) instead of auto-expanding — Linkurious Selective Expand, verbatim.
- **Long-jump:** search box (unified_search) as the primary navigation for anything not on screen — TheBrain's explicit lesson; never expect users to walk 150k nodes hop-by-hop.

**Endpoint shapes (mostly existing):**

- `GET /api/graph/events` (SSE) — KEEP, but restrict payload to the L0 skeleton + position deltas from LayoutAuthority. This is the "stream only position/type" channel.
- `GET /api/graph/node?id=X&edges=<kind>&cursor=C&limit=100` — KEEP and extend with paged neighbors + per-kind deferred counts. This is the on-demand contract; every count must be exact (scientific completeness) even when items defer.
- `GET /api/graph/slice` — REPURPOSE from "page through the full graph" to "fetch a named bounded subgraph" (ego of id at hop 1, a community, a query result). Offset/limit pagination over the whole world is a tool no scalable competitor needs client-side.
- Layout stays server-owned in LayoutAuthority — positions are computed/persisted server-side and clients only ever receive coordinates. No client force simulation, ever (the corpus's single most consistent breaking point).

**DELETE:**

1. **The full-graph cache-and-ship path**: `GET /api/graph` returning the cumulative whole `_graph_cache`, and the `/api/graph/phase` append-only loader whose contract is "client eventually holds all phases" — that is the Obsidian/Gephi Lite architecture, certified dead at 25k–50k, and Cortex is at 150k. (`graph_snapshot.py` is already deleted in the working tree — correct direction.)
2. **The dead `/api/graph/stream`** — `http_standalone_graph.py:1415` admits it "has NO consumer (not routed)". Unwired code; the repo's own rules forbid it.
3. **Client-side physics/layout knobs in `ui/unified-viz.html`** for the global view — once LayoutAuthority owns positions, client simulation code is dead weight and a foot-gun.
4. **Any client-resident full adjacency index** in the UI JS (the thing that kills Obsidian's *local* graph at 130k notes).

## 4. ANTI-PATTERNS (with citations)

1. **Whole-graph render / whole-graph client model.** Killed Obsidian (freeze at 130k even depth-1 local; ~25k practical ceiling per moderator), classic Logseq ("unusably slow" at ~3.5k pages, issue #2089), Dendron (official docs: slowdowns past "a few hundred notes"; 2m10s load, issue #630), Roam (layout refused above ~600 pages → grid fallback, issue #10), Foam (65–75% of a core at 330 notes, issue #347), Gephi Lite (by design; docs concede "not the same scales, not even closely"). Explicitly *avoided* by Sourcetrail, Sourcegraph, TheBrain, Neo4j Browser/Bloom, Linkurious, Connected Papers, CodeSee — i.e., every tool operating above 10⁵ entities.
2. **Client-side force simulation as layout owner.** First component to break everywhere: sigma FA2 past ~50k edges (Linkurious/sigma comparison), Kumu's multi-minute "jiggly map", Logseq forced to bound its sim to ≤900 nodes and cap draws at 2,200 nodes. Deterministic/server layout is what makes TheBrain, Sourcetrail, CodeSee, OKM, Litmaps feel instant.
3. **Hard caps that discard or refuse.** Graphify raises ValueError at 5,000 nodes (and issue #744: crash path ignoring even its own escape flags); OKM amputates at 100 docs; Bloom's 10k wall forces pagination workarounds. The corpus's better answer: Linkurious supernode badges, Sourcetrail hidden-member counts, Neo4j count-only fallback — defer with exact counts, never drop. This is Cortex's "scientific completeness" requirement already validated in industry.
4. **Uncapped expansion.** Wikipedia Map bounds growth to first-paragraph links (~5–10/click) explicitly to prevent explosion; Linkurious blocks multi-node expansion when a supernode is selected; Neo4j embeds the cap in the Cypher itself. Never expand a node without a query-level LIMIT + refine dialog.
5. **Renderer heroics as the scaling strategy.** WebGL buys exactly one order of magnitude (SVG ~10³ → canvas ~10⁴ → WebGL ~10⁵, per Neo4j/NVL/yFiles/sigma documented thresholds) and does nothing about layout or memory — Obsidian is WebGL and still dies. Architecture (bounded fetch + server layout), not renderer, is the lever.
6. **"Local graph" as a client filter over a fully loaded model.** Obsidian/Quartz/Foam/Kumu-focus all do on-demand *filtering*, not on-demand *fetching* — and all still pay full load+memory cost (Obsidian's local graph freezing at 130k proves filtering doesn't save you). TheBrain's on-demand *fetching* is the pattern that actually scales.

**One-line verdict:** Cortex should be TheBrain's per-click bounded neighborhood query + Sourcetrail's type-bundling with deferred counts + OKM/LayoutAuthority server-owned positions, delivered over the existing SSE skeleton + `/api/graph/node` pair — and the full-snapshot `/api/graph` path, the unrouted `/api/graph/stream`, and all client-side layout must be deleted, because the corpus contains zero survivors of that architecture at Cortex's scale.

---

## Adversarial verification

**Verdict: VERIFIED with 5 minor corrections** — no cited tool contradicts the convergent pattern, the no-discard principle holds with one auditable gap, and all load-bearing claims trace to the corpus or were confirmed in the repo (checked: `layout_authority*.py` exists in `mcp_server/server/`; `graph_snapshot.py` is deleted in the working tree; `http_standalone_graph.py:1415` does say "/api/graph/stream is not routed"; `/api/graph`, `/events`, `/slice`, `/phase`, `/node` are all routed in `http_standalone.py:157-182`; client d3 `forceSimulation` confirmed at `ui/unified/js/workflow_graph.js:147`).

Corrections:

1. **GitNexus ~5k is a memory ceiling, not a force-simulation ceiling.** The corpus states GitNexus's binding constraint is "WASM/browser memory during parse+graph build, not the Sigma WebGL draw." Citing it alongside Graphify as "client force-graph dies at ~5k" conflates two failure mechanisms; the synthesis's broader point (two independent ~5k caps) survives, but the mechanism attribution should say "whole-graph-in-client dies at ~5k" rather than "force-graph."

2. **Connected Papers "precomputed layout" is corpus-marked inference, not established fact.** The corpus says identical cached layouts "imply server-side or deterministic precomputed layout"; renderer is explicitly unknown (closed source). The synthesis presents it as a proven instance of the server-layout model — should be downgraded to "consistent with" or rest the precedent on OKM (which IS documented: server-side ordination) and TheBrain (deterministic zones).

3. **"sigma FA2 degrades past ~50k edges" comes from a vendor-biased source.** The corpus twice flags this number as a Linkurious (Ogma competitor) measurement to "treat skeptically." The synthesis states it three times as flat fact; it should carry the caveat, especially since it's used as the anchor for "layout breaks before the renderer."

4. **GitNexus tree/circles modes are miscategorized as a "navigation-first deterministic layout" example.** GitNexus is a regime-(a) load-it-all tool whose default is force mode; the corpus's claim is that force simulation appears *only* in load-it-all tools, with all focus-based tools deterministic. Listing GitNexus's alternate modes alongside TheBrain/Sourcetrail weakens that clean dichotomy without contradicting it — drop it from the list.

5. **Deleting both the full-snapshot `/api/graph` AND whole-world `/api/graph/slice` paging removes the only complete-enumeration path — a latent no-silent-discard violation at the audit level.** Every node remains reachable via search + `/api/graph/node` + named subgraphs, so no *view* discards data, but "exact counts, defer don't drop" is only verifiable if some paginated full-enumeration (or export) endpoint survives. The corpus itself supports this: Graphify keeps `--no-viz` + JSON/MCP query access beyond its cap, and GitNexus keeps backend mode. Recommend: keep one cursor-paged enumeration endpoint (or a bulk export), just never wire it to the renderer. (Minor sub-point: the client physics to delete lives in `ui/unified/js/workflow_graph.js`, not `ui/unified-viz.html` itself — and that file's own comments show a server-tile path already exists that "DRAWS — it does not simulate," so the deletion target is the simulation branch, not the whole file.)

All other checked claims are faithful to the corpus: Neo4j 300/100 caps with count-only fallback, Linkurious 50/10k thresholds and Selective Expand, Sourcetrail `bundleNodesByType`/`getGraphForActiveTokenIds`/BucketLayouter, TheBrain 572K/1.12M + O(degree) plex + search-as-long-jump, Obsidian 25K moderator quote + 130k depth-1 local-graph freeze (proving filtering ≠ fetching), Graphify `MAX_NODES_FOR_VIZ=5_000` + issue #744, Logseq ≤900-node sim / 2,200-node draw cap, OKM hard-100, Wikipedia Map 5–10/click, Roam ~600-page grid fallback, Dendron few-hundred official limit, Foam ~330-note CPU burn, and the SVG→canvas→WebGL one-order-of-magnitude ladder.