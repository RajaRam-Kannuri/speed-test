import ast
import itertools
import subprocess
import sys
from pathlib import Path

import pytest

from testgen.cases import generate_cases
from testgen.cli import main
from testgen.introspect import spec_from_module
from testgen.literal import to_source
from testgen.oracle import load_module, record_expectations
from testgen.render import render_cases, render_script
from testgen.spec import FunctionSpec, ParamSpec, Spec, SpecError, load_spec
from testgen.values import BOUNDARY, INVALID, NOMINAL, values_for

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_SPEC = ROOT / "examples" / "calculator.spec.json"


def fn(*params, **kw):
    return FunctionSpec(name="f", parameters=[ParamSpec.from_dict(p) for p in params], **kw)


# ---------------------------------------------------------------- spec


def test_spec_rejects_bad_type():
    with pytest.raises(SpecError, match="unsupported type"):
        ParamSpec.from_dict({"name": "x", "type": "complex"})


def test_spec_rejects_inverted_range():
    with pytest.raises(SpecError, match="min > max"):
        ParamSpec.from_dict({"name": "x", "type": "int", "min": 5, "max": 1})


def test_spec_rejects_duplicate_params():
    with pytest.raises(SpecError, match="duplicate"):
        FunctionSpec.from_dict({"name": "f", "parameters": [{"name": "x"}, {"name": "x"}]})


def test_spec_round_trip():
    spec = load_spec(EXAMPLE_SPEC)
    assert Spec.from_dict(spec.to_dict()).to_dict() == spec.to_dict()


# ---------------------------------------------------------------- values


def by_category(values):
    out = {NOMINAL: [], BOUNDARY: [], INVALID: []}
    for v in values:
        out[v.category].append(v.value)
    return out


def test_int_range_boundaries():
    cats = by_category(values_for(ParamSpec.from_dict({"name": "x", "type": "int", "min": 1, "max": 10})))
    assert cats[NOMINAL] == [5]
    assert {1, 2, 9, 10} <= set(cats[BOUNDARY])
    assert {0, 11, None, "1"} <= set(cats[INVALID])
    assert 0 not in cats[BOUNDARY]  # zero is outside the range


def test_excluded_value_is_invalid_and_nominal_moves():
    cats = by_category(values_for(ParamSpec.from_dict(
        {"name": "x", "type": "int", "min": -10, "max": 10, "exclude": [0]})))
    assert cats[NOMINAL] == [1]
    assert 0 not in cats[BOUNDARY]
    assert 0 in cats[INVALID]


def test_string_lengths():
    cats = by_category(values_for(ParamSpec.from_dict(
        {"name": "s", "type": "str", "min_length": 2, "max_length": 4})))
    assert "a" * 2 in cats[BOUNDARY] and "a" * 4 in cats[BOUNDARY]
    assert "a" in cats[INVALID] and "a" * 5 in cats[INVALID]


def test_nullable_makes_none_valid():
    cats = by_category(values_for(ParamSpec.from_dict({"name": "s", "type": "str", "nullable": True})))
    assert None in cats[BOUNDARY]
    assert None not in cats[INVALID]


def test_choices():
    cats = by_category(values_for(ParamSpec.from_dict({"name": "c", "choices": [1, 2, 3]})))
    assert cats[NOMINAL] == [1]
    assert cats[BOUNDARY] == [2, 3]
    assert 4 in cats[INVALID]


# ---------------------------------------------------------------- cases


SPEC_3 = (
    {"name": "a", "type": "int", "min": 0, "max": 5},
    {"name": "b", "type": "bool"},
    {"name": "c", "choices": ["x", "y", "z"]},
)


def test_each_strategy_covers_every_value():
    f = fn(*SPEC_3)
    cases = generate_cases(f, "each")
    for p in f.parameters:
        seen = {repr(c.inputs[p.name]) for c in cases}
        assert {repr(v.value) for v in values_for(p)} <= seen


def test_invalid_values_are_isolated():
    f = fn(*SPEC_3, raises_on_invalid="ValueError")
    for case in generate_cases(f, "pairwise"):
        invalid = [
            p.name for p in f.parameters
            if any(not v.valid and repr(v.value) == repr(case.inputs[p.name]) for v in values_for(p))
        ]
        if case.category == INVALID:
            assert len(invalid) == 1
            assert (case.expect, case.expected) == ("raises", "ValueError")
        else:
            assert invalid == []


