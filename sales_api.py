import json
import math
import os
from urllib import error, request

from reporting_api import ReportingAPI
from transaction_split import TransactionSplitter


class InterledgerPaymentClient:
    """Submit a payment record to the Interledger payment service."""

    def __init__(self, base_url=None, timeout=10):
        self.base_url = (base_url or os.environ.get("INTERLEDGER_PAYMENT_SERVICE_URL") or "http://localhost:8080").rstrip("/")
        self.timeout = timeout

    def create_payment(self, shop_id, amount, currency="ZAR"):
        payload = {
            "shopId": shop_id,
            "amount": float(amount),
            "currency": currency,
        }

        url = f"{self.base_url}/api/payments"
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                if not body:
                    return payload
                return json.loads(body)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Interledger payment request failed with HTTP {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Interledger payment service unavailable at {url}: {exc.reason}") from exc


def create_sale_response(payload):
    """Create a JSON-like response for a sale transaction.

    Example payload:
        {"amount": 20}
        {"amount": 20, "supplier": 2, "salaries": 3, "maintenance": 5}
    """
    raw_amount = payload.get("amount")
    if raw_amount is None:
        raise ValueError("Total amount is required.")

    try:
        amount = float(raw_amount)
    except (TypeError, ValueError):
        raise ValueError("Total amount must be a finite number.") from None

    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Total amount must be a positive finite number.")

    supplier = payload.get("supplier")
    salaries = payload.get("salaries")
    maintenance = payload.get("maintenance")

    if supplier is None and salaries is None and maintenance is None:
        splitter = TransactionSplitter.from_environment(amount, os.environ)
    else:
        splitter = TransactionSplitter(
            amount,
            supplier=supplier,
            salaries=salaries,
            maintenance=maintenance,
            env=os.environ,
        )

    split = splitter.calculate()
    response = {
        "amount": amount,
        "split": split,
    }

    # When a shop is identified, persist the sale in the local reporting store
    # and submit the payment record to the external Interledger service.
    shop_id = payload.get("shopId") or payload.get("shop_id")
    if shop_id:
        payment_client = InterledgerPaymentClient()
        currency = payload.get("currency", "ZAR")
        payment = payment_client.create_payment(shop_id, amount, currency)
        response["payment"] = payment

        reporting_api = ReportingAPI()
        reporting_api.record_transaction(
            shop_id=shop_id,
            amount=amount,
            currency=currency,
            split=split,
            payment_reference=payment.get("id"),
        )

    return response
