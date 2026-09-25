from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Mapping, Sequence, TextIO

from .doctor import ERROR, LEVELS, WARNING, run_doctor
from .paths import REPO_ROOT, Environment


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
    out: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="ai-config")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="report problems without changing anything")
    args = parser.parse_args(argv)

    env = Environment.from_env(os.environ if environ is None else environ)
    out = out or sys.stdout
    if args.command == "doctor":
        return _doctor(repo_root or REPO_ROOT, env, out)
    return 2


def _doctor(repo_root: Path, env: Environment, out: TextIO) -> int:
    findings = sorted(run_doctor(repo_root, env), key=lambda finding: LEVELS.index(finding.level))
    for finding in findings:
        print(f"{finding.level:<8} {finding.message}", file=out)
    errors = sum(finding.level == ERROR for finding in findings)
    warnings = sum(finding.level == WARNING for finding in findings)
    print(f"{errors} error(s), {warnings} warning(s)", file=out)
    return 1 if errors else 0
