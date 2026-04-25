"""
Migration script — Fase 13.e Unit Tests
=========================================
Verifies the `scripts/migrate_string_topics` helper that auto-rewrites
legacy `listen "topic"` (Fase 11.d) into the typed canonical form
(Fase 13).  The migrator must:
  - convert each unique string topic to a PascalCase identifier
  - generate `channel <Name> { ... }` declarations at the file top
  - rewrite `listen "..."` to `listen <Name>` per occurrence
  - leave already-typed listeners untouched
  - produce output that passes `axon check --strict`
"""

from __future__ import annotations

import pytest

from scripts.migrate_string_topics import (
    build_channel_block,
    find_string_topics,
    migrate,
    rewrite_listens,
    topic_to_identifier,
)


# ────────────────────────────────────────────────────────────────────
# topic_to_identifier — PascalCase conversion
# ────────────────────────────────────────────────────────────────────


class TestTopicToIdentifier:

    @pytest.mark.parametrize("topic,ident", [
        ("orders.created", "OrdersCreated"),
        ("orders-cancelled", "OrdersCancelled"),
        ("order/v2/created", "OrderV2Created"),
        ("kebab_case", "KebabCase"),
        ("simple", "Simple"),
        ("UPPER", "UPPER"),
        ("multi.word.dotted.topic", "MultiWordDottedTopic"),
    ])
    def test_pascal_case_conversion(self, topic, ident):
        assert topic_to_identifier(topic) == ident

    def test_starts_with_digit_gets_t_prefix(self):
        """An identifier cannot start with a digit; we prefix `T`."""
        assert topic_to_identifier("123.events").startswith("T")

    def test_empty_topic_returns_fallback(self):
        assert topic_to_identifier("") == "DeprecatedTopic"

    def test_only_separators_returns_fallback(self):
        assert topic_to_identifier("...---___") == "DeprecatedTopic"


# ────────────────────────────────────────────────────────────────────
# find_string_topics — collects unique topics in source order
# ────────────────────────────────────────────────────────────────────


class TestFindStringTopics:

    def test_finds_single_topic(self):
        src = 'daemon D() { listen "orders" as ev { step S { ask: "x" } } }'
        assert find_string_topics(src) == ["orders"]

    def test_collects_unique_only(self):
        src = '''
daemon D() {
  listen "a" as e1 { step S { ask: "p" } }
  listen "a" as e2 { step S { ask: "p" } }
  listen "b" as e3 { step S { ask: "p" } }
}
'''
        assert find_string_topics(src) == ["a", "b"]

    def test_preserves_first_appearance_order(self):
        src = '''
daemon D() {
  listen "gamma" as e1 { step S { ask: "p" } }
  listen "alpha" as e2 { step S { ask: "p" } }
  listen "beta" as e3 { step S { ask: "p" } }
}
'''
        assert find_string_topics(src) == ["gamma", "alpha", "beta"]

    def test_ignores_typed_listeners(self):
        """`listen Identifier` (no quotes) must not be matched."""
        src = '''
channel Typed { message: Order }
daemon D() {
  listen Typed as e1 { step S { ask: "p" } }
  listen "legacy" as e2 { step S { ask: "p" } }
}
'''
        assert find_string_topics(src) == ["legacy"]

    def test_no_topics_returns_empty(self):
        src = '''
type Order { id: String }
channel C { message: Order }
'''
        assert find_string_topics(src) == []


# ────────────────────────────────────────────────────────────────────
# rewrite_listens — text-level substitution
# ────────────────────────────────────────────────────────────────────


