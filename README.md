# x402 XRPL Settlement Adapter (Python)

Lean Python port of the TypeScript XRPL settlement adapter.

## Public API

- `create_challenge(...)`
- `verify_settlement(...)`

The verifier enforces strict v1 safe-mode invariants:

- no partial payments
- no path payment fields (`Paths`, `SendMax`, `DeliverMin`)
- memo binding to `paymentId`
- replay safety via pluggable replay store hooks

## Install

```bash
pip install .
```

## Test

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py"
```

## Coverage

Install coverage:

```bash
python3 -m pip install coverage
```

Run coverage for the package:

```bash
PYTHONPATH=src python3 -m coverage run --source=src/x402_xrpl_adapter -m unittest discover -s tests -p "test_*.py"
PYTHONPATH=src python3 -m coverage report -m
```
