"""GET /api/quadtree — gzipped Arrow IPC of every node's (id, x, y, kind).

The client builds a quadtree (e.g. flatbush) from this payload to
resolve hover/click locally in O(log N) without a server roundtrip.
``id`` and ``kind`` are dictionary-encoded so the wire size is
dominated by two Float32 columns at 1M nodes ≈ 8 MB raw / ~3-4 MB
gzipped.
"""

from __future__ import annotations

import gzip
import json


def serve(handler, store) -> None:
    try:
        import pyarrow as pa
        import pyarrow.ipc as ipc
        from mcp_server.infrastructure import layout_pg_store
    except ImportError as exc:
        body = (
            f'{{"status":"error","reason":"viz_tile_extra_missing","detail":"{exc}"}}'
        ).encode("utf-8")
        handler.send_response(503)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return

    # Stream the layout in keyset-paged chunks and write one Arrow record
    # batch per chunk, so peak RAM is one chunk (not 4 Python lists over every
    # node — the high-cardinality node_id strings dominate at 1M+ nodes). The
    # Arrow IPC frame itself stays bounded (~8 MB / 1M) and is the actual wire
    # payload, so buffering it to set Content-Length is fine.
    schema = pa.schema(
        [
            ("id", pa.dictionary(pa.int32(), pa.string())),
            ("x", pa.float32()),
            ("y", pa.float32()),
            ("kind", pa.dictionary(pa.int32(), pa.string())),
        ]
    )
    sink = pa.BufferOutputStream()
    wrote_any = False
    with ipc.new_stream(sink, schema) as writer:
        for chunk in layout_pg_store.iter_positions_chunked(store):
            batch = pa.record_batch(
                {
                    "id": pa.array([r[0] for r in chunk]).dictionary_encode(),
                    "x": pa.array([r[1] for r in chunk], type=pa.float32()),
                    "y": pa.array([r[2] for r in chunk], type=pa.float32()),
                    "kind": pa.array([r[3] for r in chunk]).dictionary_encode(),
                },
                schema=schema,
            )
            writer.write_batch(batch)
            wrote_any = True

    if not wrote_any:
        body = json.dumps({"status": "error", "reason": "no_layout"}).encode("utf-8")
        handler.send_response(503)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return

    arrow_buf = sink.getvalue().to_pybytes()
    body = gzip.compress(arrow_buf, compresslevel=6)

    handler.send_response(200)
    handler.send_header("Content-Type", "application/vnd.apache.arrow.stream")
    handler.send_header("Content-Encoding", "gzip")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "max-age=60")
    handler.end_headers()
    handler.wfile.write(body)
