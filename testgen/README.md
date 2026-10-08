# testgen

The original standalone test-case generator. The LorvenLax platform reuses its boundary-value engine (`testgen.values`) for API boundary tests.

A small testing tool that **generates test cases** and **pytest test scripts**
for Python functions. It needs only the standard library; you need `pytest`
only to run the scripts it writes.

It works in three steps:

1. **Spec**: a JSON file that describes each function's parameters and their
   constraints. You can write it by hand or draft one from type hints.
2. **Test cases**: values for each parameter, chosen by equivalence
   partitioning and boundary value analysis, then combined using a strategy.
   You can export them as Markdown, CSV or JSON.
3. **Test script**: a runnable, parametrized pytest file.

## Web version

`web/index.html` is a browser version of the generator, published at
https://claude.ai/artifact/76RELjip87Fb1ujsRQUuWY. You edit the spec in a form
(or paste Python code or a spec JSON to import it), see the test cases update
as you type, and copy the pytest script or spec JSON. It runs entirely in the
browser and produces the same cases as the CLI. Because a browser can't run
your Python code, it doesn't record expected results. Instead, you can type an
expected value for any case.

## Quick start

```bash
pip install -e ".[dev]"        # or run in place with: python -m testgen ...

# 1. Draft a spec from type hints, then add ranges/lengths/excludes by hand
testgen spec examples/calculator.py -o my.spec.json

# 2. Review the generated test cases
testgen cases examples/calculator.spec.json --format markdown
testgen cases examples/calculator.spec.json --format csv -o cases.csv

# 3. Generate and run a pytest script
testgen script examples/calculator.spec.json -o generated/test_calculator.py
pytest generated/
```

## Spec format

```json
{
  "module": "examples/calculator.py",
  "functions": [
    {
      "name": "divide",
      "raises_on_invalid": "ValueError",
      "parameters": [
        {"name": "a", "type": "int", "min": -100, "max": 100},
        {"name": "b", "type": "int", "min": -100, "max": 100, "exclude": [0]}
      ]
    }
  ]
}
```

| Field | Applies to | Meaning |
|-------|------------|---------|
| `module` | spec | Path to a `.py` file, relative to the directory you run from, or a dotted import name |
| `raises_on_invalid` | function | The exception name invalid inputs should raise |
| `type` | param | `int`, `float`, `str`, `bool`, `list`, `any` |
| `min` / `max` | int, float | Inclusive range |
| `min_length` / `max_length` | str, list | Inclusive length range |
| `choices` | any | Allowed values (an enum) |
| `exclude` | any | Values that are invalid even when inside the range |
| `nullable` | any | `None` is a valid value |
| `items` | list | A param spec (without `name`) for the list's elements |

## How cases are generated

For each parameter, values fall into three groups:

- **nominal**: a typical value, such as the middle of the range
- **boundary**: min, min+1, max-1, max, zero, empty/long/unicode strings, other choices, `None` if nullable
- **invalid**: values just outside the range or length limits, the wrong type, `None`, excluded values, values not in `choices`

The `-s/--strategy` option sets how values are combined:

| Strategy | Valid values | Invalid values |
|----------|--------------|----------------|
| `each` (default) | Start from the nominal values and vary one parameter at a time | One at a time |
| `pairwise` | Greedy all-pairs: every pair of values appears together at least once | One at a time |
| `exhaustive` | Full cartesian product, capped at 500 | One at a time |

Each test case uses at most one invalid value, so a failure points to exactly
one bad input.

## Expected results

By default, testgen **runs the target function** to record each case's actual
result. This makes the scripts snapshot (characterization) tests:

- For valid cases, it records the return value (floats are compared with
  `pytest.approx`) or the exception the function raised.
- For invalid cases, when the function sets `raises_on_invalid`, the spec's
  expectation wins. If the function behaves differently, the case gets the
  note *possible bug*, and the generated test fails.

  The example spec shows this: `average` should reject list items outside
  [-1000, 1000] but doesn't, so `average_007` fails.

With `--no-record`, the target is not run. Valid cases then become smoke tests
(they must not raise), and invalid cases must raise some exception (or the one
named in `raises_on_invalid`).

## Project layout

```
testgen/
  spec.py        spec model, loading and validation
  values.py      values for each parameter (partitions and boundaries)
  cases.py       combination strategies -> TestCase objects
  oracle.py      runs the target to record expected results
  render.py      Markdown/CSV/JSON exports and the pytest script template
  introspect.py  drafts a spec from type hints
  cli.py         `testgen spec | cases | script`
examples/        a sample module and its spec
web/index.html   browser version (JavaScript port of the generator)
tests/           tests for testgen itself (run with `pytest`)
```