def test_pairwise_covers_all_valid_pairs():
    f = fn(*SPEC_3)
    valid = {p.name: [repr(v.value) for v in values_for(p) if v.valid] for p in f.parameters}
    cases = [c for c in generate_cases(f, "pairwise") if c.category != INVALID]
    for a, b in itertools.combinations(valid, 2):
        covered = {(repr(c.inputs[a]), repr(c.inputs[b])) for c in cases}
        assert set(itertools.product(valid[a], valid[b])) <= covered
    product_size = 1
    for vals in valid.values():
        product_size *= len(vals)
    assert len(cases) < product_size


def test_case_ids_are_unique():
    cases = generate_cases(fn(*SPEC_3), "exhaustive")
    assert len({c.id for c in cases}) == len(cases)


def test_zero_parameter_function():
    cases = generate_cases(FunctionSpec(name="f"), "pairwise")
    assert [c.inputs for c in cases] == [{}]


def test_unknown_strategy():
    with pytest.raises(ValueError):
        generate_cases(fn(*SPEC_3), "random")


# ---------------------------------------------------------------- literal


@pytest.mark.parametrize("value", [
    0, -1.5, "hé", None, True, [1, [2]], (1,), {"k": (1, 2)}, set(), {3}, float("inf"), b"x",
])
def test_to_source_round_trips(value):
    src = to_source(value)
    assert eval(src) == value  # noqa: S307 - trusted test input


def test_to_source_rejects_objects():
    with pytest.raises(TypeError):
        to_source(object())


# ---------------------------------------------------------------- oracle / render


def test_oracle_records_and_flags_spec_mismatch():
    spec = load_spec(EXAMPLE_SPEC)
    cases = record_expectations(spec, generate_cases(spec.function("average")))
    nominal = cases[0]
    assert (nominal.expect, nominal.expected) == ("return", 0.0)
    flagged = [c for c in cases if c.notes]
    assert flagged and all("possible bug" in n for c in flagged for n in c.notes)


@pytest.mark.parametrize("fmt", ["json", "csv", "markdown"])
def test_render_cases_formats(fmt):
    spec = load_spec(EXAMPLE_SPEC)
    out = render_cases(generate_cases(spec.function("divide")), fmt)
    assert "divide_001" in out


def test_rendered_script_runs(tmp_path):
    spec = load_spec(EXAMPLE_SPEC)
    cases = []
    for f in spec.functions:
        cases += generate_cases(f)
    record_expectations(spec, cases)
    out = tmp_path / "test_generated.py"
    out.write_text(render_script(spec, cases, out))
    ast.parse(out.read_text())

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(out), "-q", "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=tmp_path,
    )
    # Every case passes except the one the spec says should raise but the
    # example function does not validate (an intentional demo bug).
    assert f"{len(cases) - 1} passed" in result.stdout, result.stdout
    assert "1 failed" in result.stdout
    assert "average_007-invalid" in result.stdout


def test_unrecorded_script_uses_smoke_checks():
    spec = load_spec(EXAMPLE_SPEC)
    script = render_script(spec, generate_cases(spec.function("divide")), None)
    assert "'return'" not in script  # nothing recorded
    assert "'raises', 'ValueError'" in script  # but spec expectations stay


# ---------------------------------------------------------------- introspect / cli


def test_introspect_reads_type_hints():
    probe = Spec(module=str(ROOT / "examples" / "calculator.py"), functions=[])
    spec = spec_from_module(load_module(probe), probe.module)
    greet = spec.function("greet").to_dict()
    params = {p["name"]: p for p in greet["parameters"]}
    assert params["name"]["type"] == "str"
    assert params["style"]["choices"] == ["formal", "casual"]
    assert params["title"]["nullable"] is True
    assert spec.function("average").parameters[0].items.type == "float"


def test_cli_end_to_end(tmp_path, capsys):
    drafted = tmp_path / "spec.json"
    assert main(["spec", str(ROOT / "examples" / "calculator.py"), "-o", str(drafted)]) == 0
    assert load_spec(drafted).function("divide")

    cases_out = tmp_path / "cases.csv"
    assert main(["cases", str(EXAMPLE_SPEC), "--format", "csv", "-o", str(cases_out)]) == 0
    assert cases_out.read_text().startswith("id,function")

    script_out = tmp_path / "sub" / "test_x.py"
    assert main(["script", str(EXAMPLE_SPEC), "-s", "pairwise", "-f", "divide", "-o", str(script_out)]) == 0
    assert "def test_divide" in script_out.read_text()
    assert "def test_greet" not in script_out.read_text()


def test_cli_reports_missing_spec(capsys):
    assert main(["cases", "nope.json"]) == 2
    assert "error" in capsys.readouterr().err
