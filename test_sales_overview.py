import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from execution_store import create_execution, get_execution, sales_overview
from payment_plan import create_payment_plan


class SalesOverviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {'KWIKPAY_EXECUTION_DB': os.path.join(temp.name, 'history.sqlite')})
        env.start(); self.addCleanup(env.stop)

    def record(self, status, *, test_wallet=False, received=()):
        plan = create_payment_plan({'shopId': 'demo', 'saleId': 'test', 'payerWalletAddress': 'https://wallet.example/customer',
            'amount': {'value': '100', 'assetCode': 'ZAR', 'assetScale': 2}, 'rule': {'version': 1, 'destinations': [
                {'label': 'Business', 'walletAddress': 'https://wallet.example/business', 'percentage': 80},
                {'label': 'Stock', 'walletAddress': 'https://wallet.example/stock', 'percentage': 20}]}})
        execution = create_execution(plan)['executionId']
        with closing(sqlite3.connect(os.environ['KWIKPAY_EXECUTION_DB'])) as db, db:
            db.execute('UPDATE execution_records SET status=? WHERE id=?', (status, execution))
            if test_wallet:
                db.execute("INSERT INTO test_wallet_sessions (execution_id,state,grant_json) VALUES (?,'APPROVED',?)", (execution, '{"token":"never expose"}'))
                for index, value in enumerate(received):
                    db.execute('INSERT INTO provider_legs (execution_id,leg_id,received_value) VALUES (?,?,?)', (execution, plan['legs'][index]['id'], value))
                    db.execute("UPDATE execution_legs SET status='COMPLETED' WHERE execution_id=? AND leg_id=?", (execution, plan['legs'][index]['id']))
        return execution

    def test_empty_history(self):
        result = sales_overview()
        self.assertEqual(result['history'], [])
        self.assertEqual(result['summary']['confirmedReceipts'], '0')

    def test_counts_confirmed_receipts_without_treating_tracking_as_payment(self):
        old = self.record('COMPLETED', test_wallet=True, received=('80', '20'))
        self.record('PROCESSING', test_wallet=True, received=('80',))
        self.record('COMPLETED')
        result = sales_overview(); summary = result['summary']
        self.assertEqual(summary['recordCount'], 3)
        self.assertEqual(summary['completedTestSales'], 0)
        self.assertEqual(summary['completedSalesValue'], '0')
        self.assertEqual(summary['confirmedReceipts'], '0')
        self.assertEqual(summary['confirmedByPot'], [])
        self.assertEqual(summary['statusCounts']['PROCESSING'], 2)
        self.assertEqual(result['history'][0]['source'], 'tracking')
        self.assertNotIn('never expose', json.dumps(result))
        self.assertNotIn('wallet.example', json.dumps(result))
        self.assertEqual(get_execution(old)['status'], 'PROCESSING')
        self.assertEqual({leg['status'] for leg in get_execution(old)['legs']}, {'PROCESSING'})
        with closing(sqlite3.connect(os.environ['KWIKPAY_EXECUTION_DB'])) as db:
            self.assertEqual(db.execute('SELECT status FROM execution_records WHERE id=?', (old,)).fetchone()[0], 'COMPLETED')
            self.assertEqual(db.execute('SELECT received_value FROM provider_legs WHERE execution_id=? ORDER BY received_value', (old,)).fetchall(), [('20',), ('80',)])

    def test_reports_cover_all_records_beyond_recent_history_limit(self):
        for _ in range(101): self.record('COMPLETED', test_wallet=True, received=('80', '20'))
        result = sales_overview()
        self.assertEqual(len(result['history']), 100)
        self.assertEqual(result['summary']['recordCount'], 101)
        self.assertEqual(result['summary']['completedSalesValue'], '0')
        self.assertEqual(result['summary']['confirmedReceipts'], '0')
        self.assertEqual(len(sales_overview(100)['history']), 1)
        self.assertEqual(sales_overview(100)['summary'], result['summary'])


if __name__ == '__main__': unittest.main()
