import os
import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from execution_store import claim_outgoing, create_execution, get_execution, record_outgoing, reconcile_outgoing, record_incoming
from payment_plan import create_payment_plan
from pathlib import Path


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"KWIKPAY_EXECUTION_DB": os.path.join(self.temp.name, "test.sqlite")})
        env.start()
        self.addCleanup(env.stop)
        self.plan = create_payment_plan({"shopId": "test", "saleId": "test", "payerWalletAddress": "https://wallet.example/payer",
            "amount": {"value": "100", "assetCode": "ZAR", "assetScale": 2},
            "rule": {"version": 1, "destinations": [
                {"label": "Business", "walletAddress": "https://wallet.example/one", "percentage": 80},
                {"label": "Stock", "walletAddress": "https://wallet.example/two", "percentage": 20}]}})
        self.execution = create_execution(self.plan)["executionId"]
        self.legs = [leg["id"] for leg in self.plan["legs"]]
        self.urls = [f"https://ilp.interledger-test.dev/tenant/outgoing-payments/{i}" for i in range(2)]

    def prepare(self):
        with closing(sqlite3.connect(os.environ["KWIKPAY_EXECUTION_DB"])) as db, db:
            db.execute("UPDATE execution_records SET status='PROCESSING' WHERE id=?", (self.execution,))
            db.execute("UPDATE execution_legs SET status='PREPARED' WHERE execution_id=?", (self.execution,))

    def test_upgrade_preserves_existing_uncertain_attempts(self):
        old_path = os.path.join(self.temp.name, 'preexisting.sqlite')
        with closing(sqlite3.connect(old_path)) as db, db:
            db.execute('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)')
            for name in ('001_execution_records.sql', '002_execution_legs.sql', '003_provider_legs.sql', '004_test_wallet_sessions.sql'):
                db.executescript((Path(__file__).parent / 'migrations' / name).read_text())
            db.execute("INSERT INTO execution_records (id,plan_id,plan_json,status) VALUES ('old','oldplan',?,'PROCESSING')", ('{}',))
            db.execute("INSERT INTO execution_legs (execution_id,leg_id,status) VALUES ('old','leg','PROCESSING')")
            db.execute("INSERT INTO provider_legs (execution_id,leg_id) VALUES ('old','leg')")
        with patch.dict(os.environ, {'KWIKPAY_EXECUTION_DB': old_path}):
            with closing(sqlite3.connect(old_path)) as db:
                before = db.execute('SELECT * FROM provider_legs').fetchall()
            from execution_store import connection
            with closing(connection()) as db:
                self.assertEqual(db.execute('SELECT * FROM provider_legs').fetchall(), before)
                self.assertEqual(db.execute("SELECT status FROM execution_records WHERE id='old'").fetchone()[0], 'PROCESSING')
                self.assertEqual(db.execute('SELECT count(*) FROM payment_diagnostics').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM schema_migrations WHERE version=5').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT count(*) FROM schema_migrations WHERE version=6').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT count(*) FROM schema_migrations WHERE version=7').fetchone()[0], 1)

    def test_claim_is_single_use_and_requires_prepared_execution(self):
        self.assertFalse(claim_outgoing(self.execution, self.legs[0]))
        self.prepare()
        self.assertTrue(claim_outgoing(self.execution, self.legs[0]))
        self.assertFalse(claim_outgoing(self.execution, self.legs[0]))
        self.assertEqual(next(leg["status"] for leg in get_execution(self.execution)["legs"] if leg["legId"] == self.legs[0]), "PROCESSING")

    def test_reconcile_requires_matching_resource_and_tracks_each_leg(self):
        self.prepare()
        for leg, url in zip(self.legs, self.urls):
            self.assertTrue(claim_outgoing(self.execution, leg))
            record_outgoing(self.execution, leg, url)
            record_outgoing(self.execution, leg, url)
        with self.assertRaises(ValueError):
            record_outgoing(self.execution, self.legs[0], self.urls[1])
        received = lambda value: {"value": value, "assetCode": "ZAR", "assetScale": 2}
        with self.assertRaises(ValueError):
            reconcile_outgoing(self.execution, self.legs[0], self.urls[1], received("80"), False)
        result = reconcile_outgoing(self.execution, self.legs[0], self.urls[0], received("80"), False)
        self.assertEqual(result["status"], "PROCESSING")
        result = reconcile_outgoing(self.execution, self.legs[1], self.urls[1], received("0"), True)
        self.assertEqual(result["status"], "PROCESSING")
        self.assertEqual({leg["status"] for leg in result["legs"]}, {"PROCESSING", "FAILED"})

    def test_incoming_evidence_requires_exact_quote_wallet_and_amount(self):
        self.prepare()
        leg = self.legs[0]
        self.assertTrue(claim_outgoing(self.execution, leg))
        record_outgoing(self.execution, leg, self.urls[0])
        incoming_id = 'https://ilp.interledger-test.dev/tenant/incoming-payments/123'
        with closing(sqlite3.connect(os.environ['KWIKPAY_EXECUTION_DB'])) as db, db:
            db.execute("INSERT INTO test_wallet_sessions (execution_id,state,quotes_json) VALUES (?,?,?)", (self.execution, 'APPROVED', json.dumps([{'receiver': incoming_id}, {'receiver': 'other'}])))
        amount = {'value': '80', 'assetCode': 'ZAR', 'assetScale': 2}
        incoming = {'id': incoming_id, 'walletAddress': self.plan['legs'][0]['walletAddress'], 'completed': True, 'receivedAmount': amount}
        for changed in ({'id': incoming_id + 'wrong'}, {'walletAddress': 'https://wallet.example/other'}, {'receivedAmount': {**amount, 'value': '81'}}, {'completed': 'true'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                record_incoming(self.execution, leg, {**incoming, **changed})
        self.assertIsNone(get_execution(self.execution)['legs'][0]['incomingPayment'])
        record_incoming(self.execution, leg, incoming)
        result = next(item for item in get_execution(self.execution)['legs'] if item['legId'] == leg)
        self.assertEqual(result['incomingPayment']['id'], incoming_id)
        self.assertTrue(result['incomingPayment']['completed'])
        self.assertEqual(result['incomingPayment']['received'], '80')
        self.assertEqual(result['walletStatus'], 'UNVERIFIED')
        with self.assertRaises(ValueError):
            record_incoming(self.execution, leg, {**incoming, 'completed': False})

    def test_partial_receipt_is_not_misreported_and_rejects_bad_data(self):
        self.prepare()
        self.assertTrue(claim_outgoing(self.execution, self.legs[0]))
        record_outgoing(self.execution, self.legs[0], self.urls[0])
        received = lambda value: {"value": value, "assetCode": "ZAR", "assetScale": 2}
        result = reconcile_outgoing(self.execution, self.legs[0], self.urls[0], received("40"), True)
        self.assertEqual(result["status"], "PROCESSING")
        for value in ["39", "81", "-1", "1.5"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                reconcile_outgoing(self.execution, self.legs[0], self.urls[0], received(value), False)
        self.assertEqual(next(leg["status"] for leg in get_execution(self.execution)["legs"] if leg["legId"] == self.legs[0]), "PROCESSING")

    def test_invalid_sent_evidence_does_not_change_reconciliation(self):
        self.prepare()
        claim_outgoing(self.execution, self.legs[0])
        record_outgoing(self.execution, self.legs[0], self.urls[0])
        received = {"value": "80", "assetCode": "ZAR", "assetScale": 2}
        with self.assertRaises(ValueError):
            reconcile_outgoing(self.execution, self.legs[0], self.urls[0], received, False, {**received, "assetCode": "USD"})
        with closing(sqlite3.connect(os.environ["KWIKPAY_EXECUTION_DB"])) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM open_payments_evidence").fetchone()[0], 0)
            self.assertIsNone(db.execute("SELECT received_value FROM provider_legs WHERE execution_id=? AND leg_id=?", (self.execution, self.legs[0])).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
