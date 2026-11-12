import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import mobile_demo_api as demo


class MobileDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), demo.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def call(self, path, body=None):
        request = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.load(exc)

    def test_request_review_and_conflict(self):
        status, created = self.call('/api/mobile-demo/requests', {'amount': '300'})
        self.assertEqual(status, 201)
        self.assertEqual([p['amount'] for p in created['pots']], ['240', '60'])
        path = '/' + created['checkoutUrl'].split('/', 3)[3]
        self.assertEqual(self.call(path)[1]['status'], 'AWAITING_CUSTOMER')
        self.assertEqual(self.call(path + '/review', {'walletAddress': 'http://insecure'})[0], 400)
        self.assertEqual(self.call(path + '/review', {'walletAddress': 'https://wallet.example/customer'})[0], 200)
        self.assertEqual(self.call(path)[1]['status'], 'CUSTOMER_REVIEWING')
        self.assertNotIn('customerWallet', self.call(path)[1])
        self.assertEqual(self.call(path + '/review', {'walletAddress': 'https://wallet.example/other'})[0], 409)
        token = path.rsplit('/', 1)[1]
        demo.requests[token]['expiresAtUnix'] = 0
        self.assertEqual(self.call(path)[0], 410)
        self.assertEqual(self.call(path + '/review', {'walletAddress': 'https://wallet.example/customer'})[0], 410)

    def test_rejects_invalid_amount(self):
        for value in ['1', '0', '-1', '3.00', '100001', 300]:
            self.assertEqual(self.call('/api/mobile-demo/requests', {'amount': value})[0], 400)

    def test_confirm_requires_review_and_is_idempotent(self):
        _, created = self.call('/api/mobile-demo/requests', {'amount': '300'})
        path = '/' + created['checkoutUrl'].split('/', 3)[3]
        body = {'walletAddress': 'https://wallet.example/customer'}
        self.assertEqual(self.call(path + '/confirm', body)[0], 409)
        self.assertEqual(self.call(path + '/review', body)[0], 200)
        self.assertEqual(self.call(path + '/confirm', {'walletAddress': 'https://wallet.example/other'})[0], 409)
        self.assertEqual(self.call(path + '/confirm', body)[1]['status'], 'DEMO_CONFIRMED')
        first = self.call(path)[1]['confirmedAt']
        self.assertEqual(self.call(path + '/confirm', body)[0], 200)
        self.assertEqual(self.call(path + '/review', body)[1]['status'], 'DEMO_CONFIRMED')
        self.assertEqual(self.call(path)[1]['confirmedAt'], first)

    def test_health_marks_demo_mode(self):
        self.assertEqual(self.call('/health'), (200, {'status': 'ok', 'mode': 'demo-no-payments'}))
