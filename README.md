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
python3 -m pip install ".[dev]"
```

## Test (pytest workflow)

```bash
PYTHONPATH=src python3 -m pytest
```

## Lint

```bash
python3 -m ruff check .
```

## Build + package checks

```bash
python3 -m build
python3 -m twine check dist/*
```
