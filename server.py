"""Local HTTP entry point for the existing KwikPay sales core."""

import argparse
import json
import logging
import os
from urllib.parse import urlsplit, parse_qs
import re
import stat
from pathlib import Path
import sqlite3
import subprocess
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sales_api import create_sale_response
from payment_plan import create_payment_plan
from execution_store import create_execution, get_execution, sales_overview


class SalesHandler(BaseHTTPRequestHandler):
    """Expose sale allocation and payment-record creation over JSON."""

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if self.path.startswith("/api/test-callback/"):
            return
        super().log_message(format, *args)

    def do_GET(self) -> None:
        path = urlsplit(self.path)
        if os.environ.get("KWIKPAY_TEST_WALLET_ENABLED") == "1" and re.fullmatch(r"/api/test-callback/exec_[0-9a-f]{32}", path.path):
            from test_wallet_service import finish
            params = parse_qs(path.query, keep_blank_values=True)
            try:
                if set(params) != {"interact_ref", "hash"} or any(len(v) != 1 for v in params.values()):
                    raise ValueError("Invalid wallet callback.")
                finish(path.path.rsplit("/", 1)[1], params["interact_ref"][0], params["hash"][0])
            except Exception:
                self.send_json(400, {"detail": "Wallet authorization or payment processing could not be confirmed. Check the payment status before retrying."})
                return
            self.send_response(303)
            self.send_header("Location", "http://127.0.0.1:5182/")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            return
        if path.path == "/api/sales-overview":
            try:
                query = parse_qs(path.query, keep_blank_values=True, strict_parsing=True)
                if set(query) - {"offset"} or len(query.get("offset", ["0"])) != 1 or not re.fullmatch(r"[0-9]{1,8}", query.get("offset", ["0"])[0]):
                    raise ValueError("Invalid history offset.")
                self.send_json(200, sales_overview(int(query.get("offset", ["0"])[0])))
            except ValueError:
                self.send_json(400, {"detail": "Invalid history offset."})
            except (OSError, sqlite3.Error):
                logging.exception("Sales history unavailable")
                self.send_json(503, {"detail": "Sales history is unavailable."})
        elif self.path == "/api/health":
            self.send_json(200, {"status": "ok", "service": "kwikpay-core", "paymentExecution": False})
        elif re.fullmatch(r"/api/payment-executions/exec_[0-9a-f]{32}", self.path):
            try:
                execution_id = self.path.rsplit("/", 1)[1]
                if os.environ.get("KWIKPAY_TEST_WALLET_ENABLED") == "1":
                    from test_wallet_service import poll
                    execution = poll(execution_id)
                else:
                    execution = get_execution(execution_id)
                self.send_json(200 if execution else 404, execution or {"detail": "Execution not found."})
            except (OSError, sqlite3.Error):
                logging.exception("Execution storage unavailable")
                self.send_json(503, {"detail": "Execution storage unavailable."})
        else:
            self.send_json(404, {"detail": "Endpoint not found."})

    def do_POST(self) -> None:
        if self.path not in ("/api/sales", "/api/payment-plans", "/api/payment-executions", "/api/test-payments/prepare", "/api/test-payments/consent"):
            self.send_json(404, {"detail": "Endpoint not found."})
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"detail": "Send Content-Type: application/json."})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                self.send_json(413, {"detail": "JSON body must be between 1 and 65536 bytes."})
                return
            payload = json.loads(self.rfile.read(length))
            if self.path.startswith("/api/test-payments/"):
                if os.environ.get("KWIKPAY_TEST_WALLET_ENABLED") != "1" or self.headers.get("Origin") != "http://127.0.0.1:5182":
                    self.send_json(403, {"detail": "Test Wallet flow is unavailable."})
                    return
                from test_wallet_service import prepare, consent
                sale = prepare(payload) if self.path.endswith("/prepare") else consent(payload.get("executionId", ""))
            elif self.path == "/api/payment-executions":
                sale = create_execution(payload)
            elif self.path == "/api/payment-plans":
                sale = create_payment_plan(payload)
            else:
                validate_sale(payload)
                sale = create_sale_response(payload)
        except (ValueError, TypeError, InvalidOperation, UnicodeDecodeError) as exc:
            self.send_json(400, {"detail": str(exc)})
            return
        except (RuntimeError, OSError, KeyError, subprocess.SubprocessError):
            logging.exception("Payment service rejected the sale")
            self.send_json(502, {"detail": "Payment service unavailable. The payment record could not be confirmed."})
            return
        except sqlite3.Error:
            logging.exception("Execution storage unavailable")
            self.send_json(503, {"detail": "Execution storage unavailable."})
            return

        self.send_json(201 if "payment" in sale or "executionId" in sale else 200, sale)


def validate_sale(payload: dict) -> None:
    """Validate JSON types and cent precision before calling the sales core."""
    if not isinstance(payload, dict):
        raise ValueError("Sale must be a JSON object.")
    for field in ("amount", "supplier", "salaries", "maintenance"):
        if field in payload and (isinstance(payload[field], bool) or not isinstance(payload[field], (int, float, str))):
            raise ValueError(f"{field} must be a finite number.")
    amount = Decimal(str(payload.get("amount", "0")))
    if not amount.is_finite() or amount <= 0 or amount > Decimal("999999999999.99"):
        raise ValueError("Sale amount must be between R0.01 and R999999999999.99.")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Sale amount must use whole cents (at most two decimal places).")
    for field in ("shopId", "shop_id"):
        if field in payload and (not isinstance(payload[field], str) or not payload[field].strip() or len(payload[field]) > 255):
            raise ValueError("Shop ID must be a non-empty string of at most 255 characters.")
    if payload.get("currency", "ZAR") != "ZAR":
        raise ValueError("Currency must be ZAR.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8025)
    args = parser.parse_args()
    if os.environ.get("KWIKPAY_TEST_WALLET_ENABLED") == "1":
        if args.port != 8027 or not os.environ.get("KWIKPAY_EXECUTION_DB"):
            raise SystemExit("Test Wallet mode requires port 8027 and a dedicated KWIKPAY_EXECUTION_DB.")
        dbpath = Path(os.environ["KWIKPAY_EXECUTION_DB"])
        dbpath.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if dbpath.is_symlink():
            raise SystemExit("Test Wallet database must not be a symlink.")
        fd = os.open(dbpath, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if stat.S_IMODE(os.fstat(fd).st_mode) & 0o077:
                raise SystemExit("Test Wallet database must not be accessible to other users.")
        finally:
            os.close(fd)
    # shortcut: local development server only; use an ASGI server before a hosted pilot.
    with ThreadingHTTPServer(("127.0.0.1", args.port), SalesHandler) as server:
        print(f"KwikPay core: http://127.0.0.1:{args.port}", flush=True)
        server.serve_forever()
