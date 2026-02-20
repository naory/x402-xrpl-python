import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from x402_xrpl_adapter import (
    InMemoryReplayStore,
    SettlementVerificationError,
    create_challenge,
    verify_settlement,
)


def _utf8_to_hex(value: str) -> str:
    return value.encode("utf-8").hex()


def _memo_for_payment_id(payment_id: str) -> list:
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


def _encode_receipt(network: str, tx_hash: str, payment_id: str) -> str:
    payload = {"network": network, "txHash": tx_hash, "paymentId": payment_id}
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


def _base_challenge(**overrides: Any) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "network": "xrpl:testnet",
        "amount": "2.5",
        "asset": {"kind": "XRP"},
        "destination": "rDEST",
        "expires_at": (datetime.now(tz=timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "payment_id": "PAYMENT-1",
    }
    params.update(overrides)
    return create_challenge(**params)


def _tx_for_challenge(challenge: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "validated": True,
        "TransactionType": "Payment",
        "Account": "rPAYER",
        "Destination": challenge["destination"],
        "Amount": "2500000",
        "Memos": _memo_for_payment_id(challenge["paymentId"]),
    }
    if challenge["asset"]["kind"] == "IOU":
        base["Amount"] = {
            "currency": challenge["asset"]["currency"],
            "issuer": challenge["asset"]["issuer"],
            "value": challenge["amount"],
        }
    base.update(overrides)
    return base


class ConformanceTests(unittest.TestCase):
    def test_replay_same_payment_id_same_tx_hash_idempotent_success(self) -> None:
        challenge = _base_challenge(payment_id="PAYMENT-REPLAY-A")
        tx_hash = "TX-A"
        receipt = _encode_receipt(challenge["network"], tx_hash, challenge["paymentId"])
        replay_store = InMemoryReplayStore()

        def fetch_transaction(_network: str, _tx_hash: str) -> Optional[Dict[str, Any]]:
            return _tx_for_challenge(challenge)

        first = verify_settlement(
            challenge=challenge,
            receipt_header_value=receipt,
            fetch_transaction=fetch_transaction,
            replay_store=replay_store,
        )
        second = verify_settlement(
            challenge=challenge,
            receipt_header_value=receipt,
            fetch_transaction=fetch_transaction,
            replay_store=replay_store,
        )

        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])

    def test_replay_same_payment_id_different_tx_hash_rejected(self) -> None:
        challenge = _base_challenge(payment_id="PAYMENT-REPLAY-B")
        replay_store = InMemoryReplayStore()

        def fetch_transaction(_network: str, _tx_hash: str) -> Optional[Dict[str, Any]]:
            return _tx_for_challenge(challenge)

        first_receipt = _encode_receipt(challenge["network"], "TX-1", challenge["paymentId"])
        verify_settlement(
            challenge=challenge,
            receipt_header_value=first_receipt,
            fetch_transaction=fetch_transaction,
            replay_store=replay_store,
        )

        second_receipt = _encode_receipt(challenge["network"], "TX-2", challenge["paymentId"])
        with self.assertRaises(SettlementVerificationError) as exc:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=second_receipt,
                fetch_transaction=fetch_transaction,
                replay_store=replay_store,
            )
        self.assertEqual(exc.exception.code, "replay_detected")

    def test_wrong_memo_or_wrong_amount_rejected(self) -> None:
        challenge = _base_challenge(payment_id="PAYMENT-MEMO-AMOUNT")

        def fetch_wrong_memo(_network: str, _tx_hash: str) -> Optional[Dict[str, Any]]:
            return _tx_for_challenge(challenge, Memos=_memo_for_payment_id("DIFFERENT"))

        with self.assertRaises(SettlementVerificationError) as exc_memo:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=_encode_receipt(
                    challenge["network"],
                    "TX-MEMO",
                    challenge["paymentId"],
                ),
                fetch_transaction=fetch_wrong_memo,
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc_memo.exception.code, "invalid_memo")

        def fetch_wrong_amount(_network: str, _tx_hash: str) -> Optional[Dict[str, Any]]:
            return _tx_for_challenge(challenge, Amount="2500001")

        with self.assertRaises(SettlementVerificationError) as exc_amount:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=_encode_receipt(
                    challenge["network"],
                    "TX-AMOUNT",
                    challenge["paymentId"],
                ),
                fetch_transaction=fetch_wrong_amount,
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc_amount.exception.code, "invalid_amount")

    def test_strict_v1_rules_no_paths_no_partials(self) -> None:
        challenge = _base_challenge(payment_id="PAYMENT-STRICT")

        def fetch_with_paths(_network: str, _tx_hash: str) -> Optional[Dict[str, Any]]:
            return _tx_for_challenge(challenge, Paths=[{}])

        with self.assertRaises(SettlementVerificationError) as exc_paths:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=_encode_receipt(
                    challenge["network"],
                    "TX-PATHS",
                    challenge["paymentId"],
                ),
                fetch_transaction=fetch_with_paths,
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc_paths.exception.code, "invalid_asset")

        def fetch_partial(_network: str, _tx_hash: str) -> Optional[Dict[str, Any]]:
            return _tx_for_challenge(challenge, Flags=0x00020000)

        with self.assertRaises(SettlementVerificationError) as exc_partial:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=_encode_receipt(
                    challenge["network"],
                    "TX-PARTIAL",
                    challenge["paymentId"],
                ),
                fetch_transaction=fetch_partial,
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc_partial.exception.code, "invalid_asset")


if __name__ == "__main__":
    unittest.main()
