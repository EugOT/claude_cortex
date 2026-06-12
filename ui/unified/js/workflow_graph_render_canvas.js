// Cortex — Workflow Graph: Canvas renderer (used for nodes > threshold).
// Exposes JUG._wfg.mountCanvas(container, ctx, sim, panel, width, height).
(function () {
  function mountCanvas(container, ctx, sim, panel, width, height) {
    var d3 = window.d3;
    var wfg = window.JUG._wfg;
    var canvas = document.createElement('canvas');
    canvas.className = 'wfg-canvas';
    canvas.width = width; canvas.height = height;
    canvas.style.width = width + 'px'; canvas.style.height = height + 'px';
    container.appendChild(canvas);
    var g = canvas.getContext('2d');
    var transform = d3.zoomIdentity;
    var hoverId = null, selectedId = null;

    // ── Static-scene fast path ──
    // In static server-layout mode (ctx._world set by mount()) node
    // positions NEVER change, so the naive painter — 271k edge strokes
    // + 144k arcs on EVERY zoom/hover event (~0.5 s/frame, measured
    // 2026-06-12: the galaxy rendered but could not be zoomed or
    // clicked) — is replaced by:
    //   * an offscreen BASE layer rendered once per transform-settle;
    //     zoom/pan blit the image with the relative transform (~1 ms),
    //     re-rendering crisply ~150 ms after the gesture pauses;
    //   * a uniform spatial GRID for O(1) hit-testing instead of a
    //     linear scan per mousemove;
    //   * a per-node EDGE index so hover/selection overlays draw only
    //     the focused node's edges, not the full edge set.
    // Display-level LOD only: viewport culling decides what is drawn
    // for the current view — every node and edge stays in the scene,
    // the counts, and the hit index.
    var STATIC = !!(ctx && ctx._world);
    var base = null, baseT = null, baseTimer = null;
    var grid = null, GRID_CELL = 24;     // px; ≥ 2× max node radius

    function buildStaticIndexes() {
      grid = {};
      for (var i = 0; i < ctx.nodes.length; i++) {
        var n = ctx.nodes[i];
        var key = ((n.x / GRID_CELL) | 0) + ':' + ((n.y / GRID_CELL) | 0);
        (grid[key] || (grid[key] = [])).push(n);
      }
    }

    function gridFind(x, y) {
      var cx = (x / GRID_CELL) | 0, cy = (y / GRID_CELL) | 0;
      var bestN = null, bestD = Infinity;
      for (var dx = -1; dx <= 1; dx++) {
        for (var dy = -1; dy <= 1; dy++) {
          var cell = grid[(cx + dx) + ':' + (cy + dy)];
          if (!cell) continue;
          for (var i = 0; i < cell.length; i++) {
            var n = cell[i]; var r = wfg.nodeRadius(n) + 2;
            var ddx = n.x - x, ddy = n.y - y;
            var d2 = ddx * ddx + ddy * ddy;
            if (d2 <= r * r && d2 < bestD) { bestD = d2; bestN = n; }
          }
        }
      }
      return bestN;
    }

    function renderBase() {
      if (!base) base = document.createElement('canvas');
      base.width = canvas.width; base.height = canvas.height;
      var bg = base.getContext('2d');
      bg.clearRect(0, 0, base.width, base.height);
      bg.save();
      bg.translate(transform.x, transform.y);
      bg.scale(transform.k, transform.k);
      var k = transform.k || 1;
      // World-visible rect (+pad) for culling.
      var pad = 60 / k;
      var wx0 = (-transform.x) / k - pad, wy0 = (-transform.y) / k - pad;
      var wx1 = (canvas.width - transform.x) / k + pad;
      var wy1 = (canvas.height - transform.y) / k + pad;
      var hideStructural = k < 0.9;
      var STRUCT = { in_domain: 1, tool_used_file: 1, invoked_skill: 1,
                     triggered_hook: 1, spawned_agent: 1, command_in_hub: 1 };
      // Edges first (under the dots).
      for (var i = 0; i < ctx.edges.length; i++) {
        var e = ctx.edges[i];
        if (filterKeep && !(filterKeep[e.source.id] && filterKeep[e.target.id])) continue;
        if (hideStructural && !e._crossDomain && STRUCT[e.kind]) continue;
        var sx = e.source.x, sy = e.source.y, tx = e.target.x, ty = e.target.y;
        if ((sx < wx0 || sx > wx1 || sy < wy0 || sy > wy1) &&
            (tx < wx0 || tx > wx1 || ty < wy0 || ty > wy1)) continue;
        if (e._crossDomain) {
          bg.strokeStyle = 'rgba(200,150,255,0.12)'; bg.lineWidth = 0.4;
        } else {
          bg.strokeStyle = 'rgba(120,180,200,0.04)';
          bg.lineWidth = 0.4 + (e.weight != null ? e.weight : 0.3) * 0.5;
        }
        bg.beginPath(); bg.moveTo(sx, sy); bg.lineTo(tx, ty); bg.stroke();
      }
      // Nodes batched by fill color: one path + one fill per color
      // (per-node beginPath/fill was the dominant cost).
      var byColor = {};
      for (var j = 0; j < ctx.nodes.length; j++) {
        var n = ctx.nodes[j];
        if (n.x < wx0 || n.x > wx1 || n.y < wy0 || n.y > wy1) continue;
        var col = wfg.nodeColor(n);
        var dimmed = filterKeep && !filterKeep[n.id];
        var bucket = dimmed ? col + '|dim' : col;
        (byColor[bucket] || (byColor[bucket] = [])).push(n);
      }
      for (var colKey in byColor) {
        var list = byColor[colKey];
        var dim = colKey.slice(-4) === '|dim';
        bg.fillStyle = dim ? colKey.slice(0, -4) : colKey;
        bg.globalAlpha = dim ? 0.04 : 1.0;
        bg.beginPath();
        for (var m = 0; m < list.length; m++) {
          var nn = list[m]; var r = wfg.nodeRadius(nn);
          bg.moveTo(nn.x + r, nn.y);
          bg.arc(nn.x, nn.y, r, 0, Math.PI * 2);
        }
        bg.fill();
      }
      bg.globalAlpha = 1.0;
      // Hub labels (legible-at-zoom display rule, same as legacy path).
      if (k > 0.5) {
        bg.fillStyle = '#E8E4D8';
        bg.textAlign = 'center'; bg.textBaseline = 'bottom';
        for (var q = 0; q < ctx.nodes.length; q++) {
          var ln = ctx.nodes[q];
          if (ln.kind !== 'domain' && ln.kind !== 'tool_hub') continue;
          if (filterKeep && !filterKeep[ln.id]) continue;
          if (ln.x < wx0 || ln.x > wx1 || ln.y < wy0 || ln.y > wy1) continue;
          bg.font = (ln.kind === 'domain' ? '12px ' : '10px ') + "'Inter Tight', system-ui, sans-serif";
          bg.fillText(wfg.labelOf(ln), ln.x, ln.y - wfg.nodeRadius(ln) - 3);
        }
      }
      bg.restore();
      baseT = { k: transform.k, x: transform.x, y: transform.y };
    }

    var _labelFetched = {};
    function fetchHubLabels() {
      var pending = [];
      for (var i = 0; i < ctx.nodes.length; i++) {
        var n = ctx.nodes[i];
        if ((n.kind === 'domain' || n.kind === 'tool_hub') &&
            !n.label && !_labelFetched[n.id]) {
          _labelFetched[n.id] = 1;
          pending.push(n);
        }
      }
      if (!pending.length) return;
      var left = pending.length;
      pending.forEach(function (n) {
        fetch('/api/graph/node?id=' + encodeURIComponent(n.id) + '&n_limit=1')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (p) {
            if (p && p.record && p.record.label) n.label = p.record.label;
          })
          .catch(function () {})
          .then(function () {
            left--;
            if (left === 0 && baseT) { renderBase(); draw(); }
          });
      });
    }

    function scheduleBaseRerender() {
      if (baseTimer) clearTimeout(baseTimer);
      // Re-render crisply once the gesture pauses. 150 ms: long enough
      // that a wheel stream doesn't re-render per tick, short enough
      // to feel immediate; interaction tradeoff, no external source.
      baseTimer = setTimeout(function () { baseTimer = null; renderBase(); draw(); }, 150);
    }

    function drawStaticOverlay() {
      var focusId = hoverId || selectedId;
      if (!focusId) return;
      var fn = ctx.byId[focusId];
      if (!fn) return;
      g.save();
      g.translate(transform.x, transform.y);
      g.scale(transform.k, transform.k);
      // Edges exist ONLY here: drawn for the selected node from its
      // on-demand /api/graph/node neighborhood (rows [other_id, kind,
      // label, edge_kind, direction]), positions resolved against the
      // dots already on screen. The stream carries no edges at all.
      g.strokeStyle = 'rgba(240,210,100,0.85)';
      g.lineWidth = 1.4 / (transform.k || 1);
      var rows = fn._neighbors || [];
      for (var i = 0; i < rows.length; i++) {
        var other = ctx.byId[rows[i][0]];
        if (!other || other.x == null) continue;
        g.beginPath(); g.moveTo(fn.x, fn.y);
        g.lineTo(other.x, other.y); g.stroke();
      }
      var r = wfg.nodeRadius(fn);
      g.fillStyle = wfg.nodeColor(fn);
      g.beginPath(); g.arc(fn.x, fn.y, r, 0, Math.PI * 2); g.fill();
      g.lineWidth = 2 / (transform.k || 1); g.strokeStyle = '#F0D870';
      g.beginPath(); g.arc(fn.x, fn.y, r + 1, 0, Math.PI * 2); g.stroke();
      g.restore();
    }

    function drawStatic() {
      if (!baseT) { buildStaticIndexes(); renderBase(); fetchHubLabels(); }
      g.clearRect(0, 0, canvas.width, canvas.height);
      if (transform.k === baseT.k && transform.x === baseT.x && transform.y === baseT.y) {
        g.drawImage(base, 0, 0);
      } else {
        var r = transform.k / baseT.k;
        g.setTransform(r, 0, 0, r,
          transform.x - r * baseT.x, transform.y - r * baseT.y);
        g.drawImage(base, 0, 0);
        g.setTransform(1, 0, 0, 1, 0, 0);
        scheduleBaseRerender();
      }
      drawStaticOverlay();
    }

    var sel = d3.select(canvas);
    sel.call(d3.zoom().scaleExtent([0.15, 6]).on('zoom', function (ev) {
      transform = ev.transform; draw();
    })).on('dblclick.zoom', null);
    sel.call(d3.drag()
      .subject(function (ev) {
        var p = transform.invert([ev.x, ev.y]);
        return findNode(p[0], p[1]);
      })
      .on('start', function (ev) {
        if (!ev.subject) return;
        if (!ev.active) sim.alphaTarget(0.2).restart();
        ev.subject.fx = ev.subject.x; ev.subject.fy = ev.subject.y;
      })
      .on('drag', function (ev) {
        if (!ev.subject) return;
        var p = transform.invert([ev.x, ev.y]);
        ev.subject.fx = p[0]; ev.subject.fy = p[1];
      })
      .on('end', function (ev) {
        if (!ev.subject) return;
        if (!ev.active) sim.alphaTarget(0);
        if (ev.subject.kind !== 'domain') { ev.subject.fx = null; ev.subject.fy = null; }
        // Static: the dragged node's dot is baked into the base layer
        // at its old position — re-render so it lands where dropped.
        if (STATIC && baseT) { buildStaticIndexes(); renderBase(); draw(); }
      }));

    canvas.addEventListener('mousemove', function (ev) {
      var rect = canvas.getBoundingClientRect();
      var p = transform.invert([ev.clientX - rect.left, ev.clientY - rect.top]);
      var n = findNode(p[0], p[1]);
      var next = n ? n.id : null;
      if (next !== hoverId) {
        hoverId = next;
        canvas.style.cursor = n ? 'pointer' : 'default';
        // Show the rich tooltip toolbox for the hovered node (was only
        // highlighting before — nothing actually appeared). tooltip.js
        // owns the card + positioning; we just feed it the node.
        if (window.JUG && JUG._tooltip) {
          if (n) JUG._tooltip.show(n); else JUG._tooltip.hide();
        }
        draw();
      }
    });
    canvas.addEventListener('mouseleave', function () {
      hoverId = null;
      if (window.JUG && JUG._tooltip) JUG._tooltip.hide();
      draw();
    });
    canvas.addEventListener('click', function (ev) {
      var rect = canvas.getBoundingClientRect();
      var p = transform.invert([ev.clientX - rect.left, ev.clientY - rect.top]);
      var n = findNode(p[0], p[1]);
      if (n) {
        selectedId = n.id;
        // Static: first paint shows JUST the node (empty neighbor set,
        // never a client-side join); the on-demand call below fills
        // the relational sections when it returns.
        if (STATIC && !n._neighbors) n._neighbors = [];
        panel.show(n, ctx);
        if (STATIC) {
          // ONE panel, fed by ONE on-demand call: the slim wire only
          // carries render fields, so the full record is fetched on
          // click and merged into the node, then the SAME panel
          // refreshes. graph:selectNode is NOT emitted here — it
          // opened detail_panel.js on top of this panel (two stacked
          // panels, user report 2026-06-12).
          fetch('/api/graph/node?id=' + encodeURIComponent(n.id))
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (p) {
              if (p && p.found && selectedId === n.id) {
                Object.assign(n, p.record);
                // Server-provided neighborhood: the panel's relational
                // sections render from this, never from a client-side
                // join over the full edge copy.
                n._neighbors = p.neighbors || [];
                n._neighborTotal = p.neighbor_total || n._neighbors.length;
                panel.show(n, ctx);
              }
            })
            .catch(function () {});
        } else if (window.JUG && typeof JUG.emit === 'function') {
          // Trace view (simulated path) keeps the global selection
          // event — trace.js expands the clicked node's children.
          try { JUG.emit('graph:selectNode', n); } catch (_e) {}
        }
      } else {
        selectedId = null;
        panel.hide();
        if (!STATIC && window.JUG && typeof JUG.emit === 'function') {
          try { JUG.emit('graph:deselectNode'); } catch (_e) {}
        }
      }
      draw();
    });

    function findNode(x, y) {
      if (STATIC && grid) return gridFind(x, y);
      for (var i = ctx.nodes.length - 1; i >= 0; i--) {
        var n = ctx.nodes[i]; var r = wfg.nodeRadius(n) + 2;
        var dx = n.x - x, dy = n.y - y;
        if (dx * dx + dy * dy <= r * r) return n;
      }
      return null;
    }

    // Edge rendering — density-aware.
    // Root cause of the "grey rectangle" users see: each domain has hundreds
    // of in-domain tool_hub→file edges that originate at a single tool_hub
    // point and fan into a bounded angular sector at FILE_R. Canvas 2D
    // additively stacks the stroke alpha across the wedge, so the fan
    // saturates into a solid-looking cyan trapezoid. With 16k+ edges across
    // ~8 domains the trapezoids cover half the viewport. Fix:
    //   (1) drop base alpha to 0.04 so stacking does NOT saturate;
    //   (2) skip in-domain structural edges when zoomed out — the hierarchy
    //       is already visible from the slot layout (node arrangement);
    //   (3) keep cross-domain threads (they're the whole point of the map)
    //       and keep active/focus highlighting so selection still works.
    var STRUCTURAL_KINDS = { in_domain: 1, tool_used_file: 1, invoked_skill: 1,
                             triggered_hook: 1, spawned_agent: 1, command_in_hub: 1 };
    function drawEdges(focusId) {
      var k = transform.k || 1;
      var hideStructural = k < 0.9 && !focusId;
      for (var i = 0; i < ctx.edges.length; i++) {
        var e = ctx.edges[i];
        var dim = focusId && e.source.id !== focusId && e.target.id !== focusId;
        var act = focusId && (e.source.id === focusId || e.target.id === focusId);
        // When zoomed out and nothing is selected, skip the structural fan.
        if (hideStructural && !e._crossDomain && STRUCTURAL_KINDS[e.kind]) continue;
        if (e._crossDomain) {
          g.strokeStyle = act ? 'rgba(240,210,100,0.85)' : (dim ? 'rgba(200,150,255,0.03)' : 'rgba(200,150,255,0.12)');
          g.lineWidth = act ? 1.2 : 0.4;
        } else {
          g.strokeStyle = act ? 'rgba(240,210,100,0.9)' : (dim ? 'rgba(120,180,200,0.02)' : 'rgba(120,180,200,0.04)');
          g.lineWidth = act ? 1.6 : (0.4 + (e.weight != null ? e.weight : 0.3) * 0.5);
        }
        g.beginPath(); g.moveTo(e.source.x, e.source.y); g.lineTo(e.target.x, e.target.y); g.stroke();
      }
    }
    function drawNodes(focusId, adj) {
      // At low zoom, symbols blur into a cloud and drawing each one
      // wastes ~10 ms per frame with 10k+ of them. Skip them below
      // a threshold — the domain/file scaffolding conveys shape.
      // Symbols form the dense cloud that makes the graph look "alive"
      // in the target screenshot. Drawing 10k+ circles at 60 fps costs
      // ~10 ms/frame on desktop — well within budget — so we always
      // draw them regardless of zoom. (Skipping them at zoom<0.4 was
      // hiding the entire cloud at default fit and making the graph
      // look empty.)
      var zoom = transform.k || 1;
      var skipSymbols = zoom < 0.08;   // effectively always show
      for (var j = 0; j < ctx.nodes.length; j++) {
        var n = ctx.nodes[j];
        if (skipSymbols && n.kind === 'symbol' && !focusId) continue;
        var r = wfg.nodeRadius(n);
        var isFocus = focusId === n.id;
        var isDim = focusId && n.id !== focusId && !adj[n.id];
        g.globalAlpha = isDim ? 0.15 : 1.0;
        g.fillStyle = wfg.nodeColor(n);
        g.beginPath(); g.arc(n.x, n.y, r, 0, Math.PI * 2); g.fill();
        if (isFocus) { g.lineWidth = 2; g.strokeStyle = '#F0D870'; g.stroke(); }
        if ((n.kind === 'domain' || n.kind === 'tool_hub') && transform.k > 0.5) {
          g.globalAlpha = isDim ? 0.3 : 0.95;
          g.fillStyle = '#E8E4D8';
          g.font = (n.kind === 'domain' ? '12px ' : '10px ') + "'Inter Tight', system-ui, sans-serif";
          g.textAlign = 'center'; g.textBaseline = 'bottom';
          g.fillText(wfg.labelOf(n), n.x, n.y - r - 3);
        }
        g.globalAlpha = 1.0;
      }
    }
    function drawShells() {
      if (!ctx.shells) return;
      for (var di = 0; di < ctx.domains.length; di++) {
        var d = ctx.domains[di];
        var a = ctx.anchors[d.id];
        if (!a) continue;
        // L1/L2/L3 dashed full circles
        var palette = { L1: 'rgba(255,180,100,0.18)', L2: 'rgba(120,220,200,0.18)', L3: 'rgba(120,180,250,0.14)' };
        g.setLineDash([3, 5]); g.lineWidth = 1;
        for (var k = 0; k < ctx.shells.length; k++) {
          var lv = ctx.shells[k];
          g.strokeStyle = palette[lv.key] || 'rgba(160,150,140,0.12)';
          g.beginPath(); g.arc(a.x, a.y, lv.r, 0, Math.PI * 2); g.stroke();
        }
        g.setLineDash([]);
        // L4/L5 arcs (solid, colored)
        var sidePalette = { L4: 'rgba(244,63,94,0.5)', L5: 'rgba(192,112,208,0.5)' };
        var outward = Math.atan2(a.y - ctx.cy, a.x - ctx.cx);
        for (var s = 0; s < ctx.sideShells.length; s++) {
          var sv = ctx.sideShells[s];
          var mid = outward + sv.angle;
          var half = Math.PI / 4;
          g.strokeStyle = sidePalette[sv.key] || 'rgba(160,150,140,0.3)';
          g.lineWidth = 1.5;
          g.beginPath(); g.arc(a.x, a.y, sv.r, mid - half, mid + half); g.stroke();
        }
        // Level tokens (L1..L5)
        if (transform.k > 0.35) {
          g.font = "9px 'JetBrains Mono', monospace";
          g.textAlign = 'center'; g.textBaseline = 'bottom';
          var labelPalette = {
            L1: 'rgba(255,180,100,0.7)', L2: 'rgba(120,220,200,0.7)', L3: 'rgba(120,180,250,0.55)',
            L4: 'rgba(244,63,94,0.9)',   L5: 'rgba(192,112,208,0.9)',
          };
          var outA = Math.atan2(a.y - ctx.cy, a.x - ctx.cx);
          if (Math.hypot(a.x - ctx.cx, a.y - ctx.cy) < 5) outA = -Math.PI / 2;
          for (var m = 0; m < ctx.shells.length; m++) {
            var lvl = ctx.shells[m];
            g.fillStyle = labelPalette[lvl.key] || 'rgba(160,150,140,0.6)';
            g.fillText(lvl.key, a.x + lvl.r * Math.cos(outA), a.y + lvl.r * Math.sin(outA) - 4);
          }
          for (var n = 0; n < ctx.sideShells.length; n++) {
            var slv = ctx.sideShells[n]; var sideMid = outA + slv.angle;
            g.fillStyle = labelPalette[slv.key] || 'rgba(160,150,140,0.8)';
            g.fillText(slv.key, a.x + slv.r * Math.cos(sideMid), a.y + slv.r * Math.sin(sideMid) - 4);
          }
        }
      }
    }

    function draw() {
      if (STATIC) { drawStatic(); return; }
      g.save();
      g.clearRect(0, 0, canvas.width, canvas.height);
      g.translate(transform.x, transform.y); g.scale(transform.k, transform.k);
      var focusId = hoverId || selectedId;
      var adj = focusId ? ctx.adj[focusId] || {} : {};
      drawShells();
      drawEdges(focusId);
      drawNodes(focusId, adj);
      g.restore();
    }
    sim.on('tick', draw);

    function fitToContent() {
      var pad = 60;
      var r = (ctx.baseR || 400) + 240 + pad;
      var w = canvas.width, h = canvas.height;
      var cx = ctx.cx || w / 2, cy = ctx.cy || h / 2;
      var k = Math.min(w / (2 * r), h / (2 * r), 1);
      var tx = w / 2 - cx * k, ty = h / 2 - cy * k;
      transform = d3.zoomIdentity.translate(tx, ty).scale(k);
      sel.call(d3.zoom().transform, transform);
      draw();
    }
    setTimeout(fitToContent, 80);

    var filterKeep = null;    // null = show all; map of id → bool otherwise
    function applyFilter(pred, fctx) {
      if (typeof pred !== 'function') {
        filterKeep = null;
        if (STATIC && baseT) renderBase();
        draw();
        return;
      }
      filterKeep = {};
      for (var i = 0; i < fctx.nodes.length; i++) {
        var n = fctx.nodes[i];
        try { if (pred(n, fctx)) filterKeep[n.id] = true; }
        catch (_) { filterKeep[n.id] = true; }
      }
      // Static: the filter changes what the base layer shows — one
      // full re-render, then blits stay cheap.
      if (STATIC && baseT) renderBase();
      draw();
    }
    // Patch drawEdges + drawNodes via closure: filterKeep gates visibility.
    var origDrawEdges = drawEdges, origDrawNodes = drawNodes;
    drawEdges = function (focusId) {
      if (!filterKeep) return origDrawEdges(focusId);
      var k = transform.k || 1;
      var hideStructural = k < 0.9 && !focusId;
      for (var i = 0; i < ctx.edges.length; i++) {
        var e = ctx.edges[i];
        if (!(filterKeep[e.source.id] && filterKeep[e.target.id])) continue;
        var dim = focusId && e.source.id !== focusId && e.target.id !== focusId;
        var act = focusId && (e.source.id === focusId || e.target.id === focusId);
        // Same structural-fan suppression as the unfiltered path.
        if (hideStructural && !e._crossDomain && STRUCTURAL_KINDS[e.kind]) continue;
        if (e._crossDomain) {
          g.strokeStyle = act ? 'rgba(240,210,100,0.85)' : (dim ? 'rgba(200,150,255,0.03)' : 'rgba(200,150,255,0.12)');
          g.lineWidth = act ? 1.2 : 0.4;
        } else {
          g.strokeStyle = act ? 'rgba(240,210,100,0.9)' : (dim ? 'rgba(120,180,200,0.02)' : 'rgba(120,180,200,0.04)');
          g.lineWidth = act ? 1.6 : (0.4 + (e.weight != null ? e.weight : 0.3) * 0.5);
        }
        g.beginPath(); g.moveTo(e.source.x, e.source.y); g.lineTo(e.target.x, e.target.y); g.stroke();
      }
    };
    drawNodes = function (focusId, adj) {
      if (!filterKeep) return origDrawNodes(focusId, adj);
      // Symbols form the dense cloud that makes the graph look "alive"
      // in the target screenshot. Drawing 10k+ circles at 60 fps costs
      // ~10 ms/frame on desktop — well within budget — so we always
      // draw them regardless of zoom. (Skipping them at zoom<0.4 was
      // hiding the entire cloud at default fit and making the graph
      // look empty.)
      var zoom = transform.k || 1;
      var skipSymbols = zoom < 0.08;   // effectively always show
      for (var j = 0; j < ctx.nodes.length; j++) {
        var n = ctx.nodes[j];
        if (skipSymbols && n.kind === 'symbol' && !focusId) continue;
        var kept = !!filterKeep[n.id];
        var r = wfg.nodeRadius(n);
        var isFocus = focusId === n.id;
        var isDim = !kept || (focusId && n.id !== focusId && !adj[n.id]);
        g.globalAlpha = kept ? (isDim ? 0.06 : 1.0) : 0.04;
        g.fillStyle = wfg.nodeColor(n);
        g.beginPath(); g.arc(n.x, n.y, r, 0, Math.PI * 2); g.fill();
        if (isFocus) { g.lineWidth = 2; g.strokeStyle = '#F0D870'; g.stroke(); }
        if (kept && (n.kind === 'domain' || n.kind === 'tool_hub') && transform.k > 0.5) {
          g.globalAlpha = isDim ? 0.3 : 0.95;
          g.fillStyle = '#E8E4D8';
          g.font = (n.kind === 'domain' ? '12px ' : '10px ') + "'Inter Tight', system-ui, sans-serif";
          g.textAlign = 'center'; g.textBaseline = 'bottom';
          g.fillText(wfg.labelOf(n), n.x, n.y - r - 3);
        }
        g.globalAlpha = 1.0;
      }
    };

    return {
      destroy: function () { if (canvas.parentNode) canvas.parentNode.removeChild(canvas); },
      resize: function (w, h) {
        canvas.width = w; canvas.height = h;
        canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
        fitToContent();
      },
      selectId: function (id) { var n = ctx.byId[id]; if (n) { selectedId = id; panel.show(n, ctx); draw(); } },
      fit: fitToContent,
      applyFilter: applyFilter,
      // Static mode: rebuild hit-grid + edge index + base layer after
      // the mount's append() pushed new nodes (they are invisible and
      // unclickable until the base re-renders).
      refreshBase: function () {
        if (!STATIC) return;
        buildStaticIndexes();
        renderBase();
        draw();
        fetchHubLabels();
      },
    };
  }

  window.JUG = window.JUG || {};
  window.JUG._wfg = window.JUG._wfg || {};
  window.JUG._wfg.mountCanvas = mountCanvas;
})();
