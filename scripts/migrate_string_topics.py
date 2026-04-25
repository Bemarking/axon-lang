"""
migrate_string_topics — Fase 13.e migration helper.

Auto-rewrites legacy `listen "topic"` (Fase 11.d, Pre-Fase 13) into
the typed canonical form `listen <ChannelName>` introduced by Fase 13,
inserting `channel` declarations at the top of the file so the result
type-checks under `axon check --strict`.

Schedule (D4, paper §1.2):
  v1.4.x  — string topics legal but emit deprecation warning
  v2.0    — string topics removed (compile error)

This script is the migration bridge.  It is conservative:
  - reads the source as plain text and edits in place via regex;
  - generates a default `message: Bytes` schema unless overridden via
    --message <T>; downstream review should refine each channel's
    message type, qos, lifetime, persistence, and shield gating;
  - re-runs `axon check` on the output to verify cleanliness.

Usage:
    python -m scripts.migrate_string_topics path/to/file.axon
    python -m scripts.migrate_string_topics path/to/file.axon --in-place
    python -m scripts.migrate_string_topics path/to/file.axon \\
        --message Order --qos exactly_once

By default writes the migrated source to stdout; --in-place overwrites
the input file (a `.bak` backup is created alongside it).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterator

# Match `listen` followed by a STRING literal and an optional `as alias`.
# Captures the topic between the quotes.  Axon comments use `//` and
# `/* */`; we don't strip them because the `\blisten` keyword anchor
# rules out accidental matches in normal prose comments.
_LISTEN_STR_RE = re.compile(
    r'(\blisten\s+)"([^"\\]*(?:\\.[^"\\]*)*)"',
    flags=re.MULTILINE,
)


def topic_to_identifier(topic: str) -> str:
    """Convert a string topic to a PascalCase identifier.

    Examples:
        "orders.created" → "OrdersCreated"
        "orders-cancelled" → "OrdersCancelled"
        "order/v2/created" → "OrderV2Created"
        "kebab_case" → "KebabCase"
    """
    parts = re.split(r"[^A-Za-z0-9]+", topic.strip())
    parts = [p for p in parts if p]
    if not parts:
        return "DeprecatedTopic"
    cleaned = "".join(p[:1].upper() + p[1:] for p in parts)
    if not cleaned[0].isalpha():
        cleaned = "T" + cleaned
    return cleaned


def find_string_topics(source: str) -> list[str]:
    """Return unique string topics encountered, in order of first appearance."""
    seen: dict[str, None] = {}
    for match in _LISTEN_STR_RE.finditer(source):
        topic = match.group(2)
        if topic not in seen:
            seen[topic] = None
    return list(seen)


def build_channel_block(
    topics: list[str],
    *,
    message: str = "Bytes",
    qos: str = "at_least_once",
    lifetime: str = "affine",
) -> str:
    """Generate the prelude of `channel <Name> { ... }` declarations."""
    lines: list[str] = [
        "// ─── Fase 13 migration — auto-generated channel declarations ───",
        "// Review each channel: refine `message:`, `qos:`, `lifetime:`,",
        "// `persistence:`, and add `shield: <ShieldName>` if you intend to",
        "// `publish` this channel (D8 — paper §3.4).",
    ]
    for topic in topics:
        ident = topic_to_identifier(topic)
        lines.extend([
            "",
            f"channel {ident} {{",
            f"  message: {message}",
            f"  qos: {qos}",
            f"  lifetime: {lifetime}",
            "}",
        ])
    lines.append("")
    lines.append("// ─── End of auto-generated channels ───")
    lines.append("")
    return "\n".join(lines) + "\n"


def rewrite_listens(source: str, topics: list[str]) -> str:
    """Replace each `listen "topic"` with `listen <Identifier>`."""
    mapping = {t: topic_to_identifier(t) for t in topics}

    def replace(match: re.Match) -> str:
        prefix, topic = match.group(1), match.group(2)
        ident = mapping[topic]
        # Strip trailing whitespace from prefix so we don't double-space.
        return f"{prefix.rstrip()} {ident}"

    return _LISTEN_STR_RE.sub(replace, source)


def migrate(
    source: str,
    *,
    message: str = "Bytes",
    qos: str = "at_least_once",
    lifetime: str = "affine",
) -> tuple[str, list[str]]:
    """Apply migration; return (new_source, list_of_migrated_topics).

    If no string topics are present, returns (source, []) unchanged.
    """
    topics = find_string_topics(source)
    if not topics:
        return source, []

    prelude = build_channel_block(
        topics, message=message, qos=qos, lifetime=lifetime,
    )
    rewritten = rewrite_listens(source, topics)
    return prelude + rewritten, topics


def _verify(source: str) -> tuple[bool, list[str]]:
    """Re-run the frontend on the migrated source.  Returns (ok, msgs)."""
    try:
        from axon.compiler import frontend
    except ImportError:
        return True, ["(axon.compiler not importable — skipping verification)"]
    result = frontend.check_source(source, "<migrated>")
    msgs: list[str] = []
    for d in result.diagnostics:
        loc = f":{d.line}" if getattr(d, "line", 0) else ""
        msgs.append(f"  {d.severity}{loc}: {d.message}")
    return result.ok and not [d for d in result.diagnostics
                              if d.severity == "warning"], msgs


def _argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="migrate_string_topics",
        description=(
            "Rewrite legacy `listen \"topic\"` to the Fase 13 typed form "
            "`channel <Name> { … } / listen <Name>`."
        ),
    )
    p.add_argument("file", help="Path to .axon source file")
    p.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file (creates <file>.bak first).",
    )
    p.add_argument(
        "--message",
        default="Bytes",
        help="Default message schema for generated channels (default: Bytes).",
    )
    p.add_argument(
        "--qos",
        default="at_least_once",
        choices=[
            "at_most_once", "at_least_once", "exactly_once",
            "broadcast", "queue",
        ],
        help="Default QoS for generated channels.",
    )
    p.add_argument(
        "--lifetime",
        default="affine",
        choices=["linear", "affine", "persistent"],
        help="Default lifetime for generated channels.",
    )
    p.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the post-migration `axon check` verification.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _argparser().parse_args(argv)
    path = Path(args.file)

    if not path.exists():
        print(f"✗ File not found: {path}", file=sys.stderr)
        return 2

    source = path.read_text(encoding="utf-8")
    rewritten, topics = migrate(
        source,
        message=args.message,
        qos=args.qos,
        lifetime=args.lifetime,
    )

    if not topics:
        print(
            f"✓ {path.name} — no string-topic listeners found; nothing to do.",
            file=sys.stderr,
        )
        return 0

    if not args.no_verify:
        ok, msgs = _verify(rewritten)
        if not ok:
            print(
                f"✗ {path.name} — migration produced unclean source:",
                file=sys.stderr,
            )
            for m in msgs:
                print(m, file=sys.stderr)
            print(
                "\nDiagnostics above. Run with --no-verify to inspect the "
                "raw output anyway.",
                file=sys.stderr,
            )
            return 1

    if args.in_place:
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(source, encoding="utf-8")
        path.write_text(rewritten, encoding="utf-8")
        print(
            f"✓ {path.name} — migrated {len(topics)} topic(s); "
            f"backup at {backup.name}",
            file=sys.stderr,
        )
        for t in topics:
            print(f"  {t!r} → {topic_to_identifier(t)}", file=sys.stderr)
        return 0

    sys.stdout.write(rewritten)
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
