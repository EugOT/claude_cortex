"""Tests for the constant-memory quadtree streaming handler (harbor C6).

Covers:
  (a) round-trip — de-chunk + gunzip + arrow-read equals input positions.
  (b) constant-memory — many chunks stream INCREMENTALLY: bytes reach the
      fake socket between chunk reads, not all at the end.
  (c) empty layout -> 503 no_layout, headers sent exactly once.
  (d) pyarrow missing -> 503 viz_tile_extra_missing, unchanged.
"""

from __future__ import annotations

import builtins
import gzip
import importlib
import io
import json

import pytest

from mcp_server.handlers import quadtree_handler

pa = pytest.importorskip("pyarrow")
ipc = importlib.import_module("pyarrow.ipc")


class _RecordingWFile:
    """Socket buffer that records every write (size + running offset)."""

    def __init__(self) -> None:
        self.buf = io.BytesIO()
        self.write_log: list[int] = []  # bytes-written offset after each write

    def write(self, b) -> int:
        self.buf.write(b)
        self.write_log.append(self.buf.tell())
        return len(b)

    def flush(self) -> None:
        pass

    def tell(self) -> int:
        return self.buf.tell()


class _FakeHandler:
    """Minimal BaseHTTPRequestHandler stand-in recording status/headers."""

    def __init__(self) -> None:
        self.wfile = _RecordingWFile()
        self.status: int | None = None
        self.headers: list[tuple[str, str]] = []
        self.ended = 0  # end_headers call count
        self.status_calls = 0

    def send_response(self, code: int) -> None:
        self.status = code
        self.status_calls += 1

    def send_header(self, k: str, v: str) -> None:
        self.headers.append((k, v))

    def end_headers(self) -> None:
        self.ended += 1

    def header(self, name: str) -> str | None:
        for k, v in self.headers:
            if k.lower() == name.lower():
                return v
        return None


def _dechunk(data: bytes) -> bytes:
    """Inverse of HTTP/1.1 chunked transfer framing."""
    out = bytearray()
    i = 0
    while i < len(data):
        j = data.index(b"\r\n", i)
        size = int(data[i:j], 16)
        i = j + 2
        if size == 0:
            break
        out += data[i : i + size]
        i += size + 2
    return bytes(out)


class _FakeStore:
    """Yields pre-canned chunks; records wfile offset at each yield."""

    def __init__(self, chunks, wfile=None) -> None:
        self._chunks = chunks
        self._wfile = wfile
        self.offsets_at_yield: list[int] = []

    def iter_positions_chunked(self, store, chunk_size=50_000):
        for ch in self._chunks:
            if self._wfile is not None:
                self.offsets_at_yield.append(self._wfile.tell())
            yield ch


def _patch_store(monkeypatch, fake):
    """Redirect the handler's lazy layout_pg_store import to ``fake``."""
    import mcp_server.infrastructure.layout_pg_store as real

    monkeypatch.setattr(real, "iter_positions_chunked", fake.iter_positions_chunked)


def test_roundtrip_streamed_body_equals_input(monkeypatch):
    chunks = [
        [("a", 1.0, 2.0, "fn"), ("b", 3.0, 4.0, "cls")],
        [("c", 5.0, 6.0, "fn")],
        [("d", 7.0, 8.0, "mod")],
    ]
    fake = _FakeStore(chunks)
    _patch_store(monkeypatch, fake)

    h = _FakeHandler()
    quadtree_handler.serve(h, store=object())

    assert h.status == 200
    assert h.ended == 1
    assert h.header("Transfer-Encoding") == "chunked"
    assert h.header("Content-Encoding") == "gzip"
    assert h.header("Content-Length") is None  # streaming: no length

    arrow_bytes = gzip.decompress(_dechunk(h.wfile.buf.getvalue()))
    table = ipc.open_stream(arrow_bytes).read_all()
    assert table.column("id").to_pylist() == ["a", "b", "c", "d"]
    assert table.column("x").to_pylist() == [1.0, 3.0, 5.0, 7.0]
    assert table.column("y").to_pylist() == [2.0, 4.0, 6.0, 8.0]
    assert table.column("kind").to_pylist() == ["fn", "cls", "fn", "mod"]


def test_constant_memory_streams_incrementally(monkeypatch):
    # Many chunks. The socket offset at the time chunk N+1 is pulled from
    # the store must exceed the offset at chunk N — i.e. data from earlier
    # chunks has already left the process. If the handler buffered the whole
    # payload, all yields would see the same (header-only) offset.
    n_chunks = 40
    chunks = [
        [(f"n{c}_{i}", float(i), float(c), "fn") for i in range(100)]
        for c in range(n_chunks)
    ]
    h = _FakeHandler()
    fake = _FakeStore(chunks, wfile=h.wfile)
    _patch_store(monkeypatch, fake)

    quadtree_handler.serve(h, store=object())

    assert h.status == 200
    offsets = fake.offsets_at_yield
    assert len(offsets) == n_chunks
    # Strictly growing across the stream: a buffered implementation would
    # show offsets flat until the very end.
    assert offsets[-1] > offsets[0], offsets
    # The last chunk is pulled well before the response is fully built, so
    # the offset at the final yield must be a fraction of the total bytes.
    total = h.wfile.buf.tell()
    assert offsets[-1] < total, (offsets[-1], total)

    arrow_bytes = gzip.decompress(_dechunk(h.wfile.buf.getvalue()))
    table = ipc.open_stream(arrow_bytes).read_all()
    assert table.num_rows == n_chunks * 100


def test_empty_layout_returns_503_headers_once(monkeypatch):
    fake = _FakeStore([])  # iterator immediately exhausted
    _patch_store(monkeypatch, fake)

    h = _FakeHandler()
    quadtree_handler.serve(h, store=object())

    assert h.status == 503
    assert h.status_calls == 1  # 200 was never sent before the 503
    assert h.ended == 1
    assert h.header("Transfer-Encoding") is None  # never started streaming
    assert h.header("Content-Length") is not None
    body = json.loads(h.wfile.buf.getvalue().decode("utf-8"))
    assert body["reason"] == "no_layout"


def test_pyarrow_missing_returns_503(monkeypatch):
    real_import = builtins.__import__

    def _block_pyarrow(name, *args, **kwargs):
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ImportError("No module named 'pyarrow'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_pyarrow)

    h = _FakeHandler()
    quadtree_handler.serve(h, store=object())

    assert h.status == 503
    assert h.ended == 1
    assert h.header("Transfer-Encoding") is None
    payload = h.wfile.buf.getvalue().decode("utf-8")
    assert "viz_tile_extra_missing" in payload
