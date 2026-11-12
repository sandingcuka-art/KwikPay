import unittest
from unittest import mock

from sales_api import create_sale_response


class SalesApiTests(unittest.TestCase):
    def test_create_sale_response_splits_amount(self):
        response = create_sale_response({
            "amount": 20,
            "supplier": 2,
            "salaries": 3,
            "maintenance": 5,
        })

        self.assertEqual(response["amount"], 20)
        self.assertEqual(response["split"]["supplier"], 0.4)
        self.assertEqual(response["split"]["salaries"], 0.6)
        self.assertEqual(response["split"]["maintenance"], 1.0)
        self.assertEqual(response["split"]["profit"], 18.0)

    def test_create_sale_response_uses_environment_defaults(self):
        import os
        from unittest.mock import patch

        with patch.dict(
            os.environ,
            {
                "KWIKPAY_SUPPLIER_PERCENT": "10",
                "KWIKPAY_SALARIES_PERCENT": "15",
                "KWIKPAY_MAINTENANCE_PERCENT": "20",
            },
            clear=False,
        ):
            response = create_sale_response({"amount": 100})

        self.assertEqual(response["split"]["supplier"], 10.0)
        self.assertEqual(response["split"]["salaries"], 15.0)
        self.assertEqual(response["split"]["maintenance"], 20.0)
        self.assertEqual(response["split"]["profit"], 55.0)

    def test_create_sale_response_submits_to_interledger_when_shop_id_present(self):
        with mock.patch("sales_api.InterledgerPaymentClient") as mock_client:
            mock_client.return_value.create_payment.return_value = {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "shopId": "shop-42",
                "amount": 20,
                "currency": "ZAR",
                "status": "PENDING",
            }

            response = create_sale_response({
                "amount": 20,
                "shopId": "shop-42",
                "supplier": 2,
                "salaries": 3,
                "maintenance": 5,
            })

            self.assertEqual(response["payment"]["shopId"], "shop-42")
            self.assertEqual(response["payment"]["status"], "PENDING")
            mock_client.return_value.create_payment.assert_called_once_with("shop-42", 20, "ZAR")

    def test_create_sale_response_persists_transaction_when_shop_id_present(self):
        with mock.patch("sales_api.InterledgerPaymentClient") as mock_client:
            mock_client.return_value.create_payment.return_value = {
                "id": "pay-001",
                "shopId": "shop-42",
                "amount": 20,
                "currency": "ZAR",
                "status": "PENDING",
            }

            with mock.patch("sales_api.ReportingAPI") as mock_reporting_api:
                response = create_sale_response({
                    "amount": 20,
                    "shopId": "shop-42",
                    "supplier": 2,
                    "salaries": 3,
                    "maintenance": 5,
                })

                self.assertIn("payment", response)
                mock_reporting_api.return_value.record_transaction.assert_called_once_with(
                    shop_id="shop-42",
                    amount=20,
                    currency="ZAR",
                    split=response["split"],
                    payment_reference="pay-001",
                )


if __name__ == "__main__":
    unittest.main()
