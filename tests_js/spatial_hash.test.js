// node:test suite for the canvas hit-test spatial hash (ADR-009 node:test).
//   node --test tests_js/spatial_hash.test.js
//
// Two acceptance signals from tasks/borrow-from-supermemory-handover.md §4:
//   (1) hit-test correctness — spatial grid returns the SAME node as the
//       O(N) linear reverse-scan it replaces, over random graphs/points;
//   (2) measured frame-time improvement on a >5k-node graph (spatial path
//       faster than linear). Reported and asserted in the perf test below.
const { test } = require('node:test');
const assert = require('node:assert');
const { SpatialHash } = require('../ui/unified/js/spatial_hash.js');

// Cortex KIND_RADIUS spread (workflow_graph.js): symbol 2 … domain 26, plus the
// nodeRadius bump (≤6) and the +2 hit pad → radii in [4, 34], all < cell 200.
const RADII = [2, 5, 6, 7, 8, 9, 10, 12, 14, 16, 26];
function radiusOf(n) { return n.r + 2; }

// Deterministic PRNG (mulberry32) — no Date.now()/Math.random reliance; fixed
// seed keeps the suite reproducible.
function rng(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function makeNodes(n, rand, span) {
  const nodes = [];
  for (let i = 0; i < n; i++) {
    nodes.push({
      id: 'n' + i,
      x: (rand() - 0.5) * span,
      y: (rand() - 0.5) * span,
      r: RADII[(rand() * RADII.length) | 0],
    });
  }
  return nodes;
}

// The exact O(N) hit-test from render_canvas.js: reverse scan, topmost (highest
// index, drawn last) wins.
function linearHit(nodes, x, y) {
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i], r = radiusOf(n);
    const dx = n.x - x, dy = n.y - y;
    if (dx * dx + dy * dy <= r * r) return n;
  }
  return null;
}

// The spatial-grid hit-test from render_canvas.js findNode(): 3x3 candidates,
// precise circle test, topmost-wins via max index.
function spatialHit(hash, nodes, x, y) {
  const cand = hash.queryNeighborhood(x, y);
  let best = null, bestIdx = -1;
  for (let c = 0; c < cand.length; c++) {
    const idx = cand[c], n = nodes[idx], r = radiusOf(n);
    const dx = n.x - x, dy = n.y - y;
    if (dx * dx + dy * dy <= r * r && idx > bestIdx) { best = n; bestIdx = idx; }
  }
  return best;
}

test('spatial hit-test is identical to the linear reverse-scan it replaces', () => {
  const rand = rng(1234);
  const nodes = makeNodes(3000, rand, 8000);   // dense → overlaps exercise tiebreak
  const hash = new SpatialHash(200).build(nodes);
  let hits = 0;
  for (let q = 0; q < 20000; q++) {
    const x = (rand() - 0.5) * 8200, y = (rand() - 0.5) * 8200;
    const lin = linearHit(nodes, x, y);
    const spa = spatialHit(hash, nodes, x, y);
    assert.strictEqual(spa ? spa.id : null, lin ? lin.id : null,
      `mismatch at (${x.toFixed(1)},${y.toFixed(1)}): spatial=${spa && spa.id} linear=${lin && lin.id}`);
    if (lin) hits++;
  }
  assert.ok(hits > 100, `expected meaningful hit coverage, got ${hits}`);
});

test('exact-centre and just-inside/just-outside radius boundary agree', () => {
  const nodes = [
    { id: 'a', x: 0, y: 0, r: 10 },
    { id: 'b', x: 199, y: 199, r: 10 },     // adjacent cell
    { id: 'c', x: 201, y: 0, r: 10 },       // next cell over, near boundary
  ];
  const hash = new SpatialHash(200).build(nodes);
  const at = (x, y) => { const h = spatialHit(hash, nodes, x, y); return h ? h.id : null; };
  for (const n of nodes) {
    const r = radiusOf(n);
    assert.strictEqual(at(n.x, n.y), n.id, 'centre hit');
    assert.strictEqual(at(n.x + r - 0.01, n.y), n.id, 'just inside radius hits');
    assert.strictEqual(at(n.x + r + 0.5, n.y), null, 'just outside radius misses');
  }
});

test('frame-time: spatial hit-test beats linear on a >5k-node graph', () => {
  const rand = rng(99);
  const N = 6000;                              // > 5k acceptance threshold
  const nodes = makeNodes(N, rand, 12000);
  const hash = new SpatialHash(200).build(nodes);
  const Q = 5000;
  const pts = [];
  for (let i = 0; i < Q; i++) pts.push([(rand() - 0.5) * 12200, (rand() - 0.5) * 12200]);

  const hp = require('node:perf_hooks').performance;
  let t = hp.now();
  for (let i = 0; i < Q; i++) linearHit(nodes, pts[i][0], pts[i][1]);
  const linMs = hp.now() - t;

  t = hp.now();
  for (let i = 0; i < Q; i++) spatialHit(hash, nodes, pts[i][0], pts[i][1]);
  const spaMs = hp.now() - t;

  const speedup = linMs / spaMs;
  console.log(`\n  [${N} nodes, ${Q} queries] linear=${linMs.toFixed(1)}ms  ` +
              `spatial=${spaMs.toFixed(1)}ms  speedup=${speedup.toFixed(1)}x  ` +
              `(per-query: ${(linMs / Q * 1000).toFixed(2)}µs → ${(spaMs / Q * 1000).toFixed(2)}µs)`);
  assert.ok(speedup > 2, `expected >2x speedup on ${N} nodes, got ${speedup.toFixed(1)}x`);
});
