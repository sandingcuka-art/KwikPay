import base64
import hashlib
import http.client
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from payment_plan import create_payment_plan
from server import SalesHandler
from test_wallet_service import PAYER

DESTINATIONS = ["https://ilp.interledger-test.dev/kwikpay-merch-1", "https://ilp.interledger-test.dev/kwikpay-merch-2"]


class TestWalletHTTPTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {'KWIKPAY_EXECUTION_DB': os.path.join(temp.name, 'db'), 'KWIKPAY_TEST_WALLET_ENABLED': '1'})
        env.start(); self.addCleanup(env.stop)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), SalesHandler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True); thread.start()
        self.addCleanup(thread.join); self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.auth = 'https://auth.interledger-test.dev/tenant'
        self.pending = {'interact': {'finish': 'server-nonce', 'redirect': self.auth + '/redirect'}, 'continue': {'access_token': {'value': 'secret'}}}
        self.urls = [f'https://ilp.interledger-test.dev/t/outgoing-payments/{i}' for i in range(2)]

    def request(self, method, path, data=None, origin='http://127.0.0.1:5182'):
        with closing(http.client.HTTPConnection(*self.server.server_address, timeout=10)) as conn, patch.object(SalesHandler, 'log_message'):
            conn.request(method, path, body=None if data is None else json.dumps(data), headers={'Content-Type': 'application/json', 'Origin': origin})
            res = conn.getresponse(); body = res.read()
            return res.status, json.loads(body) if body else None

    def test_http_consent_and_per_leg_status(self):
        plan = create_payment_plan({'shopId': 'test', 'saleId': '1', 'payerWalletAddress': PAYER,
            'amount': {'value': '300', 'assetCode': 'ZAR', 'assetScale': 2}, 'rule': {'version': 1, 'destinations': [
            {'label': 'Business', 'walletAddress': DESTINATIONS[1], 'percentage': 80},
            {'label': 'Stock', 'walletAddress': 'https://ilp.interledger-test.dev/kwikpay-merch-3', 'percentage': 20}]}})
        def provider(action, **args):
            if action == 'prepare':
                self.assertEqual(args['legs'], [{'walletAddress': DESTINATIONS[1], 'amountMinor': '240'}, {'walletAddress': 'https://ilp.interledger-test.dev/kwikpay-merch-3', 'amountMinor': '60'}])
                return {'quotes': [{'id': 'q0', 'expiresAt': '2099-01-01T00:00:00Z'}, {'id': 'q1', 'expiresAt': '2099-01-01T00:00:00Z'}], 'debit': '3.00', 'authServer': self.auth}
            if action == 'consent': return {'pending': self.pending, 'redirect': self.pending['interact']['redirect']}
            if action == 'continue': return {'access_token': {'value': 'secret'}}
            if action == 'send': return {'id': self.urls[int(args['quote']['id'][1])]}
            if action == 'poll':
                i = self.urls.index(args['outgoingUrl'])
                self.assertEqual(args['destination'], plan['legs'][i]['walletAddress'])
                return {'outgoing': {'id': self.urls[i], 'failed': False}, 'incoming': {'completed': True, 'receivedAmount': {'value': ['240', '60'][i], 'assetCode': 'ZAR', 'assetScale': 2}}}
            raise AssertionError(action)
        with patch('test_wallet_service.bridge', side_effect=provider), patch('test_wallet_service.secrets.token_urlsafe', return_value='client-nonce'):
            self.assertEqual(self.request('POST', '/api/test-payments/prepare', plan, 'http://other.example')[0], 403)
            status, quote = self.request('POST', '/api/test-payments/prepare', plan)
            self.assertEqual(status, 201)
            execution = quote['executionId']
            self.assertEqual(self.request('POST', '/api/test-payments/consent', {'executionId': execution})[0], 200)
            path = '/api/test-callback/' + execution
            self.assertEqual(self.request('GET', path + '?interact_ref=ref&hash=bad')[0], 400)
            raw = '\n'.join(['client-nonce', 'server-nonce', 'ref', self.auth]).encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
            self.assertEqual(self.request('GET', path + '?interact_ref=ref&hash=' + digest)[0], 303)
            self.assertEqual(self.request('GET', path + '?interact_ref=ref&hash=' + digest)[0], 400)
            status, result = self.request('GET', '/api/payment-executions/' + execution)
            self.assertEqual((status, result['status']), (200, 'PROCESSING'))
            overview = self.request('GET', '/api/sales-overview')[1]
            self.assertEqual(overview['summary']['completedTestSales'], 0)
            self.assertEqual(overview['summary']['confirmedReceipts'], '0')
            self.assertNotIn('secret', json.dumps(result))

    def test_expired_quote_returns_actionable_error_without_authorization(self):
        plan = create_payment_plan({'shopId': 'test', 'saleId': 'expire', 'payerWalletAddress': PAYER,
            'amount': {'value': '100', 'assetCode': 'ZAR', 'assetScale': 2}, 'rule': {'version': 1, 'destinations': [
            {'label': 'Business', 'walletAddress': DESTINATIONS[0], 'percentage': 80},
            {'label': 'Stock', 'walletAddress': DESTINATIONS[1], 'percentage': 20}]}})
        fixture = {'quotes': [{'id': 'q0', 'expiresAt': '2099-01-01T00:00:00Z'}, {'id': 'q1', 'expiresAt': '2099-01-01T00:00:00Z'}], 'debit': '1.00', 'authServer': self.auth}
        with patch('test_wallet_service.bridge', return_value=fixture) as provider:
            status, result = self.request('POST', '/api/test-payments/prepare', plan)
            self.assertEqual(status, 201)
            execution = result['executionId']
            fixture['quotes'][0]['expiresAt'] = '2000-01-01T00:00:00Z'
            with closing(sqlite3.connect(os.environ['KWIKPAY_EXECUTION_DB'])) as db, db:
                db.execute('UPDATE test_wallet_sessions SET quotes_json=? WHERE execution_id=?', (json.dumps(fixture['quotes']), execution))
            status, result = self.request('POST', '/api/test-payments/consent', {'executionId': execution})
            self.assertEqual(status, 400)
            self.assertIn('expired', result['detail'])
            provider.assert_called_once_with('prepare', payerWalletAddress=PAYER, legs=[{'walletAddress': DESTINATIONS[0], 'amountMinor': '80'}, {'walletAddress': DESTINATIONS[1], 'amountMinor': '20'}])
            self.assertEqual(self.request('GET', '/api/payment-executions/' + execution)[1]['status'], 'FAILED')


if __name__ == '__main__': unittest.main()
