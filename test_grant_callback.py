import unittest

from grant_callback import verify_interaction_hash


class GrantCallbackTests(unittest.TestCase):
    def test_published_example_and_tampering(self):
        values = ("VJLO6A4CATR0KRO", "MBDOFXG4Y5CVJCX821LH", "4IFWWIKYB2PQ6U56NL1", "https://server.example.com/tx")
        result = "x-gguKWTj8rQf7d7i3w3UhzvuJ5bpOlKyAlVpLxBffY"
        self.assertTrue(verify_interaction_hash(*values, result))
        self.assertFalse(verify_interaction_hash(*values[:2], "changed", values[3], result))
        self.assertFalse(verify_interaction_hash(*values, result[:-1] + "A"))
        self.assertFalse(verify_interaction_hash(*values, "not valid!"))
        self.assertFalse(verify_interaction_hash("", *values[1:], result))
        self.assertFalse(verify_interaction_hash(values[0] + "\n", *values[1:], result))


if __name__ == "__main__":
    unittest.main()
