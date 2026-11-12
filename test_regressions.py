import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from rules_engine import Rule, RulesEngine
from sales_api import create_sale_response
from transaction_split import split_transaction


class FinancialRegressionTests(unittest.TestCase):
    def test_rounding_never_creates_negative_profit(self):
        result = split_transaction("0.02", supplier=33, salaries=33, maintenance=34, env={})
        self.assertTrue(all(value >= 0 for value in result.values()))
        self.assertEqual(sum(Decimal(str(value)) for value in result.values()), Decimal("0.02"))

    def test_split_allocations_are_whole_cents(self):
        result = split_transaction("0.06", env={})

        for category, amount in result.items():
            with self.subTest(category=category):
                amount = Decimal(str(amount))
                self.assertEqual(amount, amount.quantize(Decimal("0.01")))

    def test_rounded_allocations_preserve_the_sale_total(self):
        result = split_transaction("0.06", env={})
        rounded_total = sum(
            Decimal(str(amount)).quantize(Decimal("0.01"))
            for amount in result.values()
        )

        self.assertEqual(rounded_total, Decimal("0.06"))

    def test_rule_rejects_non_finite_percentages(self):
        for percent in (float("nan"), float("inf"), "NaN", "Infinity"):
            with self.subTest(percent=percent):
                with self.assertRaises(ValueError):
                    Rule("supplier", percent)

    def test_nan_percentage_cannot_bypass_the_total_limit(self):
        with self.assertRaises(ValueError):
            split_transaction(
                100, supplier="NaN", salaries=100, maintenance=100, env={}
            )

    def test_engine_rejects_the_reserved_profit_rule_name(self):
        with self.assertRaises(ValueError):
            RulesEngine([Rule("supplier", 20), Rule("profit", 10)])

    def test_sale_requires_an_amount(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                create_sale_response({})

    def test_sale_rejects_non_finite_amounts(self):
        for amount in (float("nan"), float("inf"), "NaN", "Infinity"):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    create_sale_response({
                        "amount": amount,
                        "supplier": 2,
                        "salaries": 3,
                        "maintenance": 5,
                    })


if __name__ == "__main__":
    unittest.main()
