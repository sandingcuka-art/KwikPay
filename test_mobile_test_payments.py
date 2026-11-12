import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import json
import urllib.error
import urllib.request
import base64

import mobile_test_payments as mobile


class MobileTestPayments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'KWIKPAY_EXECUTION_DB': self.tmp.name + '/payments.sqlite', 'KWIKPAY_CALLBACK_ORIGIN': 'https://example.up.railway.app', 'KWIKPAY_MERCHANT_KEY': 'unit-test-key', 'KWIKPAY_DASHBOARD_PASSWORD': 'unit-test-password'})
        self.env.start()
        mobile.initialise()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_customer_test_wallet_is_used_and_request_prepared_once(self):
        token = mobile.create_request()
        with self.assertRaises(ValueError):
            mobile.start_request(token, 'https://example.com/other')
        with patch.object(mobile.test_wallet_service, 'prepare', return_value={'executionId': 'exec_' + 'a' * 32, 'debitMinor': '300'}) as prepare, \
             patch.object(mobile.test_wallet_service, 'consent', return_value={'interactUrl': 'https://auth.interledger-test.dev/example'}):
            other = 'https://ilp.interledger-test.dev/other-customer'
            mobile.start_request(token, other)
            self.assertEqual(prepare.call_args.args[0]['payerWalletAddress'], other)
            with self.assertRaises(ValueError):
                mobile.start_request(token, mobile.PAYER)
            self.assertEqual(prepare.call_count, 1)
        self.assertEqual(mobile.request_row(token)[1], 'AWAITING_CONSENT')

    def test_dashboard_amount_limits_and_saved_split(self):
        for value in ('0', '1', '1001', '10000', '-1', '3.00', '', 'NaN', 1000, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mobile.create_request(value)
        result = mobile.public_request(mobile.create_request('999'))
        self.assertEqual(result['amount'], '999')
        self.assertEqual([p['amount'] for p in result['pots']], ['799', '200'])
        config = mobile.read_config()
        config['pots'][0]['percentage'], config['pots'][1]['percentage'] = 1, 99
        mobile.save_config(config)
        with self.assertRaisesRegex(ValueError, 'each pot'):
            mobile.create_request('2')

    def test_quote_must_not_exceed_the_requested_sale(self):
        token = mobile.create_request('200')
        with patch.object(mobile.test_wallet_service, 'prepare', return_value={'executionId': 'exec_' + 'a' * 32, 'debitMinor': '201'}), \
             patch.object(mobile.test_wallet_service, 'consent') as consent:
            with self.assertRaisesRegex(ValueError, 'exceeds the sale amount'):
                mobile.start_request(token, mobile.PAYER)
            consent.assert_not_called()
        self.assertEqual(mobile.request_row(token)[1], 'PREPARATION_FAILED')

    def test_poll_stops_only_after_matching_complete_evidence(self):
        plan = mobile.make_plan(mobile.read_config())
        legs = [{'legId': leg['id'], 'status': 'PROCESSING', 'incomingPayment': {'completed': True, 'received': leg['amount']['value']}, 'openPayments': {'sent': leg['amount']['value'], 'received': leg['amount']['value']}} for leg in plan['legs']]
        execution = {'plan': plan, 'legs': legs}
        self.assertFalse(mobile.needs_poll(execution))
        legs[1]['incomingPayment']['completed'] = False
        self.assertTrue(mobile.needs_poll(execution))
        legs[1]['incomingPayment']['completed'] = True
        legs[1]['openPayments']['received'] = '0'
        self.assertTrue(mobile.needs_poll(execution))

    def test_split_is_calculated_and_snapshotted_by_api(self):
        old = mobile.create_request()
        config = mobile.read_config()
        config['pots'][0]['percentage'], config['pots'][1]['percentage'] = 60, 40
        config['pots'][0]['label'] = 'Operating'
        updated = mobile.save_config(config)
        self.assertEqual(updated['version'], 2)
        new = mobile.create_request()
        self.assertEqual([p['amount'] for p in mobile.public_request(old)['pots']], ['240', '60'])
        self.assertEqual([p['amount'] for p in mobile.public_request(new)['pots']], ['180', '120'])
        self.assertEqual(mobile.public_request(new)['pots'][0]['label'], 'Operating')
        with patch.object(mobile.test_wallet_service, 'prepare', return_value={'executionId': 'exec_' + 'a' * 32, 'debitMinor': '300'}) as prepare, \
             patch.object(mobile.test_wallet_service, 'consent', return_value={'interactUrl': 'https://auth.interledger-test.dev/example'}):
            mobile.start_request(new, mobile.PAYER)
            plan = prepare.call_args.args[0]
            self.assertEqual([leg['amount']['value'] for leg in plan['legs']], ['180', '120'])
            self.assertEqual(plan['ruleVersion'], 2)
        with self.assertRaises(ValueError):
            mobile.save_config(config)

    def test_config_rejects_invalid_destinations_and_percentages(self):
        config = mobile.read_config()
        config['pots'][0]['walletAddress'] = 'https://evil.example/merchant'
        with self.assertRaises(ValueError): mobile.save_config(config)
        config = mobile.read_config()
        config['pots'][0]['percentage'] = 0
        with self.assertRaises(ValueError): mobile.save_config(config)
        config = mobile.read_config()
        config['pots'][0]['percentage'] = 50
        with self.assertRaises(ValueError): mobile.save_config(config)

    def test_legacy_mobile_rows_survive_additive_migration(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'KWIKPAY_EXECUTION_DB': temp + '/old.sqlite'}):
            with mobile.closing(mobile.connection()) as db, db:
                db.execute('CREATE TABLE mobile_requests (token_hash TEXT PRIMARY KEY, created INTEGER NOT NULL, expires INTEGER NOT NULL, state TEXT NOT NULL, execution_id TEXT, debit TEXT, redirect TEXT)')
                db.execute("INSERT INTO mobile_requests VALUES ('old-hash',1,2,'PROCESSING','exec_old',NULL,NULL)")
            mobile.initialise()
            mobile.initialise()
            with mobile.closing(mobile.connection()) as db:
                self.assertEqual(db.execute("SELECT state,execution_id,snapshot_json FROM mobile_requests WHERE token_hash='old-hash'").fetchone(), ('PROCESSING', 'exec_old', None))
            self.assertEqual(mobile.read_config()['version'], 1)

    def test_dashboard_reports_observations_without_confirming_settlement(self):
        from execution_store import create_execution
        token = mobile.create_request()
        plan = json.loads(mobile.request_row(token)[5])
        execution = create_execution(plan)
        execution_id = execution['executionId']
        with mobile.closing(mobile.connection()) as db, db:
            db.execute("UPDATE mobile_requests SET execution_id=?,state='PROCESSING' WHERE token_hash=?", (execution_id, mobile.token_hash(token)))
            db.execute("INSERT INTO test_wallet_sessions(execution_id,state) VALUES (?, 'APPROVED')", (execution_id,))
            db.execute("UPDATE execution_records SET status='PROCESSING' WHERE id=?", (execution_id,))
            for leg in plan['legs']:
                db.execute("UPDATE execution_legs SET status='PROCESSING' WHERE execution_id=? AND leg_id=?", (execution_id, leg['id']))
                db.execute('INSERT INTO provider_legs(execution_id,leg_id) VALUES (?,?)', (execution_id, leg['id']))
                db.execute('INSERT INTO open_payments_evidence(execution_id,leg_id,sent_value,received_value) VALUES (?,?,?,?)', (execution_id, leg['id'], leg['amount']['value'], leg['amount']['value']))
        with patch.object(mobile, 'schedule_poll'):
            overview = mobile.dashboard_overview()
        self.assertEqual(overview['summary']['recordCount'], 1)
        self.assertEqual(overview['summary']['observedSent'], '300')
        self.assertEqual(overview['summary']['observedReceived'], '300')
        self.assertEqual(overview['history'][0]['status'], 'PROCESSING')
        self.assertTrue(all(leg['walletStatus'] == 'UNVERIFIED' for leg in overview['history'][0]['legs']))
        first, second = [leg['id'] for leg in plan['legs']]
        mobile.record_manual_verification(execution_id, {'legId': first, 'verified': True})
        mobile.record_manual_verification(execution_id, {'legId': first, 'verified': True})
        with patch.object(mobile, 'schedule_poll'):
            confirmed = mobile.dashboard_overview()['history'][0]
        self.assertIsNotNone(confirmed['legs'][0]['manuallyVerifiedAt'])
        self.assertIsNone(confirmed['legs'][1]['manuallyVerifiedAt'])
        self.assertEqual(confirmed['legs'][0]['walletStatus'], 'UNVERIFIED')
        self.assertEqual(confirmed['status'], 'PROCESSING')
        with mobile.closing(mobile.connection()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM manual_verification_events').fetchone()[0], 1)
        mobile.record_manual_verification(execution_id, {'legId': first, 'verified': False})
        with patch.object(mobile, 'schedule_poll'):
            self.assertIsNone(mobile.dashboard_overview()['history'][0]['legs'][0]['manuallyVerifiedAt'])
        with mobile.closing(mobile.connection()) as db, db:
            db.execute('DELETE FROM open_payments_evidence WHERE execution_id=? AND leg_id=?', (execution_id, second))
        with self.assertRaises(ValueError):
            mobile.record_manual_verification(execution_id, {'legId': second, 'verified': True})
        with self.assertRaises(ValueError):
            mobile.record_manual_verification(execution_id, {'legId': 'leg_unknown', 'verified': True})
        with self.assertRaises(ValueError):
            mobile.record_manual_verification(execution_id, {'legId': first, 'verified': 'true'})
        updated = mobile.read_config()
        updated['pots'][0]['label'] = 'Renamed pot'
        updated['pots'][0]['percentage'], updated['pots'][1]['percentage'] = 60, 40
        mobile.save_config(updated)
        with patch.object(mobile, 'schedule_poll'):
            later = mobile.dashboard_overview()
        self.assertEqual([leg['planned'] for leg in later['history'][0]['legs']], ['240', '60'])
        self.assertEqual(later['history'][0]['legs'][0]['label'], 'Business income')

    def test_failed_or_expired_request_is_not_retried(self):
        token = mobile.create_request()
        with patch.object(mobile.test_wallet_service, 'prepare', side_effect=RuntimeError('failed')) as prepare:
            with self.assertRaises(RuntimeError):
                mobile.start_request(token, mobile.PAYER)
            with self.assertRaises(ValueError):
                mobile.start_request(token, mobile.PAYER)
            self.assertEqual(prepare.call_count, 1)
        token = mobile.create_request()
        with mobile.closing(mobile.connection()) as db, db:
            db.execute('UPDATE mobile_requests SET expires=? WHERE token_hash=?', (int(time.time()) - 1, mobile.token_hash(token)))
        with self.assertRaises(ValueError):
            mobile.start_request(token, mobile.PAYER)

    def test_oversized_quote_never_requests_consent(self):
        token = mobile.create_request()
        with patch.object(mobile.test_wallet_service, 'prepare', return_value={'executionId': 'exec_' + 'a' * 32, 'debitMinor': '301'}), \
             patch.object(mobile.test_wallet_service, 'consent') as consent:
            with self.assertRaises(ValueError):
                mobile.start_request(token, mobile.PAYER)
            consent.assert_not_called()
        self.assertEqual(mobile.request_row(token)[1], 'PREPARATION_FAILED')

    def test_callback_rejects_bad_hash_and_does_not_run_twice(self):
        token = mobile.create_request()
        execution = 'exec_' + 'b' * 32
        with mobile.closing(mobile.connection()) as db, db:
            db.execute("UPDATE mobile_requests SET state='AWAITING_CONSENT', execution_id=? WHERE token_hash=?", (execution, mobile.token_hash(token)))
        server = ThreadingHTTPServer(('127.0.0.1', 0), mobile.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/api/test-callback/{execution}?interact_ref=x&hash=y'
        with patch.object(mobile.test_wallet_service, 'finish', side_effect=ValueError('invalid')):
            with self.assertRaises(urllib.error.HTTPError) as bad:
                urllib.request.urlopen(url)
            self.assertEqual(bad.exception.code, 400)
            bad.exception.close()
        self.assertEqual(mobile.request_row(token)[1], 'AWAITING_CONSENT')
        def verified_finish(*args, on_verified):
            on_verified()
            self.assertEqual(mobile.request_row(token)[1], 'PROCESSING')
        with patch.object(mobile.test_wallet_service, 'finish', side_effect=verified_finish) as finish:
            with urllib.request.urlopen(url) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), 'text/html')
                self.assertIn(b'Return to KwikPay', response.read())
                self.assertTrue(response.url.endswith('/payment-return?status=processing'))
            with self.assertRaises(urllib.error.HTTPError) as duplicate:
                urllib.request.urlopen(url)
            self.assertEqual(duplicate.exception.code, 400)
            duplicate.exception.close()
            finish.assert_called_once()
        self.assertEqual(mobile.request_row(token)[1], 'PROCESSING')

    def test_creation_requires_merchant_key_and_respects_amount_limit(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), mobile.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/api/mobile-test/requests'
        def post(value, key):
            req = urllib.request.Request(url, data=json.dumps({'amount': value}).encode(), headers={'Content-Type': 'application/json', 'X-KwikPay-Merchant-Key': key})
            try:
                with urllib.request.urlopen(req) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                with error:
                    return error.code, json.load(error)
        self.assertEqual(post('300', 'wrong')[0], 403)
        self.assertEqual(post('1001', 'unit-test-key')[0], 400)
        self.assertEqual(post('1', 'unit-test-key')[0], 400)
        status, maximum = post('1000', 'unit-test-key')
        self.assertEqual(status, 201)
        self.assertEqual([pot['amount'] for pot in maximum['pots']], ['800', '200'])
        status, data = post('300', 'unit-test-key')
        self.assertEqual(status, 201)
        self.assertEqual([pot['amount'] for pot in data['pots']], ['240', '60'])

    def test_signed_apk_download_requires_dashboard_auth(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), mobile.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close); self.addCleanup(thread.join); self.addCleanup(server.shutdown)
        downloads = self.tmp.name + '/downloads'
        os.mkdir(downloads)
        name = 'kwikpay-customer-0.2.0.apk'
        with open(downloads + '/' + name, 'wb') as f: f.write(b'example-apk')
        base = f'http://127.0.0.1:{server.server_port}'
        auth = 'Basic ' + base64.b64encode(b'merchant:unit-test-password').decode()
        with patch.dict(os.environ, {'KWIKPAY_DOWNLOADS_DIR': downloads}):
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(base + '/downloads/' + name)
            self.assertEqual(denied.exception.code, 401)
            denied.exception.close()
            request = urllib.request.Request(base + '/downloads/' + name, headers={'Authorization': auth})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b'example-apk')
                self.assertEqual(response.headers['Content-Type'], 'application/vnd.android.package-archive')
                self.assertIn(name, response.headers['Content-Disposition'])
                self.assertIn('no-store', response.headers['Cache-Control'])
            for invalid in ('/downloads/other.apk', '/downloads/' + name + '?x=1'):
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    urllib.request.urlopen(urllib.request.Request(base + invalid, headers={'Authorization': auth}))
                self.assertEqual(missing.exception.code, 404)
                missing.exception.close()

    def test_dashboard_auth_origin_and_mobile_config_access(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), mobile.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        auth = 'Basic ' + base64.b64encode(b'merchant:unit-test-password').decode()
        def call(path, data=None, headers=None):
            request = urllib.request.Request(base + path, data=None if data is None else json.dumps(data).encode(), headers=headers or {})
            try:
                with urllib.request.urlopen(request) as response: return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                with error: return error.code, None
        self.assertEqual(call('/api/dashboard/config')[0], 401)
        self.assertEqual(call('/api/dashboard/requests', {'amount': '300'}, {'Content-Type': 'application/json'})[0], 401)
        self.assertEqual(call('/api/dashboard/config', headers={'Authorization': 'Basic !!!'})[0], 401)
        self.assertEqual(call('/api/mobile-test/config')[0], 403)
        self.assertEqual(call('/api/mobile-test/config', headers={'X-KwikPay-Merchant-Key': 'unit-test-key'})[0], 200)
        cfg = call('/api/dashboard/config', headers={'Authorization': auth})[1]
        cfg['pots'][0]['percentage'], cfg['pots'][1]['percentage'] = 70, 30
        headers = {'Authorization': auth, 'Origin': 'https://attacker.example', 'Content-Type': 'application/json'}
        self.assertEqual(call('/api/dashboard/config', cfg, headers)[0], 403)
        self.assertEqual(call('/api/dashboard/requests', {'amount': '300'}, headers)[0], 403)
        verification = '/api/dashboard/sales/exec_' + 'a' * 32 + '/manual-verification'
        self.assertEqual(call(verification, {'legId': 'leg_x', 'verified': True}, {'Content-Type': 'application/json'})[0], 401)
        self.assertEqual(call(verification, {'legId': 'leg_x', 'verified': True}, headers)[0], 403)
        self.assertEqual(mobile.read_config()['version'], 1)
        headers['Origin'] = 'https://example.up.railway.app'
        self.assertEqual(call('/api/dashboard/requests', {'amount': '1001'}, headers)[0], 400)
        max_status, max_sale = call('/api/dashboard/requests', {'amount': '1000'}, headers)
        self.assertEqual(max_status, 201)
        self.assertEqual(max_sale['amount'], '1000')
        self.assertEqual([pot['amount'] for pot in max_sale['pots']], ['800', '200'])
        request_status, request_data = call('/api/dashboard/requests', {'amount': '300'}, headers)
        self.assertEqual(request_status, 201)
        self.assertTrue(request_data['checkoutUrl'].startswith('https://example.up.railway.app/api/mobile-test/requests/'))
        self.assertEqual([pot['amount'] for pot in request_data['pots']], ['240', '60'])
        status, saved = call('/api/dashboard/config', cfg, headers)
        self.assertEqual(status, 200)
        self.assertEqual(saved['version'], 2)
        self.assertEqual([pot['amount'] for pot in mobile.public_request(mobile.create_request())['pots']], ['210', '90'])
        from execution_store import create_execution
        token = mobile.create_request()
        plan = json.loads(mobile.request_row(token)[5])
        execution_id = create_execution(plan)['executionId']
        leg = plan['legs'][0]
        with mobile.closing(mobile.connection()) as db, db:
            db.execute("UPDATE mobile_requests SET execution_id=?,state='PROCESSING' WHERE token_hash=?", (execution_id, mobile.token_hash(token)))
            db.execute("INSERT INTO test_wallet_sessions(execution_id,state) VALUES (?, 'APPROVED')", (execution_id,))
            db.execute("INSERT INTO open_payments_evidence(execution_id,leg_id,sent_value,received_value) VALUES (?,?,?,?)", (execution_id, leg['id'], leg['amount']['value'], leg['amount']['value']))
        path = f'/api/dashboard/sales/{execution_id}/manual-verification'
        self.assertEqual(call(path, {'legId': leg['id'], 'verified': True}, headers)[0], 200)
        with patch.object(mobile, 'schedule_poll'):
            overview = call('/api/dashboard/sales-overview', headers={'Authorization': auth})[1]
        self.assertIsNotNone(overview['history'][0]['legs'][0]['manuallyVerifiedAt'])
        self.assertEqual(overview['history'][0]['legs'][0]['walletStatus'], 'UNVERIFIED')


if __name__ == '__main__':
    unittest.main()
