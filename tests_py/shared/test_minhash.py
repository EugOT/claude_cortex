"""Tests for mcp_server.shared.minhash — MinHash sketches and band-LSH."""

from mcp_server.shared.minhash import MinHash, MinHashLSH, optimal_lsh_params


def _sketch(text: str, k: int = 3, num_perm: int = 128) -> MinHash:
    """MinHash over space-stripped k-gram shingles (mirrors entity_dedup)."""
    s = text.replace(" ", "")
    shingles = {s[i : i + k] for i in range(max(1, len(s) - k + 1))}
    m = MinHash(num_perm=num_perm)
    for sh in shingles:
        m.update(sh.encode("utf-8"))
    return m


class TestMinHash:
    def test_identical_sets_estimate_one(self):
        a = _sketch("embeddingengine")
        b = _sketch("embeddingengine")
        assert a.jaccard(b) == 1.0

    def test_disjoint_sets_estimate_zero(self):
        a = _sketch("postgresql")
        b = _sketch("xyzqwklmn")
        assert a.jaccard(b) == 0.0

    def test_near_duplicate_high_estimate(self):
        a = _sketch("embeddingengine")
        b = _sketch("embedingengine")  # one missing char
        assert a.jaccard(b) >= 0.7

    def test_deterministic_across_instances(self):
        # Fixed RandomState seed → identical sketches for identical input.
        assert list(_sketch("cortex").hashvalues) == list(_sketch("cortex").hashvalues)

    def test_jaccard_mismatched_perm_raises(self):
        import pytest

        with pytest.raises(ValueError):
            MinHash(64).jaccard(MinHash(128))


class TestLshParams:
    def test_bands_times_rows_within_perm(self):
        b, r = optimal_lsh_params(0.7, 128)
        assert b * r <= 128
        assert b >= 1 and r >= 1

    def test_cached_stable(self):
        assert optimal_lsh_params(0.7, 128) == optimal_lsh_params(0.7, 128)


class TestMinHashLSH:
    def test_blocks_near_duplicate(self):
        lsh = MinHashLSH(threshold=0.7, num_perm=128)
        a = _sketch("embeddingengine")
        lsh.insert("a", a)
        probe = _sketch("embedingengine")
        assert "a" in lsh.query(probe)

    def test_does_not_block_unrelated(self):
        lsh = MinHashLSH(threshold=0.7, num_perm=128)
        lsh.insert("a", _sketch("postgresql"))
        assert lsh.query(_sketch("completelyunrelated")) == []

    def test_duplicate_key_raises(self):
        import pytest

        lsh = MinHashLSH(threshold=0.7, num_perm=128)
        m = _sketch("cortex")
        lsh.insert("k", m)
        with pytest.raises(ValueError):
            lsh.insert("k", m)
