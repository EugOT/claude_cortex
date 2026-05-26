"""Python encoder for ZERA bundles over Cortex-shaped graphs.

ZERA is the wire protocol for >1 GB graph payloads. The Cortex viz
server uses this module to serve ``/api/graph.zera``: the cached
workflow graph (``_graph_cache["data"]``) encoded as a single
length-prefixed sequence of zstd-compressed JSON frames.

Frame order in the bundle (each prefixed with its u32-LE length):

    +--------+----------+---------+---------+
    | HELLO  | CODEBOOK | GRAMMAR | PAYLOAD |
    +--------+----------+---------+---------+

HELLO declares the encoding choices (variant, int-ids, zstd level)
so the client can recover the exact decoding strategy without out-of-
band agreement. CODEBOOK carries the per-key value palettes
(low-cardinality enum fields such as ``kind``, ``type``, ``color``,
``domain``, ``symbol_type``) plus id-prefix palette. GRAMMAR is
currently empty for this graph shape (S5 will plug in derivation
rules). PAYLOAD is the actual node + edge stream with palette indices
in place of repeated strings and integer-encoded numeric id suffixes.

Round-trip: ``decode_zera_bundle(encode_graph_to_zera_bundle(g))``
returns a field-by-field equal reconstruction for every key ZERA
tracks. The viz JS decoder applies the exact same algorithm.

This module is import-isolated from the retrieval path. It is only
referenced by ``http_standalone_endpoints.serve_graph_zera`` and the
viz server router; the recall/remember pipeline imports nothing from
here. Touching this module does not affect LongMemEval, LoCoMo, BEAM
scores.

source: docs/protocols/ZERA-spec.md (the ai-automatised-pipeline repo)
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

try:
    import blake3
except ImportError:  # pragma: no cover
    blake3 = None  # type: ignore[assignment]

try:
    import zstandard as zstd
except ImportError:  # pragma: no cover
    zstd = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Codebook discovery
# ---------------------------------------------------------------------------

# Fields on each node that are LOW-CARDINALITY (small enum) — these
# become palette indices in the encoded payload, saving ~10 bytes
# per node per palette after zstd.
_NODE_PALETTE_KEYS: tuple[str, ...] = (
    "kind", "type", "color", "domain", "domain_id", "symbol_type",
)
_EDGE_PALETTE_KEYS: tuple[str, ...] = (
    "kind", "type", "reason",
)

# Cardinality cap — if a field has more than this many distinct values
# it's NOT worth palette-encoding (palette would be bigger than the savings).
_PALETTE_MAX_CARDINALITY = 200


def _discover_palettes(items: list[dict], keys: tuple[str, ...]) -> dict[str, list[str]]:
    """For each key, return the deduplicated, sorted list of values seen
    in ``items``. Skip keys whose cardinality exceeds the cap."""
    out: dict[str, list[str]] = {}
    for k in keys:
        seen: set[str] = set()
        for it in items:
            v = it.get(k)
            if v is None:
                continue
            seen.add(str(v))
            if len(seen) > _PALETTE_MAX_CARDINALITY:
                break
        if 0 < len(seen) <= _PALETTE_MAX_CARDINALITY:
            out[k] = sorted(seen)
    return out


def _id_prefix_palette(nodes: list[dict]) -> list[str]:
    """Common prefixes before the first ``:`` in node ids. Drops ~7 bytes
    per node on Cortex-shaped graphs (memory:, entity:, file:, sym:)."""
    counts: Counter[str] = Counter()
    for n in nodes:
        ident = n.get("id") or ""
        if ":" in ident:
            counts[ident.split(":", 1)[0] + ":"] += 1
    threshold = max(1, len(nodes) // 50)
    return [p for p, c in counts.most_common() if c > threshold]


def build_codebook(graph: dict) -> dict:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    return {
        "node_palettes": _discover_palettes(nodes, _NODE_PALETTE_KEYS),
        "edge_palettes": _discover_palettes(edges, _EDGE_PALETTE_KEYS),
        "id_prefixes": _id_prefix_palette(nodes),
    }


def codebook_content_id(cb: dict) -> str:
    if blake3 is None:
        return "0" * 64
    raw = json.dumps(cb, separators=(",", ":"), sort_keys=True, default=str).encode()
    h = blake3.blake3()
    h.update(len(raw).to_bytes(8, "little"))
    h.update(raw)
    return h.digest().hex()


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def _maybe_int(s: Any) -> Any:
    if isinstance(s, str) and s.isdigit():
        try:
            return int(s)
        except ValueError:
            return s
    return s


def _split_id_prefix(prefixes: list[str], ident: Any) -> tuple[int | None, Any]:
    if not isinstance(ident, str):
        return None, ident
    for i, p in enumerate(prefixes):
        if ident.startswith(p):
            return i, _maybe_int(ident[len(p):])
    return None, _maybe_int(ident)


def _encode_item(
    item: dict,
    palettes: dict[str, list[str]],
    id_prefixes: list[str],
) -> dict:
    out: dict[str, Any] = {}
    palette_idx_cache: dict[str, dict[str, int]] = {
        k: {v: i for i, v in enumerate(vs)} for k, vs in palettes.items()
    }
    for k, v in item.items():
        if v is None:
            continue
        if k == "id":
            p, s = _split_id_prefix(id_prefixes, v)
            out["i"] = s
            if p is not None:
                out["ip"] = p
            continue
        if k == "source":
            p, s = _split_id_prefix(id_prefixes, v)
            out["fs"] = s
            if p is not None:
                out["fp"] = p
            continue
        if k == "target":
            p, s = _split_id_prefix(id_prefixes, v)
            out["ts"] = s
            if p is not None:
                out["tp"] = p
            continue
        if k in palettes:
            idx = palette_idx_cache[k].get(str(v))
            if idx is not None:
                out[f"_{k}"] = idx
                continue
        out[k] = v
    return out


def encode_payload(graph: dict, codebook: dict) -> dict:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    np = codebook["node_palettes"]
    ep = codebook["edge_palettes"]
    ipref = codebook["id_prefixes"]
    return {
        "n": [_encode_item(n, np, ipref) for n in nodes],
        "e": [_encode_item(e, ep, ipref) for e in edges],
    }


# ---------------------------------------------------------------------------
# Bundle packing
# ---------------------------------------------------------------------------

def _zstd_frame(obj: Any, level: int) -> bytes:
    if zstd is None:
        return b""
    # default=str matches the existing /api/graph serializer: live graph
    # nodes carry non-JSON-native values (numpy float32 heat/weight,
    # datetimes) that plain json.dumps rejects with TypeError. Coercing
    # them to strings keeps parity with what the viz already consumes
    # from the JSON endpoint.
    raw = json.dumps(obj, separators=(",", ":"), default=str).encode()
    return zstd.ZstdCompressor(level=level).compress(raw)


def encode_graph_to_zera_bundle(
    graph: dict,
    *,
    graph_id: str | None = None,
    payload_zstd_level: int = 19,
) -> bytes:
    cb = build_codebook(graph)
    payload = encode_payload(graph, cb)

    if graph_id is None and blake3 is not None:
        h = blake3.blake3()
        h.update(len(payload["n"]).to_bytes(8, "little"))
        h.update(json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode())
        graph_id = h.digest().hex()
    elif graph_id is None:
        graph_id = "0" * 64

    hello = {
        "zera_version": "0.0.5",
        "graph_id": graph_id,
        "codebook_id": codebook_content_id(cb),
        "cache_hit": False,
        "encoding": "json",
        "payload_int_ids": True,
        "payload_zstd_level": payload_zstd_level,
        "node_count": len(graph.get("nodes", [])),
        "edge_count": len(graph.get("edges", [])),
    }
    grammar = {"rules": []}

    f_hello = _zstd_frame(hello, 3)
    f_cb = _zstd_frame(cb, 3)
    f_gr = _zstd_frame(grammar, 3)
    f_pl = _zstd_frame(payload, payload_zstd_level)

    return b"".join(
        len(b).to_bytes(4, "little") + b
        for b in (f_hello, f_cb, f_gr, f_pl)
    )


# ---------------------------------------------------------------------------
# Decoder (round-trip verification)
# ---------------------------------------------------------------------------

def decode_zera_bundle(bundle: bytes) -> dict:
    if zstd is None:
        raise RuntimeError("zstandard not available")
    decomp = zstd.ZstdDecompressor()
    frames = []
    pos = 0
    while pos < len(bundle):
        ln = int.from_bytes(bundle[pos:pos + 4], "little")
        pos += 4
        frames.append(decomp.decompress(bundle[pos:pos + ln]))
        pos += ln
    if len(frames) != 4:
        raise ValueError(f"expected 4 frames, got {len(frames)}")
    hello = json.loads(frames[0])
    cb = json.loads(frames[1])
    _grammar = json.loads(frames[2])
    payload = json.loads(frames[3])

    np = cb.get("node_palettes", {})
    ep = cb.get("edge_palettes", {})
    ipref = cb.get("id_prefixes", [])

    def make_id(p: int | None, s: Any) -> str:
        s_str = str(s) if isinstance(s, int) else s
        return f"{ipref[p]}{s_str}" if p is not None else s_str

    def decode_item(it: dict, palettes: dict[str, list[str]], id_key: str) -> dict:
        out: dict[str, Any] = {}
        if id_key == "id":
            out["id"] = make_id(it.get("ip"), it.get("i"))
        elif id_key == "edge":
            out["source"] = make_id(it.get("fp"), it.get("fs"))
            out["target"] = make_id(it.get("tp"), it.get("ts"))
        for k, v in it.items():
            if k in ("i", "ip", "fs", "fp", "ts", "tp"):
                continue
            if k.startswith("_") and k[1:] in palettes:
                out[k[1:]] = palettes[k[1:]][v]
            else:
                out[k] = v
        return out

    nodes = [decode_item(n, np, "id") for n in payload["n"]]
    edges = [decode_item(e, ep, "edge") for e in payload["e"]]
    return {"hello": hello, "nodes": nodes, "edges": edges}
