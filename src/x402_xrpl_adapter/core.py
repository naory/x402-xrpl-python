import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Protocol

from .schemas import CHALLENGE_SCHEMA, RECEIPT_SCHEMA, SUPPORTED_NETWORKS

FetchTransaction = Callable[[str, str], Optional[Dict[str, Any]]]


class ReplayStore(Protocol):
    def get_tx_hash_by_payment_id(self, payment_id: str) -> Optional[str]: ...

    def get_payment_id_by_tx_hash(self, tx_hash: str) -> Optional[str]: ...

    def register(self, payment_id: str, tx_hash: str) -> None: ...


@dataclass
class InMemoryReplayStore:
    _payment_id_to_tx_hash: Dict[str, str]
    _tx_hash_to_payment_id: Dict[str, str]

    def __init__(self) -> None:
        self._payment_id_to_tx_hash = {}
        self._tx_hash_to_payment_id = {}

    def get_tx_hash_by_payment_id(self, payment_id: str) -> Optional[str]:
        return self._payment_id_to_tx_hash.get(payment_id)

    def get_payment_id_by_tx_hash(self, tx_hash: str) -> Optional[str]:
        return self._tx_hash_to_payment_id.get(tx_hash)

    def register(self, payment_id: str, tx_hash: str) -> None:
        existing_tx = self._payment_id_to_tx_hash.get(payment_id)
        if existing_tx is not None and existing_tx != tx_hash:
            raise SettlementVerificationError(
                "replay_detected",
                "replay_detected: paymentId used with different txHash",
            )
        existing_payment_id = self._tx_hash_to_payment_id.get(tx_hash)
        if existing_payment_id is not None and existing_payment_id != payment_id:
            raise SettlementVerificationError(
                "replay_detected",
                "replay_detected: txHash used with different paymentId",
            )
        self._payment_id_to_tx_hash[payment_id] = tx_hash
        self._tx_hash_to_payment_id[tx_hash] = payment_id


class SettlementVerificationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def create_challenge(
    *,
    network: str,
    amount: str,
    asset: Dict[str, Any],
    destination: str,
    expires_at: str,
    payment_id: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    _assert_supported_network(network)
    _assert_decimal_amount(amount, "invalid_challenge")
    _assert_iso8601_utc(expires_at, "invalid_challenge")
    _assert_non_empty(destination, "destination", "invalid_challenge")
    _assert_non_empty(payment_id, "paymentId", "invalid_challenge")

    if asset.get("kind") == "IOU":
        _assert_non_empty(str(asset.get("currency", "")), "asset.currency", "invalid_challenge")
        _assert_non_empty(str(asset.get("issuer", "")), "asset.issuer", "invalid_challenge")

    challenge: Dict[str, Any] = {
        "version": "2",
        "network": network,
        "amount": _normalize_decimal(amount),
        "asset": asset,
        "destination": destination,
        "expiresAt": expires_at,
        "paymentId": payment_id,
        "memo": {
            "format": "x402",
            "paymentId": payment_id,
            "sessionId": session_id,
        },
    }
    _validate_schema(challenge, CHALLENGE_SCHEMA, "invalid_challenge")
    return challenge


def verify_settlement(
    *,
    challenge: Dict[str, Any],
    receipt_header_value: str,
    fetch_transaction: FetchTransaction,
    replay_store: ReplayStore,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now_value = now or datetime.now(tz=timezone.utc)
    _validate_challenge(challenge)
    _validate_not_expired(challenge, now_value)

    receipt = _decode_receipt_header(receipt_header_value)
    if receipt["network"] != challenge["network"]:
        raise SettlementVerificationError(
            "network_mismatch",
            "receipt.network does not match challenge.network",
        )
    if receipt["paymentId"] != challenge["paymentId"]:
        raise SettlementVerificationError(
            "invalid_receipt",
            "receipt.paymentId does not match challenge.paymentId",
        )

    existing_tx = replay_store.get_tx_hash_by_payment_id(challenge["paymentId"])
    if existing_tx is not None and existing_tx != receipt["txHash"]:
        raise SettlementVerificationError(
            "replay_detected",
            "replay_detected: paymentId used with different txHash",
        )
    existing_payment_id = replay_store.get_payment_id_by_tx_hash(receipt["txHash"])
    if existing_payment_id is not None and existing_payment_id != challenge["paymentId"]:
        raise SettlementVerificationError(
            "replay_detected",
            "replay_detected: txHash used with different paymentId",
        )

    if existing_tx == receipt["txHash"] and existing_payment_id == challenge["paymentId"]:
        return {"ok": True, "idempotent": True, "receipt": receipt}

    tx = fetch_transaction(challenge["network"], receipt["txHash"])
    if tx is None:
        raise SettlementVerificationError("tx_not_found", "transaction not found")
    if not tx.get("validated") or tx.get("TransactionType") != "Payment":
        raise SettlementVerificationError(
            "tx_not_validated",
            "transaction is not a validated Payment",
        )

    account = tx.get("Account")
    if not isinstance(account, str) or account.strip() == "":
        raise SettlementVerificationError(
            "invalid_receipt",
            "tx.Account (payer address) is required",
        )
    if tx.get("Destination") != challenge["destination"]:
        raise SettlementVerificationError(
            "invalid_destination",
            "transaction destination does not match challenge",
        )
    if tx.get("DestinationTag") is not None:
        raise SettlementVerificationError(
            "invalid_destination",
            "DestinationTag is not supported in v1 safe mode",
        )

    flags = int(tx.get("Flags", 0) or 0)
    if flags & 0x00020000:
        raise SettlementVerificationError(
            "invalid_asset",
            "partial payment flag is not allowed in v1",
        )
    if tx.get("Paths") is not None or tx.get("SendMax") is not None or tx.get("DeliverMin") is not None:
        raise SettlementVerificationError(
            "invalid_asset",
            "path payment fields (Paths/SendMax/DeliverMin) are not allowed in v1",
        )

    _assert_amount_and_asset_match(challenge, tx.get("Amount"))
    _assert_memo_matches(tx.get("Memos"), challenge["paymentId"])
    replay_store.register(challenge["paymentId"], receipt["txHash"])

    return {
        "ok": True,
        "idempotent": False,
        "receipt": receipt,
        "payerAccount": account,
    }


def _validate_challenge(challenge: Dict[str, Any]) -> None:
    _validate_schema(challenge, CHALLENGE_SCHEMA, "invalid_challenge")
    _assert_iso8601_utc(challenge["expiresAt"], "invalid_challenge")
    if challenge["memo"]["paymentId"] != challenge["paymentId"]:
        raise SettlementVerificationError(
            "invalid_challenge",
            "challenge.memo.paymentId must match challenge.paymentId",
        )


def _validate_not_expired(challenge: Dict[str, Any], now: datetime) -> None:
    try:
        expires_at = _parse_iso8601_utc(challenge["expiresAt"])
    except ValueError as exc:
        raise SettlementVerificationError(
            "invalid_challenge",
            "challenge.expiresAt is not valid ISO-8601",
        ) from exc
    if now > expires_at:
        raise SettlementVerificationError("expired_challenge", "challenge has expired")


def _decode_receipt_header(receipt_header_value: str) -> Dict[str, Any]:
    try:
        decoded = base64.b64decode(receipt_header_value).decode("utf-8")
        payload = json.loads(decoded)
    except Exception as exc:
        raise SettlementVerificationError(
            "invalid_receipt",
            "receipt header is not valid base64 JSON",
        ) from exc

    _validate_schema(payload, RECEIPT_SCHEMA, "invalid_receipt")
    return payload


def _assert_amount_and_asset_match(challenge: Dict[str, Any], tx_amount: Any) -> None:
    expected_amount = challenge["amount"]
    asset = challenge["asset"]
    if asset["kind"] == "XRP":
        if not isinstance(tx_amount, str):
            raise SettlementVerificationError(
                "invalid_asset",
                "expected XRP amount in drops string form",
            )
        if tx_amount != _xrp_to_drops(expected_amount):
            raise SettlementVerificationError(
                "invalid_amount",
                "XRP amount (drops) does not match challenge amount",
            )
        return

    if not isinstance(tx_amount, dict):
        raise SettlementVerificationError("invalid_asset", "expected IOU issued amount")
    if tx_amount.get("currency") != asset.get("currency") or tx_amount.get("issuer") != asset.get("issuer"):
        raise SettlementVerificationError(
            "invalid_asset",
            "IOU currency/issuer does not match challenge",
        )
    if tx_amount.get("value") != expected_amount:
        raise SettlementVerificationError(
            "invalid_amount",
            "IOU amount does not match challenge amount",
        )


def _assert_memo_matches(memos: Any, payment_id: str) -> None:
    if not isinstance(memos, list) or len(memos) == 0:
        raise SettlementVerificationError("invalid_memo", "transaction memo is required")

    for memo_container in memos:
        memo = memo_container.get("Memo") if isinstance(memo_container, dict) else None
        if not isinstance(memo, dict):
            continue

        memo_type = _decode_memo_field(memo.get("MemoType"))
        memo_format = _decode_memo_field(memo.get("MemoFormat"))
        memo_data_hex = memo.get("MemoData")
        if not isinstance(memo_data_hex, str) or memo_data_hex == "":
            continue

        try:
            memo_data = bytes.fromhex(memo_data_hex).decode("utf-8")
        except Exception as exc:
            raise SettlementVerificationError(
                "invalid_memo",
                "MemoData must be hex-encoded UTF-8 JSON",
            ) from exc

        if memo_type != "x402" or memo_format != "application/json" or memo_data == "":
            continue

        try:
            parsed = json.loads(memo_data)
        except Exception as exc:
            raise SettlementVerificationError("invalid_memo", "memo JSON is malformed") from exc

        if (
            parsed.get("v") == 1
            and parsed.get("t") == "x402"
            and isinstance(parsed.get("paymentId"), str)
            and parsed["paymentId"] == payment_id
        ):
            return

    raise SettlementVerificationError(
        "invalid_memo",
        "no valid x402 memo found with matching paymentId",
    )


def _validate_schema(payload: Any, schema: Dict[str, Any], code: str) -> None:
    if schema is CHALLENGE_SCHEMA:
        _validate_challenge_shape(payload, code)
        return
    if schema is RECEIPT_SCHEMA:
        _validate_receipt_shape(payload, code)
        return
    raise SettlementVerificationError(code, "unsupported schema")


def _validate_challenge_shape(payload: Any, code: str) -> None:
    if not isinstance(payload, dict):
        raise SettlementVerificationError(code, "challenge must be an object")
    required_fields = (
        "version",
        "network",
        "amount",
        "asset",
        "destination",
        "expiresAt",
        "paymentId",
        "memo",
    )
    for field in required_fields:
        if field not in payload:
            raise SettlementVerificationError(code, "%s is required" % field)
    if payload["version"] != "2":
        raise SettlementVerificationError(code, 'challenge.version must be "2"')
    _assert_supported_network(payload["network"])
    _assert_decimal_amount(payload["amount"], code)
    _assert_non_empty(payload["destination"], "destination", code)
    _assert_non_empty(payload["paymentId"], "paymentId", code)

    asset = payload["asset"]
    if not isinstance(asset, dict):
        raise SettlementVerificationError(code, "asset must be an object")
    kind = asset.get("kind")
    if kind not in ("XRP", "IOU"):
        raise SettlementVerificationError(code, 'asset.kind must be "XRP" or "IOU"')
    if kind == "IOU":
        _assert_non_empty(asset.get("currency", ""), "asset.currency", code)
        _assert_non_empty(asset.get("issuer", ""), "asset.issuer", code)

    memo = payload["memo"]
    if not isinstance(memo, dict):
        raise SettlementVerificationError(code, "memo must be an object")
    if memo.get("format") != "x402":
        raise SettlementVerificationError(code, "challenge.memo.format must be x402")
    _assert_non_empty(memo.get("paymentId", ""), "memo.paymentId", code)


def _validate_receipt_shape(payload: Any, code: str) -> None:
    if not isinstance(payload, dict):
        raise SettlementVerificationError(code, "receipt payload must be an object")
    for field in ("network", "txHash", "paymentId"):
        value = payload.get(field)
        if not isinstance(value, str) or value.strip() == "":
            raise SettlementVerificationError(code, "receipt.%s is required" % field)
    _assert_supported_network(payload["network"])


def _assert_supported_network(network: str) -> None:
    if network not in SUPPORTED_NETWORKS:
        raise SettlementVerificationError("network_mismatch", f"unsupported network: {network}")


def _assert_decimal_amount(value: str, code: str) -> None:
    if not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d+)?", value):
        raise SettlementVerificationError(code, f"invalid decimal amount: {value}")


def _assert_non_empty(value: str, field: str, code: str) -> None:
    if not isinstance(value, str) or value.strip() == "":
        raise SettlementVerificationError(code, f"{field} is required")


def _parse_iso8601_utc(value: str) -> datetime:
    if not isinstance(value, str) or "T" not in value or not value.endswith("Z"):
        raise ValueError("invalid UTC timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_iso8601_utc(value: str, code: str) -> None:
    try:
        _parse_iso8601_utc(value)
    except ValueError as exc:
        raise SettlementVerificationError(code, "expiresAt must be an ISO-8601 UTC timestamp") from exc


def _normalize_decimal(value: str) -> str:
    _assert_decimal_amount(value, "invalid_amount")
    if "." not in value:
        return value
    integer, fraction = value.split(".", 1)
    integer = integer.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    return f"{integer}.{fraction}" if fraction else integer


def _xrp_to_drops(xrp: str) -> str:
    _assert_decimal_amount(xrp, "invalid_amount")
    integer, dot, fraction = xrp.partition(".")
    if len(fraction) > 6:
        raise SettlementVerificationError(
            "invalid_amount",
            "XRP amount must have at most 6 decimal places",
        )
    fraction_padded = fraction.ljust(6, "0")
    return (integer + fraction_padded).lstrip("0") or "0"


def _decode_memo_field(value: Any) -> str:
    if not isinstance(value, str) or value == "":
        return ""
    if re.fullmatch(r"[0-9a-fA-F]+", value) and len(value) % 2 == 0:
        try:
            return bytes.fromhex(value).decode("utf-8")
        except Exception as exc:
            raise SettlementVerificationError(
                "invalid_memo",
                "memo field contains invalid hex",
            ) from exc
    return value
