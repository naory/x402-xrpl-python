import json
import unittest
from unittest.mock import patch

from x402_xrpl_adapter.rpc import XrplJsonRpcClient


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb
        return None


class RpcClientTests(unittest.TestCase):
    def test_fetch_transaction_returns_result_object(self) -> None:
        client = XrplJsonRpcClient("https://xrpl.example/rpc", timeout_seconds=3)
        expected = {"hash": "ABC", "validated": True}
        with patch("x402_xrpl_adapter.rpc.urlopen", return_value=_FakeResponse({"result": expected})):
            got = client.fetch_transaction("xrpl:testnet", "ABC")
        self.assertEqual(got, expected)

    def test_fetch_transaction_returns_none_for_non_object_result(self) -> None:
        client = XrplJsonRpcClient("https://xrpl.example/rpc")
        with patch("x402_xrpl_adapter.rpc.urlopen", return_value=_FakeResponse({"result": "not-an-object"})):
            got = client.fetch_transaction("xrpl:testnet", "ABC")
        self.assertIsNone(got)

    def test_fetch_transaction_returns_none_for_error_result(self) -> None:
        client = XrplJsonRpcClient("https://xrpl.example/rpc")
        payload = {"result": {"error": "txnNotFound"}}
        with patch("x402_xrpl_adapter.rpc.urlopen", return_value=_FakeResponse(payload)):
            got = client.fetch_transaction("xrpl:testnet", "ABC")
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
