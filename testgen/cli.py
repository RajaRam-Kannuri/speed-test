"""Command line interface.

    testgen spec    <module>        draft a JSON spec from type hints
    testgen cases   <spec.json>     generate test cases (json / csv / markdown)
    testgen script  <spec.json>     generate a runnable pytest script
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .cases import STRATEGIES, generate_all
from .introspect import spec_from_module
from .oracle import load_module, record_expectations
from .render import FORMATS, render_cases, render_script
from .spec import Spec, SpecError, load_spec


def _write(text: str, output: Optional[str]) -> None:
    if output in (None, "-"):
        sys.stdout.write(text)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"wrote {path}", file=sys.stderr)


def _build_cases(args, spec: Spec):
    cases = generate_all(spec.functions, args.strategy, args.function or None)
    if not cases:
        raise SpecError("no test cases generated (check --function names)")
    if args.record:
        record_expectations(spec, cases)
    return cases


def cmd_spec(args) -> int:
    probe = Spec(module=args.module, functions=[], base_dir=Path.cwd())
    module = load_module(probe)
    spec = spec_from_module(module, args.module, args.function or None)
    if not spec.functions:
        print("no public functions found", file=sys.stderr)
        return 1
    _write(json.dumps(spec.to_dict(), indent=2) + "\n", args.output)
    return 0


def cmd_cases(args) -> int:
    spec = load_spec(args.spec)
    cases = _build_cases(args, spec)
    _write(render_cases(cases, args.format), args.output)
    print(f"{len(cases)} test cases generated", file=sys.stderr)
    return 0


def cmd_script(args) -> int:
    spec = load_spec(args.spec)
    cases = _build_cases(args, spec)
    out_path = None if args.output in (None, "-") else Path(args.output)
    _write(render_script(spec, cases, out_path, Path(args.spec).name), args.output)
    print(f"{len(cases)} test cases written as pytest parameters", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="testgen", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("spec", help="draft a spec from a module's type hints")
    p.add_argument("module", help="path to a .py file or a dotted module name")
    p.add_argument("-f", "--function", action="append", help="only include this function (repeatable)")
    p.add_argument("-o", "--output", help="output file (default: stdout)")
    p.set_defaults(func=cmd_spec)

    def common(p):
        p.add_argument("spec", help="path to a JSON spec")
        p.add_argument("-s", "--strategy", choices=STRATEGIES, default="each",
                       help="how values are combined (default: each)")
        p.add_argument("-f", "--function", action="append", help="only this function (repeatable)")
        p.add_argument("--no-record", dest="record", action="store_false",
                       help="don't execute the target to record expected results")
        p.add_argument("-o", "--output", help="output file (default: stdout)")

    p = sub.add_parser("cases", help="generate test cases")
    common(p)
    p.add_argument("--format", choices=FORMATS, default="markdown")
    p.set_defaults(func=cmd_cases)

    p = sub.add_parser("script", help="generate a pytest script")
    common(p)
    p.set_defaults(func=cmd_script)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (SpecError, FileNotFoundError, ModuleNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
