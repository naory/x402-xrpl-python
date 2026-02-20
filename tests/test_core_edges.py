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
        "payment_id": "PAYMENT-EDGE-1",
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


class CoreEdgeTests(unittest.TestCase):
    def test_create_challenge_rejects_iou_missing_fields(self) -> None:
        with self.assertRaises(SettlementVerificationError) as exc:
            create_challenge(
                network="xrpl:testnet",
                amount="1.5",
                asset={"kind": "IOU", "currency": "USD"},
                destination="rDEST",
                expires_at=(datetime.now(tz=timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                payment_id="P-IOU-MISS",
            )
        self.assertEqual(exc.exception.code, "invalid_challenge")

    def test_verify_settlement_rejects_receipt_network_mismatch(self) -> None:
        challenge = _base_challenge()
        receipt = _encode_receipt("xrpl:devnet", "TX-NET", challenge["paymentId"])
        with self.assertRaises(SettlementVerificationError) as exc:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=receipt,
                fetch_transaction=lambda _network, _tx_hash: _tx_for_challenge(challenge),
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc.exception.code, "network_mismatch")

    def test_verify_settlement_rejects_receipt_payment_id_mismatch(self) -> None:
        challenge = _base_challenge()
        receipt = _encode_receipt(challenge["network"], "TX-PID", "OTHER-PAYMENT-ID")
        with self.assertRaises(SettlementVerificationError) as exc:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=receipt,
                fetch_transaction=lambda _network, _tx_hash: _tx_for_challenge(challenge),
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc.exception.code, "invalid_receipt")

    def test_verify_settlement_rejects_missing_tx(self) -> None:
        challenge = _base_challenge(payment_id="PAYMENT-NOT-FOUND")
        receipt = _encode_receipt(challenge["network"], "TX-MISSING", challenge["paymentId"])

        def fetch_none(_network: str, _tx_hash: str) -> Optional[Dict[str, Any]]:
            return None

        with self.assertRaises(SettlementVerificationError) as exc:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=receipt,
                fetch_transaction=fetch_none,
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc.exception.code, "tx_not_found")

    def test_verify_settlement_rejects_invalid_tx_state(self) -> None:
        challenge = _base_challenge(payment_id="PAYMENT-BAD-TX")
        receipt = _encode_receipt(challenge["network"], "TX-BAD-TX", challenge["paymentId"])
        bad_tx = _tx_for_challenge(challenge, validated=False)

        with self.assertRaises(SettlementVerificationError) as exc:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=receipt,
                fetch_transaction=lambda _network, _tx_hash: bad_tx,
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc.exception.code, "tx_not_validated")

    def test_verify_settlement_rejects_destination_issues(self) -> None:
        challenge = _base_challenge(payment_id="PAYMENT-DEST")

        bad_dest_receipt = _encode_receipt(challenge["network"], "TX-BAD-DEST", challenge["paymentId"])
        with self.assertRaises(SettlementVerificationError) as exc_dest:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=bad_dest_receipt,
                fetch_transaction=lambda _network, _tx_hash: _tx_for_challenge(challenge, Destination="rOTHER"),
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc_dest.exception.code, "invalid_destination")

        tag_receipt = _encode_receipt(challenge["network"], "TX-DEST-TAG", challenge["paymentId"])
        with self.assertRaises(SettlementVerificationError) as exc_tag:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=tag_receipt,
                fetch_transaction=lambda _network, _tx_hash: _tx_for_challenge(challenge, DestinationTag=7),
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc_tag.exception.code, "invalid_destination")

    def test_verify_settlement_rejects_invalid_account(self) -> None:
        challenge = _base_challenge(payment_id="PAYMENT-ACC")
        receipt = _encode_receipt(challenge["network"], "TX-ACC", challenge["paymentId"])
        with self.assertRaises(SettlementVerificationError) as exc:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=receipt,
                fetch_transaction=lambda _network, _tx_hash: _tx_for_challenge(challenge, Account=""),
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc.exception.code, "invalid_receipt")

    def test_verify_settlement_accepts_iou_flow(self) -> None:
        challenge = _base_challenge(
            payment_id="PAYMENT-IOU-OK",
            amount="12.34",
            asset={"kind": "IOU", "currency": "USD", "issuer": "rISSUER"},
        )
        receipt = _encode_receipt(challenge["network"], "TX-IOU-OK", challenge["paymentId"])

        result = verify_settlement(
            challenge=challenge,
            receipt_header_value=receipt,
            fetch_transaction=lambda _network, _tx_hash: _tx_for_challenge(challenge),
            replay_store=InMemoryReplayStore(),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["payerAccount"], "rPAYER")

    def test_verify_settlement_rejects_xrp_with_too_many_decimals(self) -> None:
        challenge = _base_challenge(payment_id="PAYMENT-XRP-DEC", amount="1.1234567")
        receipt = _encode_receipt(challenge["network"], "TX-XRP-DEC", challenge["paymentId"])
        with self.assertRaises(SettlementVerificationError) as exc:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=receipt,
                fetch_transaction=lambda _network, _tx_hash: _tx_for_challenge(challenge, Amount="1123457"),
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc.exception.code, "invalid_amount")

    def test_verify_settlement_rejects_bad_receipt_encoding(self) -> None:
        challenge = _base_challenge(payment_id="PAYMENT-ENC")
        with self.assertRaises(SettlementVerificationError) as exc:
            verify_settlement(
                challenge=challenge,
                receipt_header_value="not-base64",
                fetch_transaction=lambda _network, _tx_hash: _tx_for_challenge(challenge),
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc.exception.code, "invalid_receipt")

    def test_verify_settlement_rejects_mismatched_challenge_memo_payment_id(self) -> None:
        challenge = _base_challenge(payment_id="PAYMENT-CHAL-MEMO")
        challenge["memo"]["paymentId"] = "OTHER"
        receipt = _encode_receipt(challenge["network"], "TX-CHAL-MEMO", challenge["paymentId"])
        with self.assertRaises(SettlementVerificationError) as exc:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=receipt,
                fetch_transaction=lambda _network, _tx_hash: _tx_for_challenge(challenge),
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc.exception.code, "invalid_challenge")

    def test_verify_settlement_rejects_expired_challenge(self) -> None:
        challenge = _base_challenge(
            payment_id="PAYMENT-EXP",
            expires_at=(datetime.now(tz=timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        )
        receipt = _encode_receipt(challenge["network"], "TX-EXP", challenge["paymentId"])
        with self.assertRaises(SettlementVerificationError) as exc:
            verify_settlement(
                challenge=challenge,
                receipt_header_value=receipt,
                fetch_transaction=lambda _network, _tx_hash: _tx_for_challenge(challenge),
                replay_store=InMemoryReplayStore(),
            )
        self.assertEqual(exc.exception.code, "expired_challenge")

    def test_replay_store_rejects_tx_hash_reused_for_other_payment(self) -> None:
        store = InMemoryReplayStore()
        store.register("PAYMENT-A", "TX-SAME")
        with self.assertRaises(SettlementVerificationError) as exc:
            store.register("PAYMENT-B", "TX-SAME")
        self.assertEqual(exc.exception.code, "replay_detected")


if __name__ == "__main__":
    unittest.main()