class TestRewriteListens:

    def test_replaces_listen_string_with_identifier(self):
        src = '''daemon D() {
  goal: "x"
  listen "orders.created" as ev { step S { ask: "p" } }
}
'''
        out = rewrite_listens(src, ["orders.created"])
        assert 'listen "orders.created"' not in out
        assert "listen OrdersCreated" in out

    def test_does_not_touch_other_strings(self):
        """`goal: \"x\"` must remain a string after migration."""
        src = '''daemon D() {
  goal: "x"
  listen "topic" as ev { step S { ask: "p" } }
}
'''
        out = rewrite_listens(src, ["topic"])
        assert 'goal: "x"' in out  # unchanged

    def test_handles_multiple_distinct_topics(self):
        src = '''daemon D() {
  listen "alpha" as e1 { step S { ask: "p" } }
  listen "beta" as e2 { step S { ask: "p" } }
}
'''
        out = rewrite_listens(src, ["alpha", "beta"])
        assert "listen Alpha" in out
        assert "listen Beta" in out


# ────────────────────────────────────────────────────────────────────
# build_channel_block — declaration generator
# ────────────────────────────────────────────────────────────────────


class TestBuildChannelBlock:

    def test_emits_one_block_per_topic(self):
        block = build_channel_block(["a", "b"])
        assert "channel A {" in block
        assert "channel B {" in block

    def test_default_message_is_bytes(self):
        block = build_channel_block(["a"])
        assert "message: Bytes" in block

    def test_custom_message_overrides_default(self):
        block = build_channel_block(["a"], message="Order")
        assert "message: Order" in block
        assert "message: Bytes" not in block

    def test_uses_double_slash_comments(self):
        """Axon comment syntax is `//`, not `#`."""
        block = build_channel_block(["a"])
        assert block.startswith("//")
        assert "#" not in block.split("\n")[0]

    def test_generated_block_includes_review_hint(self):
        """Auto-generated channels need human review of message/qos/etc."""
        block = build_channel_block(["a"])
        assert "Review" in block


# ────────────────────────────────────────────────────────────────────
# migrate — full-pipeline integration with axon check
# ────────────────────────────────────────────────────────────────────


class TestMigrate:

    def test_migrate_returns_topics_list(self):
        src = '''daemon D() {
  goal: "x"
  listen "alpha" as e1 { step S { ask: "p" } }
  listen "beta" as e2 { step S { ask: "p" } }
}
'''
        new_src, topics = migrate(src)
        assert topics == ["alpha", "beta"]
        assert "channel Alpha" in new_src
        assert "channel Beta" in new_src
        assert "listen Alpha" in new_src
        assert "listen Beta" in new_src

    def test_migrate_no_op_on_clean_source(self):
        """A program with no string topics is returned unchanged."""
        src = '''type Order { id: String }
channel C { message: Order }
'''
        new_src, topics = migrate(src)
        assert new_src == src
        assert topics == []

    def test_migrated_source_passes_axon_check(self):
        """The migrated output is valid AXON and clean under --strict."""
        from axon.compiler import frontend

        src = '''daemon D() {
  goal: "x"
  listen "orders.created" as ev { step S { ask: "p" } }
  listen "orders.cancelled" as ev2 { step S { ask: "p" } }
}
'''
        new_src, topics = migrate(src)
        assert len(topics) == 2

        result = frontend.check_source(new_src, "<migrated>")
        # Errors must be empty; no warnings either (typed-canonical form).
        errors = [d for d in result.diagnostics if d.severity == "error"]
        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert errors == [], [e.message for e in errors]
        assert warnings == [], [w.message for w in warnings]

    def test_migrate_preserves_typed_listeners_unchanged(self):
        """Typed (already-canonical) listeners must survive untouched."""
        src = '''type Order { id: String }
channel Already { message: Order }
daemon Mixed() {
  goal: "x"
  listen Already as canonical { step S { ask: "p" } }
  listen "legacy" as legacy_ev { step S { ask: "p" } }
}
'''
        new_src, topics = migrate(src)
        assert topics == ["legacy"]
        assert "listen Already as canonical" in new_src
        assert "listen Legacy as legacy_ev" in new_src

    def test_migrate_with_custom_qos_and_lifetime(self):
        src = '''daemon D() {
  listen "broadcast.bus" as ev { step S { ask: "p" } }
}
'''
        new_src, _ = migrate(src, qos="broadcast", lifetime="persistent")
        assert "qos: broadcast" in new_src
        assert "lifetime: persistent" in new_src
