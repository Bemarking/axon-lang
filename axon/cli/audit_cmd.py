"""
axon audit — gap analysis against external audit frameworks.

Usage:
    axon audit <file.axon> [--framework soc2|iso27001|fips|cc]
                           [-o out.json]

Frameworks:
    soc2      — SOC 2 Type II (AICPA TSC)
    iso27001  — ISO/IEC 27001:2022 (Annex A subset)
    fips      — FIPS 140-3 (CMVP submission readiness)
    cc        — Common Criteria EAL 4+ (SFRs + SARs)
    all       — all four (default)

Exit codes:
    0 — gap analysis generated
    1 — source has compile errors
    2 — file not found
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
from axon.runtime.esk import FrameworkId, analyze_all, analyze_gaps


_FRAMEWORK_ALIASES: dict[str, FrameworkId] = {
    "soc2":      FrameworkId.SOC2_TYPE_II,
    "iso27001":  FrameworkId.ISO_27001,
    "fips":      FrameworkId.FIPS_140_3,
    "cc":        FrameworkId.CC_EAL4_PLUS,
}


def cmd_audit(args: Namespace) -> int:
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
                f"cannot run audit. Run 'axon check' for details.",
                sys.stderr,
            ),
            file=sys.stderr,
        )
        return 1

    tree = Parser(Lexer(source).tokenize()).parse()
    ir = IRGenerator().generate(tree)

    framework_flag = getattr(args, "framework", "all") or "all"
    if framework_flag == "all":
        analyses = analyze_all(ir)
        payload = {
            "schema":     "axon.esk.audit_gap_report.v1",
            "program":    path.name,
            "frameworks": {name: a.to_dict() for name, a in analyses.items()},
            "summary": {
                name: {
                    "readiness_percent": a.readiness_percent,
                    "ready":             a.ready,
                    "total":             a.total_controls,
                    "pending_code":      a.pending_code,
                    "pending_external":  a.pending_external,
                }
                for name, a in analyses.items()
            },
        }
    else:
        if framework_flag not in _FRAMEWORK_ALIASES:
            print(
                safe_text(
                    f"X Unknown framework '{framework_flag}'. "
                    f"Use one of: soc2, iso27001, fips, cc, all.",
                    sys.stderr,
                ),
                file=sys.stderr,
            )
            return 2
        analysis = analyze_gaps(ir, _FRAMEWORK_ALIASES[framework_flag])
        payload = {
            "schema":   "axon.esk.audit_gap_report.v1",
            "program":  path.name,
            "analysis": analysis.to_dict(),
        }

    text = json.dumps(payload, indent=2, sort_keys=True)
    out = getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(
            safe_text(
                f"OK audit report written to {format_cli_path(Path(out))}",
                sys.stdout,
            )
        )
    else:
        print(text)
    return 0
