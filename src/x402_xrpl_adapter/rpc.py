import json
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen


class XrplJsonRpcClient:
    """Tiny optional helper for XRPL JSON-RPC tx lookup."""

    def __init__(self, rpc_url: str, timeout_seconds: int = 10) -> None:
        self.rpc_url = rpc_url
        self.timeout_seconds = timeout_seconds

    def fetch_transaction(self, network: str, tx_hash: str) -> Optional[Dict[str, Any]]:
        del network  # network selection is caller-managed via rpc_url.
        payload = {
            "method": "tx",
            "params": [{"transaction": tx_hash, "binary": False}],
        }
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw)
        result = parsed.get("result")
        if not isinstance(result, dict):
            return None
        if result.get("error") is not None:
            return None
        return result
