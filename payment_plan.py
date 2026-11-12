"""Build the MVP payment plan without moving money or creating payment records."""

import re
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from urllib.parse import urlsplit
from uuid import uuid4


def wallet_address(value):
    if not isinstance(value, str) or value != value.strip() or len(value) > 2048:
        raise ValueError("Wallet address must be an HTTPS URL.")
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.port is not None or url.query or url.fragment or any(c.isspace() for c in value)):
            raise ValueError
    except ValueError:
        raise ValueError("Wallet address must be an HTTPS URL without credentials, port, query or fragment.") from None
    return value


def create_payment_plan(payload):
    if not isinstance(payload, dict):
        raise ValueError("Payment plan must be an object.")
    for field in ("shopId", "saleId"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"{field} is required.")
    payer = wallet_address(payload.get("payerWalletAddress"))
    amount = payload.get("amount")
    if not isinstance(amount, dict) or amount.get("assetCode") != "ZAR" or type(amount.get("assetScale")) is not int or amount["assetScale"] != 2:
        raise ValueError("Amount must use ZAR with asset scale 2.")
    value = amount.get("value")
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,14}", value) or int(value) <= 0:
        raise ValueError("Amount value must be positive integer minor units.")
    total = int(value)
    rule = payload.get("rule")
    if not isinstance(rule, dict) or type(rule.get("version")) is not int or rule["version"] < 1:
        raise ValueError("Rule version must be a positive integer.")
    destinations = rule.get("destinations")
    if not isinstance(destinations, list) or len(destinations) != 2:
        raise ValueError("Exactly two pots are required.")
    percentages = []
    for destination in destinations:
        if not isinstance(destination, dict) or not isinstance(destination.get("label"), str) or not destination["label"].strip():
            raise ValueError("Pot label is required.")
        wallet_address(destination.get("walletAddress"))
        percentage = destination.get("percentage")
        if isinstance(percentage, bool) or not isinstance(percentage, (int, float)):
            raise ValueError("Percentages must be numbers.")
        try:
            percent = Decimal(str(percentage))
            if not percent.is_finite() or not 0 <= percent <= 100:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValueError("Percentages must be between 0 and 100.") from None
        percentages.append(percent)
    if sum(percentages) != 100:
        raise ValueError("Percentages must total 100.")
    first = int((Decimal(total) * percentages[0] / 100).to_integral_value(rounding=ROUND_DOWN))
    amounts = [first, total - first]
    return {
        "id": f"plan_{uuid4().hex}", "saleId": payload["saleId"], "shopId": payload["shopId"],
        "payerWalletAddress": payer, "amount": {"value": str(total), "assetCode": "ZAR", "assetScale": 2},
        "ruleVersion": rule["version"], "status": "CREATED",
        "legs": [{"id": f"leg_{uuid4().hex}", "label": destination["label"].strip(),
                  "percentage": destination["percentage"], "walletAddress": destination["walletAddress"],
                  "amount": {"value": str(leg_amount), "assetCode": "ZAR", "assetScale": 2}, "status": "PENDING"}
                 for destination, leg_amount in zip(destinations, amounts)],
    }
