"""Tests for mcp_server.shared.string_distance.

Reference values for Jaro / Jaro-Winkler are the canonical literature examples
(Winkler 1990 and the standard record-linkage test set).
"""

import math

from mcp_server.shared.string_distance import (
    jaro_similarity,
    jaro_winkler_similarity,
    osa_distance,
)


class TestJaro:
    def test_canonical_values(self):
        assert math.isclose(jaro_similarity("MARTHA", "MARHTA"), 0.9444, abs_tol=1e-4)
        assert math.isclose(jaro_similarity("DWAYNE", "DUANE"), 0.8222, abs_tol=1e-4)
        assert math.isclose(jaro_similarity("DIXON", "DICKSONX"), 0.7667, abs_tol=1e-4)

    def test_identical(self):
        assert jaro_similarity("postgres", "postgres") == 1.0

    def test_disjoint(self):
        assert jaro_similarity("abc", "xyz") == 0.0

    def test_empty(self):
        assert jaro_similarity("", "x") == 0.0
        assert jaro_similarity("", "") == 1.0


class TestJaroWinkler:
    def test_canonical_values(self):
        # Winkler prefix boost raises the Jaro score for shared prefixes.
        assert math.isclose(
            jaro_winkler_similarity("MARTHA", "MARHTA"), 0.9611, abs_tol=1e-4
        )
        assert math.isclose(
            jaro_winkler_similarity("DWAYNE", "DUANE"), 0.84, abs_tol=1e-4
        )
        assert math.isclose(
            jaro_winkler_similarity("DIXON", "DICKSONX"), 0.8133, abs_tol=1e-4
        )

    def test_prefix_capped_at_four(self):
        # Identical 8-char prefix counts only 4 toward the boost.
        s = jaro_winkler_similarity("abcdefXX", "abcdefYY")
        # jaro is symmetric here; the boost uses prefix=4 not 6.
        jaro = jaro_similarity("abcdefXX", "abcdefYY")
        assert math.isclose(s, jaro + 4 * 0.1 * (1 - jaro), abs_tol=1e-9)

    def test_at_least_jaro(self):
        assert jaro_winkler_similarity("foo", "bar") >= jaro_similarity("foo", "bar")

    def test_in_unit_interval(self):
        for a, b in [("EmbeddingEngine", "EmbedingEngine"), ("x", "y"), ("ab", "abc")]:
            v = jaro_winkler_similarity(a, b)
            assert 0.0 <= v <= 1.0


class TestOsaDistance:
    def test_identical(self):
        assert osa_distance("crane", "crane") == 0

    def test_single_substitution(self):
        assert osa_distance("extractor", "extractar") == 1

    def test_adjacent_transposition(self):
        assert osa_distance("ab", "ba") == 1
        assert osa_distance("converter", "converetr") == 1

    def test_classic_levenshtein(self):
        assert osa_distance("kitten", "sitting") == 3

    def test_empty(self):
        assert osa_distance("", "abc") == 3
        assert osa_distance("abc", "") == 3
        assert osa_distance("", "") == 0
