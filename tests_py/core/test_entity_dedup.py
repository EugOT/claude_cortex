"""Tests for mcp_server.core.entity_dedup — 3-pass fuzzy entity dedup."""

from mcp_server.core.entity_dedup import (
    DedupResult,
    deduplicate_entities,
)
from mcp_server.core.entity_dedup_filters import (
    affixes_sandwich_difference,
    is_affix_extension,
    is_structural_identifier,
    is_variant_pair,
    normalize_label,
    shared_prefix_masks_difference,
)


def _ent(name, type_="technology", **kw):
    d = {"name": name, "type": type_}
    d.update(kw)
    return d


class TestPassthrough:
    def test_empty(self):
        r = deduplicate_entities([])
        assert isinstance(r, DedupResult)
        assert r.remap == {} and r.survivors == []

    def test_single(self):
        r = deduplicate_entities([_ent("PostgreSQL")])
        assert r.remap == {}
        assert len(r.survivors) == 1

    def test_no_duplicates(self):
        r = deduplicate_entities([_ent("PostgreSQL"), _ent("Redis"), _ent("Kafka")])
        assert r.remap == {}
        assert len(r.survivors) == 3


class TestExactNormPass:
    def test_punctuation_and_space_variants_merge(self):
        ents = [
            _ent("Embedding Engine"),
            _ent("embedding-engine"),
            _ent("EMBEDDING_ENGINE"),
        ]
        r = deduplicate_entities(ents)
        # All three normalize to "embedding engine" → one survivor.
        assert len(r.survivors) == 1
        assert len(r.remap) == 2

    def test_distinct_normals_not_merged(self):
        r = deduplicate_entities([_ent("Embedding Engine"), _ent("Vector Store")])
        assert r.remap == {}


class TestFuzzyPass:
    def test_spacing_variant_merges_across_norm_boundary(self):
        # "EmbeddingEngine" (no space) and "Embedding Engine" have different
        # exact-norms but share all space-stripped shingles → fuzzy merge.
        ents = [_ent("EmbeddingEngine"), _ent("Embedding Engine")]
        r = deduplicate_entities(ents)
        assert len(r.survivors) == 1
        assert len(r.merges) >= 1
        assert any(m.reason == "jaro-winkler" for m in r.merges)

    def test_merge_score_is_float_in_unit_interval(self):
        r = deduplicate_entities([_ent("EmbeddingEngine"), _ent("Embedding Engine")])
        for m in r.merges:
            assert isinstance(m.score, float)
            assert 0.0 <= m.score <= 1.0


class TestBlockers:
    def test_affix_extension_not_merged(self):
        # parseConfig vs parseConfigFile — strict prefix-extension, never merged.
        ents = [_ent("parseConfigStage"), _ent("parseConfigStageFile")]
        r = deduplicate_entities(ents)
        assert r.remap == {}

    def test_affix_extension_predicate(self):
        # Prefix containment.
        assert is_affix_extension("parseconfig", "parseconfigfile")
        # Suffix containment (the benchmark's PgMemoryStore ~ MemoryStore FP).
        assert is_affix_extension("memorystore", "pgmemorystore")
        assert not is_affix_extension("parseconfig", "parseconfar")

    def test_suffix_containment_not_merged(self):
        # Regression: concrete class vs its abstraction must not merge.
        ents = [_ent("PgMemoryStore"), _ent("MemoryStore")]
        r = deduplicate_entities(ents)
        assert r.remap == {}

    def test_variant_pair_predicate(self):
        # SKU/version siblings: same stem, different trailing version token.
        assert is_variant_pair("asr1603", "asr1604")
        assert is_variant_pair("m1", "m2")
        assert not is_variant_pair("cranel", "cranel")
        # Prefix-extensions are NOT variants (caught by the suffix blocker).
        assert not is_variant_pair("cranel", "cranelr")


