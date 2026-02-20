SUPPORTED_NETWORKS = ("xrpl:1", "xrpl:testnet", "xrpl:devnet")

CHALLENGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "version",
        "network",
        "amount",
        "asset",
        "destination",
        "expiresAt",
        "paymentId",
        "memo",
    ],
    "properties": {
        "version": {"const": "2"},
        "network": {"enum": list(SUPPORTED_NETWORKS)},
        "amount": {"type": "string", "pattern": r"^(?:0|[1-9]\d*)(?:\.\d+)?$"},
        "asset": {
            "oneOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind"],
                    "properties": {"kind": {"const": "XRP"}},
                },
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "currency", "issuer"],
                    "properties": {
                        "kind": {"const": "IOU"},
                        "currency": {"type": "string", "minLength": 1},
                        "issuer": {"type": "string", "minLength": 1},
                    },
                },
            ]
        },
        "destination": {"type": "string", "minLength": 1},
        "expiresAt": {"type": "string", "minLength": 1},
        "paymentId": {"type": "string", "minLength": 1},
        "memo": {
            "type": "object",
            "additionalProperties": False,
            "required": ["format", "paymentId"],
            "properties": {
                "format": {"const": "x402"},
                "paymentId": {"type": "string", "minLength": 1},
                "sessionId": {"type": "string"},
            },
        },
    },
}

RECEIPT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["network", "txHash", "paymentId"],
    "properties": {
        "network": {"enum": list(SUPPORTED_NETWORKS)},
        "txHash": {"type": "string", "minLength": 1},
        "paymentId": {"type": "string", "minLength": 1},
    },
}
