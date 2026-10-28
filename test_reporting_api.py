import os
import tempfile
import unittest

from reporting_api import ReportingAPI


class ReportingApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "kwikpay.db")
        self.api = ReportingAPI(self.db_path)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_transaction_and_rule_storage(self):
        self.api.save_rule("shop-42", "supplier", 2)
        self.api.save_rule("shop-42", "salaries", 3)

        transaction_id = self.api.record_transaction(
            shop_id="shop-42",
            amount=20,
            currency="ZAR",
            split={"supplier": 0.4, "salaries": 0.6, "maintenance": 1.0, "profit": 18.0},
            payment_reference="pay-123",
        )

        self.assertTrue(transaction_id)
        self.assertEqual(len(self.api.list_transactions("shop-42")), 1)
        self.assertEqual(self.api.get_rules("shop-42")["supplier"], 2)

    def test_shop_summary_aggregates_totals(self):
        self.api.save_rule("shop-42", "supplier", 2)
        self.api.save_rule("shop-42", "salaries", 3)
        self.api.save_rule("shop-42", "maintenance", 5)

        self.api.record_transaction(
            shop_id="shop-42",
            amount=20,
            currency="ZAR",
            split={"supplier": 0.4, "salaries": 0.6, "maintenance": 1.0, "profit": 18.0},
            payment_reference="pay-1",
        )
        self.api.record_transaction(
            shop_id="shop-42",
            amount=100,
            currency="ZAR",
            split={"supplier": 2.0, "salaries": 3.0, "maintenance": 5.0, "profit": 90.0},
            payment_reference="pay-2",
        )

        summary = self.api.shop_summary("shop-42")
        self.assertEqual(summary["total_sales"], 120.0)
        self.assertEqual(summary["total_profit"], 108.0)
        self.assertEqual(summary["supplier_total"], 2.4)
        self.assertEqual(summary["rules"]["supplier"], 2)

    def test_rule_crud_and_payment_status_updates(self):
        self.api.save_rule("shop-42", "supplier", 2)
        self.assertEqual(self.api.get_rule("shop-42", "supplier"), 2)

        self.api.save_rule("shop-42", "supplier", 4)
        self.assertEqual(self.api.get_rules("shop-42")["supplier"], 4)

        self.api.delete_rule("shop-42", "supplier")
        self.assertNotIn("supplier", self.api.get_rules("shop-42"))

        self.api.record_transaction(
            shop_id="shop-42",
            amount=50,
            currency="ZAR",
            split={"supplier": 1.0, "salaries": 2.0, "maintenance": 3.0, "profit": 44.0},
            payment_reference="pay-123",
            payment_status="PENDING",
        )

        self.assertEqual(self.api.get_payment_status("shop-42", "pay-123"), "PENDING")
        self.api.update_payment_status("shop-42", "pay-123", "PAID")
        self.assertEqual(self.api.get_payment_status("shop-42", "pay-123"), "PAID")
        self.assertEqual(self.api.list_transactions("shop-42")[0]["payment_status"], "PAID")

        summary = self.api.shop_summary("shop-42")
        self.assertEqual(summary["payment_status_summary"]["PAID"], 1)


if __name__ == "__main__":
    unittest.main()
