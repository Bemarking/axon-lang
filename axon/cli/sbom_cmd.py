"""
axon sbom — emit a Software Bill of Materials for an .axon program.

Produces the `SupplyChainSBOM` JSON artifact described in ESK §6.6
(paper Fase 6).  Deterministic: same source ⇒ same program_hash,
enabling reproducible-build audits.

Exit codes:
  0 — SBOM generated successfully
  1 — program has compile errors (SBOM not generated)
  2 — file not found or I/O error
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

from axon.cli.display import format_cli_path, safe_text
from axon.compiler import frontend
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.runtime.esk import generate_sbom


def cmd_sbom(args: Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(
            safe_text(f"X File not found: {format_cli_path(path)}", sys.stdout),
            file=sys.stderr,
        )
        return 2

    source = path.read_text(encoding="utf-8")
    result = frontend.check_source(source, str(path))
    if result.diagnostics:
        print(
            safe_text(
                f"X {path.name} has {len(result.diagnostics)} compile error(s) — "
                f"cannot generate SBOM. Run 'axon check' for details.",
                sys.stderr,
            ),
            file=sys.stderr,
        )
        return 1

    tree = Parser(Lexer(source).tokenize()).parse()
    ir = IRGenerator().generate(tree)
    sbom = generate_sbom(ir)
    payload = sbom.to_dict()

    output = getattr(args, "output", None)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        print(safe_text(f"OK SBOM written to {format_cli_path(Path(output))}", sys.stdout))
    else:
        print(text)
    return 0
