from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import pytest

from x402_xrpl_adapter import (
    InMemoryReplayStore,
    SettlementVerificationError,
    create_challenge,
    verify_settlement,
)


def _default_vectors_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root.parent / "x402-xrpl" / "conformance" / "test_vectors.json"


def _load_vectors() -> dict[str, Any]:
    custom = os.getenv("X402_TEST_VECTORS_PATH")
    vectors_path = Path(custom) if custom else _default_vectors_path()
    return json.loads(vectors_path.read_text(encoding="utf-8"))


def _utf8_to_hex(value: str) -> str:
    return value.encode("utf-8").hex()


def _memo_for_payment_id(payment_id: str) -> list[dict[str, Any]]:
    memo_data = {"v": 1, "t": "x402", "paymentId": payment_id}
    return [
        {
            "Memo": {
                "MemoType": _utf8_to_hex("x402"),
                "MemoFormat": _utf8_to_hex("application/json"),
                "MemoData": _utf8_to_hex(json.dumps(memo_data)),
            }
        }
    ]


def _encode_receipt(receipt: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(receipt).encode("utf-8")).decode("utf-8")


def _enrich_tx(tx: dict[str, Any]) -> dict[str, Any]:
    if "memoPaymentId" not in tx:
        return tx
    tx = dict(tx)
    tx["Memos"] = _memo_for_payment_id(str(tx["memoPaymentId"]))
    del tx["memoPaymentId"]
    return tx


VECTORS = _load_vectors()


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["id"])
def test_shared_conformance_vectors(case: dict[str, Any]) -> None:
    challenge = create_challenge(
        network=case["challenge"]["network"],
        amount=case["challenge"]["amount"],
        asset=case["challenge"]["asset"],
        destination=case["challenge"]["destination"],
        expires_at=case["challenge"]["expiresAt"],
        payment_id=case["challenge"]["paymentId"],
    )
    replay_store = InMemoryReplayStore()

    for step in case["steps"]:
        tx_by_hash = step["txByHash"]

        def fetch_transaction(_network: str, tx_hash: str) -> dict[str, Any] | None:
            tx = tx_by_hash.get(tx_hash)
            return None if tx is None else _enrich_tx(tx)

        if "receiptRaw" in step:
            receipt_header_value = step["receiptRaw"]
        else:
            receipt_header_value = _encode_receipt(step["receipt"])

        expected_error = step["expect"].get("errorCode")
        if expected_error is not None:
            with pytest.raises(SettlementVerificationError) as exc:
                verify_settlement(
                    challenge=challenge,
                    receipt_header_value=receipt_header_value,
                    fetch_transaction=fetch_transaction,
                    replay_store=replay_store,
                )
            assert exc.value.code == expected_error
            continue

        result = verify_settlement(
            challenge=challenge,
            receipt_header_value=receipt_header_value,
            fetch_transaction=fetch_transaction,
            replay_store=replay_store,
        )
        assert result["ok"] is step["expect"].get("ok", True)
        assert result["idempotent"] is step["expect"].get("idempotent", False)
