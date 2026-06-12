// Live-build SSE subscriber — watches the graph grow on first visit.
//
// Counterpart to mcp_server/server/graph_event_stream.py. Opens an
// EventSource on /api/graph/events, parses each `batch` event, and
// calls JUG.appendGraphDelta with the nodes/edges. appendGraphDelta
// dedupes by id, so a reconnect-with-Last-Event-ID replay is safe.
//
// Public API:
//   GraphEventStream.start({onProgress?, onDone?})
//     Opens the EventSource (or returns the existing one if already
//     open). Idempotent.
//
//   GraphEventStream.stop()
//     Closes the EventSource and stops appending. Used when the user
//     switches away from the Graph tab, or when the build emits
//     `done` (we close ourselves there too).
(function () {
  var es = null;
  var stats = { batches: 0, nodes: 0, edges: 0, lastLabel: '', startedAt: 0, doneAt: 0 };
  var callbacks = { onProgress: null, onDone: null };

  function _ensureLastData() {
    if (!window.JUG) return false;
    if (!JUG.state.lastData) {
      JUG.state.lastData = {
        nodes: [], edges: [], links: [],
        meta: { schema: 'workflow_graph.v1', source: 'live-stream' },
      };
    }
    return true;
  }

  // ── Slim wire decode ──
  // The server emits positional arrays (see _slim_node/_slim_edge in
  // http_standalone_graph.py):
  //   node: [id, kind, domain_id, x, y, label, color, heat, extra_ids]
  //   edge: [source, target, kind, weight]
  // Nulls mean "absent" — fields are only assigned when present so the
  // renderer's fallbacks (palette by kind, label→id, default weight)
  // engage. Full records stay server-side; the detail panel drills
  // /api/graph/node on click.
  function _decodeNode(a) {
    if (!Array.isArray(a)) return a;  // already an object (tests, legacy)
    var n = { id: a[0], kind: a[1], type: a[1] };
    if (a[2] != null) n.domain_id = a[2];
    if (a[3] != null) n.x = a[3];
    if (a[4] != null) n.y = a[4];
    if (a[5] != null) n.label = a[5];
    if (a[6] != null) n.color = a[6];
    if (a[7] != null) n.heat = a[7];
    if (a[8] != null) n.extra_domain_ids = a[8];
    return n;
  }

  function _decodeEdge(a) {
    if (!Array.isArray(a)) return a;
    var e = { source: a[0], target: a[1], kind: a[2], type: a[2] };
    if (a[3] != null) e.weight = a[3];
    return e;
  }

  function _onBatchEvent(ev) {
    var data;
    try { data = JSON.parse(ev.data); } catch (e) {
      console.warn('[stream] bad batch event:', e);
      return;
    }
    if (!_ensureLastData()) return;
    var nodes = (data.nodes || []).map(_decodeNode);
    var edges = (data.edges || []).map(_decodeEdge);
    if (typeof JUG.appendGraphDelta === 'function') {
      JUG.appendGraphDelta(nodes, edges);
    }
    stats.batches += 1;
    stats.nodes += nodes.length;
    stats.edges += edges.length;
    stats.lastLabel = data.label || stats.lastLabel;
    if (callbacks.onProgress) {
      try {
        callbacks.onProgress({
          batches: stats.batches,
          nodes: stats.nodes,
          edges: stats.edges,
          label: stats.lastLabel,
          off: data.off, n_total: data.n_total, e_total: data.e_total,
        });
      } catch (_) {}
    }
  }

  function _onDoneEvent(ev) {
    stats.doneAt = Date.now();
    var elapsed = stats.doneAt - stats.startedAt;
    console.log(
      '[stream] done — ' + stats.batches + ' batches, ' +
      stats.nodes + ' nodes, ' + stats.edges + ' edges in ' +
      Math.round(elapsed) + ' ms'
    );
    if (callbacks.onDone) {
      try { callbacks.onDone({ ...stats, elapsed_ms: elapsed }); } catch (_) {}
    }
    stop();
  }

  function _onError(ev) {
    // EventSource auto-reconnects on transient errors using the last
    // received id, so we don't need to do anything except log. If the
    // server is genuinely down, repeated reconnects will keep failing —
    // bounded by the browser, not by us.
    console.warn('[stream] error (will retry):', ev);
  }

  function start(opts) {
    opts = opts || {};
    callbacks.onProgress = opts.onProgress || null;
    callbacks.onDone = opts.onDone || null;
    if (es) {
      // Already open — just update callbacks.
      return es;
    }
    stats.startedAt = Date.now();
    es = new EventSource('/api/graph/events');
    es.addEventListener('batch', _onBatchEvent);
    es.addEventListener('done', _onDoneEvent);
    es.addEventListener('error', _onError);
    console.log('[stream] EventSource opened on /api/graph/events');
    return es;
  }

  function stop() {
    if (es) {
      try { es.close(); } catch (_) {}
      es = null;
      console.log('[stream] EventSource closed');
    }
  }

  function isOpen() {
    return es !== null && es.readyState !== EventSource.CLOSED;
  }

  function getStats() {
    return Object.assign({}, stats, { open: isOpen() });
  }

  window.GraphEventStream = { start: start, stop: stop, isOpen: isOpen, stats: getStats };
})();
