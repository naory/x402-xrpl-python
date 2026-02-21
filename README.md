# x402-xrpl-settlement-adapter-py

Strict **server-side settlement verifier** for **x402 v2 payments on XRPL**.

This package validates presigned XRPL `Payment` transactions and turns them into deterministic, replay-safe x402 settlement receipts for HTTP 402 flows.

Designed for backend services that require strong guarantees around:

- On-ledger settlement verification
- Exact amount enforcement (XRP drops or IOU value)
- Exact currency + issuer matching (for IOUs such as RLUSD)
- Memo binding to `paymentId`
- Replay protection (`paymentId <-> txHash` invariant)
- Rejection of partial payments
- Rejection of path payments (`Paths` / `SendMax` / `DeliverMin`)
- Safe-mode enforcement (no `DestinationTag` support)

---

## What This Is

A strict verification layer that converts an XRPL `Payment` transaction into a validated **x402 v2 settlement result**.

It enforces deterministic settlement rules suitable for:

- API gateways
- Payment middleware
- Backend services issuing x402 challenges
- Infrastructure providers integrating XRPL settlement

---

## What This Is NOT

- Not a wallet SDK
- Not a signing library
- Not a presigned transaction builder
- Not a client-side payment helper

This is the **server-side enforcement layer**.

---

## Public API

Minimal by design:

- `create_challenge(...)`
- `verify_settlement(...)`
- `InMemoryReplayStore`
- `SettlementVerificationError`

Optional helpers (stdlib-only; core stays dependency-free):

- `fetch_transaction_jsonrpc(network_url, tx_hash)` — minimal RPC fetch
- `x402_xrpl_adapter.rpc.XrplJsonRpcClient` — wrapper for `verify_settlement` callback

---

## Quickstart

```bash
git clone https://github.com/naory/x402-xrpl-python.git
cd x402-xrpl-python
python3 -m pip install ".[dev]"
PYTHONPATH=src python3 -m pytest
```

---

## Usage Example

### 1) Issue a challenge

```python
from x402_xrpl_adapter import create_challenge

challenge = create_challenge(
    network="xrpl:testnet",
    amount="2.5",
    asset={"kind": "XRP"},
    destination="rDestinationAddress...",
    expires_at="2026-02-17T12:00:00Z",
    payment_id="PAYMENT-001",
)
```

### 2) Verify settlement from receipt + tx fetch callback

```python
import base64
import json

from x402_xrpl_adapter import InMemoryReplayStore, verify_settlement

receipt_header_value = base64.b64encode(
    json.dumps(
        {
            "network": challenge["network"],
            "txHash": "ABCDEF123...",
            "paymentId": challenge["paymentId"],
        }
    ).encode("utf-8")
).decode("utf-8")

def fetch_transaction(network: str, tx_hash: str):
    del network, tx_hash
    return {
        "validated": True,
        "TransactionType": "Payment",
        "Account": "rSender...",
        "Destination": challenge["destination"],
        "Amount": "2500000",  # 2.5 XRP in drops
        "Memos": [
            {
                "Memo": {
                    "MemoType": "78343032",  # "x402"
                    "MemoFormat": "6170706c69636174696f6e2f6a736f6e",  # "application/json"
                    "MemoData": "7b2276223a312c2274223a2278343032222c227061796d656e744964223a225041594d454e542d303031227d",
                }
            }
        ],
    }

result = verify_settlement(
    challenge=challenge,
    receipt_header_value=receipt_header_value,
    fetch_transaction=fetch_transaction,
    replay_store=InMemoryReplayStore(),
)

assert result["ok"] is True
```

Second call with the same `paymentId` + `txHash` returns idempotent success.

---

## Optional XRPL JSON-RPC Helper

Minimal stdlib-only helpers. Core verifier stays dependency-free.

**Function** — `fetch_transaction_jsonrpc(network_url, tx_hash)`:

```python
from x402_xrpl_adapter import fetch_transaction_jsonrpc

tx = fetch_transaction_jsonrpc("https://s.altnet.rippletest.net:51234", "ABCDEF123...")
# returns dict or None
```

**Class** — `XrplJsonRpcClient` for use as `verify_settlement` callback:

```python
from x402_xrpl_adapter.rpc import XrplJsonRpcClient

client = XrplJsonRpcClient("https://s.altnet.rippletest.net:51234")
result = verify_settlement(
    challenge=challenge,
    receipt_header_value=receipt_header_value,
    fetch_transaction=client.fetch_transaction,
    replay_store=InMemoryReplayStore(),
)
```

---

## Architecture Overview

```text
Client -> 402 Challenge -> XRPL Payment (presigned)
       -> txHash + receipt header

Server -> x402-xrpl-settlement-adapter-py
       -> fetch_transaction(network, tx_hash)
       -> deterministic validation
       -> settlement accepted/rejected
```

---

## Security Model

Strict validation rules:

- Exact amount match (no tolerance)
- Exact destination match
- Exact currency + issuer match for IOUs
- Required memo binding to `paymentId`
- Rejection of partial payments
- Rejection of path-based payment fields
- Replay protection invariant (`paymentId <-> txHash`)
- Distinct error codes for challenge, receipt, memo, and replay failures

This prevents replay, redirection, partial delivery, and path manipulation attacks.

---

## Conformance Vectors (Shared with TS)

Python runs a shared canonical vector suite from the TS repository.

- Default location: sibling TS repo at `../x402-xrpl/conformance/test_vectors.json`
- Override with env var:

```bash
X402_TEST_VECTORS_PATH=/absolute/path/to/test_vectors.json PYTHONPATH=src python3 -m pytest
```

---

## Development Workflow

### Test

```bash
PYTHONPATH=src python3 -m pytest
```

### Lint

```bash
python3 -m ruff check .
```

### Build + package checks

```bash
python3 -m build
python3 -m twine check dist/*
```

---

## License

MIT