class TestStructuralIdentifierExemption:
    """Regression for the benchmark's dotted-module-path false positives."""

    def test_predicate(self):
        assert is_structural_identifier("mcp_server.core.engram")
        assert is_structural_identifier("benchmarks/lib/bench_db")
        assert not is_structural_identifier("Node.js")  # single dot = concept
        assert not is_structural_identifier("EmbeddingEngine")

    def test_distinct_module_paths_not_merged(self):
        # mcp_server.core.engram ~ mcp_server.core.replay scored 0.935 on JW;
        # they are distinct modules and must never merge.
        ents = [
            _ent("mcp_server.core.engram"),
            _ent("mcp_server.core.replay"),
            _ent("mcp_server.core.codebase_graph"),
        ]
        r = deduplicate_entities(ents)
        assert r.remap == {}


class TestAffixSandwichGuard:
    def test_blocks_glued_camelcase_middle(self):
        # The benchmark's residual FP: distinct test classes (glued CamelCase),
        # shared prefix "test" + suffix "classification", middle store/core.
        assert affixes_sandwich_difference(
            "teststoreclassification", "testcoreclassification"
        )

    def test_allows_empty_middle(self):
        # One middle empty (affix-only difference) → not blocked.
        assert not affixes_sandwich_difference("embeddingengine", "embedding engine")

    def test_allows_similar_middle(self):
        # Middles themselves similar (typo) → not blocked.
        assert not affixes_sandwich_difference("xx stor yy", "xx store yy")

    def test_distinct_test_classes_not_merged(self):
        ents = [_ent("TestStoreClassification"), _ent("TestCoreClassification")]
        r = deduplicate_entities(ents)
        assert r.remap == {}


class TestSharedPrefixGuard:
    def test_predicate_blocks_dominant_prefix_with_different_tails(self):
        # Long shared prefix, dissimilar remainders → masked difference.
        assert shared_prefix_masks_difference(
            "mcp server core engram", "mcp server core replay"
        )

    def test_predicate_allows_similar_tails(self):
        # Shared prefix but near-identical tails → not masked.
        assert not shared_prefix_masks_difference("embedding engine", "embedding engin")

    def test_predicate_ignores_short_common_prefix(self):
        assert not shared_prefix_masks_difference("alpha", "beta")


class TestTypeScoping:
    def test_different_types_not_merged(self):
        # Same name, different type → different buckets → never compared.
        ents = [
            _ent("TensorFlowKit", type_="technology"),
            _ent("TensorFlowKit", type_="dependency"),
        ]
        r = deduplicate_entities(ents)
        assert r.remap == {}

    def test_code_symbols_exempt(self):
        # function/class types are not fuzzy-eligible (graphify #1205).
        ents = [
            _ent("renderFrame", type_="function"),
            _ent("render Frame", type_="function"),
        ]
        r = deduplicate_entities(ents)
        assert r.remap == {}

    def test_ast_origin_exempt(self):
        # origin='ast_symbol' is exempt even for a fuzzy-eligible type + name.
        ents = [
            _ent("Embedding Engine", origin="ast_symbol"),
            _ent("EmbeddingEngine", origin="ast_symbol"),
        ]
        r = deduplicate_entities(ents)
        assert r.remap == {}

    def test_text_origin_merges(self):
        # Same pair with origin='text_concept' merges as before.
        ents = [
            _ent("Embedding Engine", origin="text_concept"),
            _ent("EmbeddingEngine", origin="text_concept"),
        ]
        r = deduplicate_entities(ents)
        assert len(r.survivors) == 1


class TestWinnerSelection:
    def test_most_mentioned_survives(self):
        ents = [
            _ent("Embedding Engine", mention_count=2, heat=0.3),
            _ent("embedding engine", mention_count=9, heat=0.1),
        ]
        r = deduplicate_entities(ents)
        assert len(r.survivors) == 1
        assert r.survivors[0]["mention_count"] == 9

    def test_remap_points_alias_to_winner(self):
        ents = [
            _ent("Embedding Engine", id=1, mention_count=2),
            _ent("embedding-engine", id=2, mention_count=9),
        ]
        r = deduplicate_entities(ents)
        # id=2 is the more-mentioned winner; id=1 remaps to it.
        assert r.remap == {"1": "2"}


class TestNormalize:
    def test_normalize_label(self):
        assert normalize_label("Embedding-Engine") == "embedding engine"
        assert normalize_label("  HTTP_Client  ") == "http client"
        assert normalize_label(None) == ""
