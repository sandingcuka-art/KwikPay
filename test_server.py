import http.client
from contextlib import closing
import json
import threading
import tempfile
import os
import sqlite3
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from server import SalesHandler
from payment_plan import create_payment_plan


class SalesHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {"KWIKPAY_EXECUTION_DB": os.path.join(cls.temp_dir.name, "execution.sqlite")})
        cls.env.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), SalesHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.env.stop()
        cls.temp_dir.cleanup()

    def request(self, method, path, body=None, content_type="application/json"):
        with patch.object(SalesHandler, "log_message"):
            connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
            try:
                connection.request(method, path, body=body, headers={"Content-Type": content_type})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

    def test_health_identifies_the_real_core_and_missing_execution(self):
        status, body = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["service"], "kwikpay-core")
        self.assertFalse(body["paymentExecution"])

    def test_payment_plan_endpoint_returns_canonical_plan_without_creating_payment(self):
        payload = {"shopId": "demo", "saleId": "sale-1", "payerWalletAddress": "https://wallet.example/customer",
                   "amount": {"value": "10000", "assetCode": "ZAR", "assetScale": 2},
                   "rule": {"version": 1, "destinations": [
                       {"label": "Income", "percentage": 80, "walletAddress": "https://wallet.example/income"},
                       {"label": "Stock", "percentage": 20, "walletAddress": "https://wallet.example/stock"}]}}
        with patch("sales_api.InterledgerPaymentClient") as client:
            status, plan = self.request("POST", "/api/payment-plans", json.dumps(payload))
        self.assertEqual(status, 200)
        self.assertEqual([leg["amount"]["value"] for leg in plan["legs"]], ["8000", "2000"])
        client.assert_not_called()

    def test_http_sale_reuses_the_core_and_preserves_cents(self):
        status, body = self.request("POST", "/api/sales", json.dumps({
            "amount": 0.06, "supplier": 20, "salaries": 5, "maintenance": 5,
        }))
        self.assertEqual(status, 200)
        self.assertEqual(body["split"], {"supplier": 0.01, "salaries": 0.0, "maintenance": 0.0, "profit": 0.05})

    def test_shop_sale_creates_a_pending_record(self):
        payment = {"id": "test-payment", "shopId": "test-shop", "status": "PENDING"}
        with patch("sales_api.InterledgerPaymentClient") as client:
            client.return_value.create_payment.return_value = payment
            status, body = self.request("POST", "/api/sales", json.dumps({
                "amount": 100, "supplier": 80, "salaries": 0, "maintenance": 0, "shopId": "test-shop",
            }))
        self.assertEqual(status, 201)
        self.assertEqual(body["split"]["profit"], 20)
        self.assertEqual(body["payment"], payment)
        client.return_value.create_payment.assert_called_once_with("test-shop", 100, "ZAR")

    def test_bad_payloads_are_rejected_before_payment_creation(self):
        invalid = [None, [], {}, {"amount": True}, {"amount": 0}, {"amount": -1}, {"amount": 0.001},
                   {"amount": "NaN"}, {"amount": "Infinity"}, {"amount": []},
                   {"amount": 100, "supplier": -1}, {"amount": 100, "supplier": 101},
                   {"amount": 100, "salaries": None}, {"amount": 100, "maintenance": {}},
                   {"amount": 100, "shopId": " "}, {"amount": 100, "shopId": 2},
                   {"amount": 100, "currency": "EUR"}]
        with patch("sales_api.InterledgerPaymentClient") as client:
            for payload in invalid:
                with self.subTest(payload=payload):
                    status, body = self.request("POST", "/api/sales", json.dumps(payload))
                    self.assertEqual(status, 400)
                    self.assertIn("detail", body)
        client.assert_not_called()

    def test_malformed_json_and_content_type(self):
        self.assertEqual(self.request("POST", "/api/sales", "{")[0], 400)
        self.assertEqual(self.request("POST", "/api/sales", "{}", "text/plain")[0], 415)
        self.assertEqual(self.request("POST", "/api/sales", " " * 65537)[0], 413)

    def test_payment_outage_returns_an_error_without_simulating_success(self):
        with patch("sales_api.InterledgerPaymentClient") as client, patch("server.logging.exception"):
            client.return_value.create_payment.side_effect = RuntimeError("private upstream error")
            status, body = self.request("POST", "/api/sales", '{"amount":100,"shopId":"test-shop"}')
        self.assertEqual(status, 502)
        self.assertNotIn("private", body["detail"])

    def test_execution_rejects_invalid_plan(self):
        status, body = self.request("POST", "/api/payment-executions", "{}")
        self.assertEqual(status, 400)
        self.assertIn("plan", body["detail"])

    def test_execution_record_poll_and_idempotency(self):
        plan = create_payment_plan({"shopId": "demo", "saleId": "sale-1", "payerWalletAddress": "https://wallet.example/customer",
            "amount": {"value": "10000", "assetCode": "ZAR", "assetScale": 2}, "rule": {"version": 1, "destinations": [
                {"label": "Income", "percentage": 80, "walletAddress": "https://wallet.example/income"},
                {"label": "Stock", "percentage": 20, "walletAddress": "https://wallet.example/stock"}]}})
        status, execution = self.request("POST", "/api/payment-executions", json.dumps(plan))
        self.assertEqual(status, 201)
        self.assertEqual(execution["status"], "CREATED")
        self.assertEqual([leg["status"] for leg in execution["legs"]], ["PENDING", "PENDING"])
        self.assertEqual(self.request("POST", "/api/payment-executions", json.dumps(plan))[1]["executionId"], execution["executionId"])
        self.assertEqual(self.request("GET", "/api/payment-executions/" + execution["executionId"])[1], execution)
        # Provider outcomes are fixtures here; no route can set them in the local scaffold.
        with closing(sqlite3.connect(os.environ["KWIKPAY_EXECUTION_DB"])) as db, db:
            db.execute("UPDATE execution_legs SET status='COMPLETED' WHERE execution_id=? AND leg_id=?", (execution["executionId"], plan["legs"][0]["id"]))
            db.execute("UPDATE execution_legs SET status='FAILED' WHERE execution_id=? AND leg_id=?", (execution["executionId"], plan["legs"][1]["id"]))
            db.execute("UPDATE execution_records SET status='PARTIAL' WHERE id=?", (execution["executionId"],))
        stored = self.request("GET", "/api/payment-executions/" + execution["executionId"])[1]
        self.assertEqual(stored["status"], "PARTIAL")
        self.assertEqual({leg["legId"]: leg["status"] for leg in stored["legs"]}, {plan["legs"][0]["id"]: "COMPLETED", plan["legs"][1]["id"]: "FAILED"})
        plan["saleId"] = "other"
        self.assertEqual(self.request("POST", "/api/payment-executions", json.dumps(plan))[0], 400)
        plan["legs"][0]["amount"]["value"] = "9000"
        self.assertEqual(self.request("POST", "/api/payment-executions", json.dumps(plan))[0], 400)
        self.assertEqual(self.request("GET", "/api/payment-executions/exec_" + "0" * 32)[0], 404)

    def test_sales_overview_returns_data_and_validates_offsets(self):
        status, body = self.request("GET", "/api/sales-overview")
        self.assertEqual(status, 200)
        self.assertIn("history", body)
        self.assertIn("confirmedReceipts", body["summary"])
        self.assertEqual(self.request("GET", "/api/sales-overview?offset=100")[0], 200)
        for path in ("/api/sales-overview?offset=-1", "/api/sales-overview?offset=1&offset=2", "/api/sales-overview?offset=x", "/api/sales-overview?other=x"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 400)

    def test_unknown_endpoint_returns_json_404(self):
        self.assertEqual(self.request("GET", "/api/unknown")[0], 404)


if __name__ == "__main__":
    unittest.main()
