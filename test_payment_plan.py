import copy
import unittest

from payment_plan import create_payment_plan


class PaymentPlanTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "shopId": "demo-shop", "saleId": "sale-1", "payerWalletAddress": "https://wallet.example/customer",
            "amount": {"value": "10000", "assetCode": "ZAR", "assetScale": 2},
            "rule": {"version": 1, "destinations": [
                {"label": "Business income", "percentage": 80, "walletAddress": "https://wallet.example/merchant"},
                {"label": "Stock reserve", "percentage": 20, "walletAddress": "https://wallet.example/stock"},
            ]},
        }

    def test_canonical_plan_and_remainder(self):
        for amount, expected in [("10000", ["8000", "2000"]), ("9999", ["7999", "2000"])]:
            self.request["amount"]["value"] = amount
            plan = create_payment_plan(self.request)
            self.assertEqual(plan["status"], "CREATED")
            self.assertEqual(plan["payerWalletAddress"], self.request["payerWalletAddress"])
            self.assertEqual([leg["amount"]["value"] for leg in plan["legs"]], expected)
            self.assertEqual(sum(int(leg["amount"]["value"]) for leg in plan["legs"]), int(amount))
            self.assertTrue(all(leg["status"] == "PENDING" for leg in plan["legs"]))

    def test_rejects_invalid_inputs(self):
        invalid = []
        for value in ("0", "-1", "1.5", 10000, "999999999999999"):
            request = copy.deepcopy(self.request); request["amount"]["value"] = value; invalid.append(request)
        for value in ("", "http://wallet.example/a", "https://u@wallet.example/a", "https://wallet.example/a?x=1"):
            request = copy.deepcopy(self.request); request["rule"]["destinations"][0]["walletAddress"] = value; invalid.append(request)
        request = copy.deepcopy(self.request); request["payerWalletAddress"] = ""; invalid.append(request)
        request = copy.deepcopy(self.request); request["rule"]["destinations"][0]["label"] = "  "; invalid.append(request)
        for value in (79, -1, True, float("nan")):
            request = copy.deepcopy(self.request); request["rule"]["destinations"][0]["percentage"] = value; invalid.append(request)
        request = copy.deepcopy(self.request); request["rule"]["destinations"].pop(); invalid.append(request)
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                create_payment_plan(request)


if __name__ == "__main__":
    unittest.main()
