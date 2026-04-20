"""
axon evidence-package — bundle external-audit evidence for an .axon program.

Assembles a deterministic ZIP containing:
  * MANIFEST.json (per-file SHA-256)
  * program_sbom.json
  * program_dossier.json
  * in_toto_statement.json
  * risk_register.json
  * gap_analysis/<framework>.json
  * control_statements/<framework>.json
  * source/<file>.axon
  * README.md (auditor intake note)

Usage:
    axon evidence-package <file.axon> -o package.zip [--note "..."]

Exit codes:
    0 — package written successfully
    1 — source has compile errors
    2 — file not found / I/O error
"""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

from axon.cli.display import format_cli_path, safe_text
from axon.compiler import frontend
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.runtime.esk import build_evidence_package


def cmd_evidence_package(args: Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(
            safe_text(f"X File not found: {format_cli_path(path)}", sys.stderr),
            file=sys.stderr,
        )
        return 2

    source = path.read_text(encoding="utf-8")
    result = frontend.check_source(source, str(path))
    if result.diagnostics:
        print(
            safe_text(
                f"X {path.name} has {len(result.diagnostics)} compile error(s) — "
                f"cannot assemble evidence package. Run 'axon check' for details.",
                sys.stderr,
            ),
            file=sys.stderr,
        )
        return 1

    tree = Parser(Lexer(source).tokenize()).parse()
    ir = IRGenerator().generate(tree)

    out_arg = getattr(args, "output", None)
    if out_arg:
        out_path = Path(out_arg)
    else:
        out_path = path.with_suffix(".evidence.zip")

    note = getattr(args, "note", "") or ""
    package = build_evidence_package(
        ir,
        source_files={path.name: source},
        auditor_note=note,
    )
    package.write_zip(out_path)

    print(
        safe_text(
            f"OK evidence package written to {format_cli_path(out_path)} "
            f"({len(package.files)} files, {len(package.to_zip_bytes())} bytes)",
            sys.stdout,
        )
    )
    return 0
