import base64
from contextlib import closing
import hashlib
import json
import os
import sqlite3
import subprocess
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from payment_plan import create_payment_plan
from test_wallet_service import PAYER, BridgeError, bridge, prepare, consent, finish, poll, quote_valid

DESTINATIONS = ["https://ilp.interledger-test.dev/kwikpay-merch-1", "https://ilp.interledger-test.dev/kwikpay-merch-2"]


class TestWalletFlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"KWIKPAY_EXECUTION_DB": os.path.join(temp.name, "test.sqlite")})
        env.start()
        self.addCleanup(env.stop)
        self.plan = create_payment_plan({"shopId": "test", "saleId": "one", "payerWalletAddress": PAYER,
            "amount": {"value": "100", "assetCode": "ZAR", "assetScale": 2}, "rule": {"version": 1, "destinations": [
                {"label": "Business", "walletAddress": DESTINATIONS[0], "percentage": 80},
                {"label": "Stock", "walletAddress": DESTINATIONS[1], "percentage": 20}]}})
        self.auth = 'https://auth.interledger-test.dev/tenant'
        self.pending = {"interact": {"finish": "provider-nonce", "redirect": "https://auth.interledger-test.dev/redirect"}, "continue": {"access_token": {"value": "secret"}}}
        self.urls = [f'https://ilp.interledger-test.dev/tenant/outgoing-payments/{i}' for i in range(2)]
        self.incoming_urls = [f'https://ilp.interledger-test.dev/tenant/incoming-payments/{i}' for i in range(2)]

    def test_consent_verified_once_and_each_leg_reconciled(self):
        calls = []
        self.plan['payerWalletAddress'] = 'https://ilp.interledger-test.dev/team-member'
        def provider(action, **args):
            calls.append(action)
            if action in ('prepare', 'consent', 'send'):
                self.assertEqual(args['payerWalletAddress'], self.plan['payerWalletAddress'])
            if action == 'prepare': return {'quotes': [{'id': 'q0', 'receiver': self.incoming_urls[0], 'expiresAt': '2099-01-01T00:00:00Z'}, {'id': 'q1', 'receiver': self.incoming_urls[1], 'expiresAt': '2099-01-01T00:00:00Z'}], 'debit': '1.00', 'authServer': self.auth}
            if action == 'consent': return {'pending': self.pending, 'redirect': self.pending['interact']['redirect']}
            if action == 'continue': return {'access_token': {'value': 'secret'}}
            if action == 'send': return {'id': self.urls[int(args['quote']['id'][1])]}
            if action == 'poll':
                i = self.urls.index(args['outgoingUrl'])
                amount = {'value': ['80', '20'][i], 'assetCode': 'ZAR', 'assetScale': 2}
                return {'outgoing': {'id': self.urls[i], 'failed': False, 'sentAmount': amount}, 'incoming': {'id': self.incoming_urls[i], 'walletAddress': DESTINATIONS[i], 'completed': True, 'receivedAmount': amount}}
            raise AssertionError(action)
        with patch('test_wallet_service.bridge', side_effect=provider), patch('test_wallet_service.secrets.token_urlsafe', return_value='client-nonce'):
            quote = prepare(self.plan)
            execution = quote['executionId']
            self.assertEqual(quote['debitMinor'], '100')
            self.assertEqual(consent(execution), {'interactUrl': self.pending['interact']['redirect']})
            self.assertEqual(consent(execution), {'interactUrl': self.pending['interact']['redirect']})
            self.assertEqual(calls.count('consent'), 1)
            with self.assertRaises(ValueError): finish(execution, 'ref', 'bad')
            self.assertNotIn('continue', calls)
            raw = '\n'.join(['client-nonce', 'provider-nonce', 'ref', self.auth]).encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
            self.assertEqual(finish(execution, 'ref', digest)['status'], 'PROCESSING')
            with self.assertRaises(ValueError): finish(execution, 'ref', digest)
            self.assertEqual(calls.count('send'), 2)
            result = poll(execution)
            self.assertEqual(result['status'], 'PROCESSING')
            self.assertEqual({leg['status'] for leg in result['legs']}, {'PROCESSING'})
            self.assertEqual({leg['walletStatus'] for leg in result['legs']}, {'UNVERIFIED'})
            self.assertEqual({leg['openPayments']['sent'] for leg in result['legs']}, {'80', '20'})
            self.assertEqual({leg['openPayments']['received'] for leg in result['legs']}, {'80', '20'})
            self.assertTrue(all(leg['openPayments']['observedAt'] for leg in result['legs']))
            self.assertEqual({leg['incomingPayment']['id'] for leg in result['legs']}, set(self.incoming_urls))
            self.assertTrue(all(leg['incomingPayment']['completed'] for leg in result['legs']))
            self.assertNotIn('secret', json.dumps(result))

    def test_expired_outgoing_grant_can_still_match_incoming_without_sending(self):
        from execution_store import create_execution, claim_outgoing, record_outgoing
        execution = create_execution(self.plan)['executionId']
        leg = self.plan['legs'][0]['id']
        with closing(sqlite3.connect(os.environ['KWIKPAY_EXECUTION_DB'])) as db, db:
            db.execute("UPDATE execution_records SET status='PROCESSING' WHERE id=?", (execution,))
            db.execute("UPDATE execution_legs SET status='PREPARED' WHERE execution_id=?", (execution,))
            quotes = [{'receiver': self.incoming_urls[0]}, {'receiver': self.incoming_urls[1]}]
            db.execute("INSERT INTO test_wallet_sessions (execution_id,state,quotes_json,grant_json) VALUES (?,?,?,?)", (execution, 'APPROVED', json.dumps(quotes), '{}'))
        self.assertTrue(claim_outgoing(execution, leg))
        record_outgoing(execution, leg, self.urls[0])
        amount = {'value': '80', 'assetCode': 'ZAR', 'assetScale': 2}
        def provider(action, **args):
            if action == 'poll': raise BridgeError('provider_error', 401)
            if action == 'incoming':
                self.assertEqual(args['incomingUrl'], self.incoming_urls[0])
                return {'id': self.incoming_urls[0], 'walletAddress': DESTINATIONS[0], 'completed': True, 'receivedAmount': amount}
            raise AssertionError('No payment may be sent')
        with patch('test_wallet_service.bridge', side_effect=provider) as client:
            result = poll(execution)
        matched = next(item for item in result['legs'] if item['legId'] == leg)
        self.assertTrue(matched['incomingPayment']['completed'])
        self.assertEqual(matched['incomingPayment']['id'], self.incoming_urls[0])
        self.assertEqual(matched['walletStatus'], 'UNVERIFIED')
        self.assertEqual([call.args[0] for call in client.call_args_list], ['poll', 'incoming'])

    def test_rejects_invalid_destinations_and_zero_legs_before_provider(self):
        from copy import deepcopy
        for field, value in [('walletAddress', 'https://example.com/wallet'), ('amount', {'value': '0', 'assetCode': 'ZAR', 'assetScale': 2})]:
            plan = deepcopy(self.plan)
            plan['legs'][0][field] = value
            with self.subTest(field=field), patch('test_wallet_service.bridge') as provider:
                with self.assertRaises(ValueError):
                    prepare(plan)
                provider.assert_not_called()

    def test_other_test_wallet_flows_to_bridge_and_unsafe_wallets_rejected(self):
        from copy import deepcopy
        fixture = {'quotes': [{'id': 'q0', 'expiresAt': '2099-01-01T00:00:00Z'}, {'id': 'q1', 'expiresAt': '2099-01-01T00:00:00Z'}], 'debit': '1.00', 'authServer': self.auth}
        plan = deepcopy(self.plan)
        plan['payerWalletAddress'] = 'https://ilp.interledger-test.dev/another-customer'
        with patch('test_wallet_service.bridge', return_value=fixture) as client:
            prepare(plan)
            self.assertEqual(client.call_args.kwargs['payerWalletAddress'], plan['payerWalletAddress'])
        for bad in ('https://evil.example/wallet', 'https://ilp.interledger-test.dev/', 'https://ilp.interledger-test.dev/wallet?token=x'):
            plan['payerWalletAddress'] = bad
            with self.subTest(wallet=bad), self.assertRaises(ValueError):
                prepare(plan)

    def test_unknown_submission_is_not_retried(self):
        def provider(action, **args):
            if action == 'prepare': return {'quotes': [{'id': 'q0', 'expiresAt': '2099-01-01T00:00:00Z'}, {'id': 'q1', 'expiresAt': '2099-01-01T00:00:00Z'}], 'debit': '1.00', 'authServer': self.auth}
            if action == 'consent': return {'pending': self.pending, 'redirect': self.pending['interact']['redirect']}
            if action == 'continue': return {'access_token': {'value': 'secret'}}
            if action == 'send': raise RuntimeError('ambiguous timeout')
            raise AssertionError(action)
        with patch('test_wallet_service.bridge', side_effect=provider) as client, patch('test_wallet_service.secrets.token_urlsafe', return_value='client-nonce'):
            execution = prepare(self.plan)['executionId']
            consent(execution)
            data = '\n'.join(['client-nonce', 'provider-nonce', 'ref', self.auth]).encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            result = finish(execution, 'ref', digest)
            self.assertEqual(result['status'], 'PROCESSING')
            poll(execution)
            self.assertEqual(sum(call.args[0] == 'send' for call in client.call_args_list), 2)

    def test_expired_before_consent_does_not_request_authorization(self):
        fixture = {'quotes': [{'id': 'q0', 'expiresAt': '2099-01-01T00:00:00Z'}, {'id': 'q1', 'expiresAt': '2099-01-01T00:00:00Z'}], 'debit': '1.00', 'authServer': self.auth}
        with patch('test_wallet_service.bridge', return_value=fixture) as client:
            execution = prepare(self.plan)['executionId']
            with closing(sqlite3.connect(os.environ['KWIKPAY_EXECUTION_DB'])) as db, db:
                fixture['quotes'][0]['expiresAt'] = '2000-01-01T00:00:00Z'
                db.execute('UPDATE test_wallet_sessions SET quotes_json=? WHERE execution_id=?', (json.dumps(fixture['quotes']), execution))
            with self.assertRaisesRegex(ValueError, 'expired'):
                consent(execution)
            client.assert_called_once_with('prepare', payerWalletAddress=PAYER, legs=[{'walletAddress': DESTINATIONS[0], 'amountMinor': '80'}, {'walletAddress': DESTINATIONS[1], 'amountMinor': '20'}])
            with closing(sqlite3.connect(os.environ['KWIKPAY_EXECUTION_DB'])) as db, db:
                self.assertEqual(db.execute('SELECT status FROM execution_records WHERE id=?', (execution,)).fetchone()[0], 'FAILED')
                self.assertEqual(db.execute('SELECT count(*) FROM provider_legs WHERE execution_id=?', (execution,)).fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT count(*) FROM payment_diagnostics WHERE execution_id=? AND outcome='quote_expired'", (execution,)).fetchone()[0], 2)

    def test_expired_after_approval_does_not_continue_or_send(self):
        fixture = {'quotes': [{'id': 'q0', 'expiresAt': '2099-01-01T00:00:00Z'}, {'id': 'q1', 'expiresAt': '2099-01-01T00:00:00Z'}], 'debit': '1.00', 'authServer': self.auth}
        def provider(action, **args):
            if action == 'prepare': return fixture
            if action == 'consent': return {'pending': self.pending, 'redirect': self.pending['interact']['redirect']}
            raise AssertionError('No grant continuation or send should occur')
        with patch('test_wallet_service.bridge', side_effect=provider) as client, patch('test_wallet_service.secrets.token_urlsafe', return_value='client-nonce'):
            execution = prepare(self.plan)['executionId']
            consent(execution)
            with closing(sqlite3.connect(os.environ['KWIKPAY_EXECUTION_DB'])) as db, db:
                fixture['quotes'][1]['expiresAt'] = '2000-01-01T00:00:00Z'
                db.execute('UPDATE test_wallet_sessions SET quotes_json=? WHERE execution_id=?', (json.dumps(fixture['quotes']), execution))
            data = '\n'.join(['client-nonce', 'provider-nonce', 'ref', self.auth]).encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            result = finish(execution, 'ref', digest)
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual([call.args[0] for call in client.call_args_list], ['prepare', 'consent'])
            with closing(sqlite3.connect(os.environ['KWIKPAY_EXECUTION_DB'])) as db, db:
                self.assertEqual(db.execute('SELECT count(*) FROM provider_legs WHERE execution_id=?', (execution,)).fetchone()[0], 0)

    def test_expired_second_leg_and_ambiguous_first_preserve_partial_state(self):
        fixture = {'quotes': [{'id': 'q0', 'expiresAt': '2099-01-01T00:00:00Z'}, {'id': 'q1', 'expiresAt': '2099-01-01T00:00:00Z'}], 'debit': '1.00', 'authServer': self.auth}
        def provider(action, **args):
            if action == 'prepare': return fixture
            if action == 'consent': return {'pending': self.pending, 'redirect': self.pending['interact']['redirect']}
            if action == 'continue': return {'access_token': {'value': 'secret'}}
            if action == 'send': raise BridgeError('provider_error', 503)
            raise AssertionError(action)
        with patch('test_wallet_service.bridge', side_effect=provider) as client, patch('test_wallet_service.secrets.token_urlsafe', return_value='client-nonce'):
            execution = prepare(self.plan)['executionId']; consent(execution)
            data = '\n'.join(['client-nonce', 'provider-nonce', 'ref', self.auth]).encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            with patch('test_wallet_service.quote_valid', side_effect=[True, True, True, False]):
                result = finish(execution, 'ref', digest)
            self.assertEqual(result['status'], 'PROCESSING')
            self.assertEqual([call.args[0] for call in client.call_args_list].count('send'), 1)
            self.assertEqual({item['status'] for item in result['legs']}, {'PROCESSING', 'FAILED'})
            with closing(sqlite3.connect(os.environ['KWIKPAY_EXECUTION_DB'])) as db, db:
                diagnostics = db.execute('SELECT outcome, provider_status FROM payment_diagnostics WHERE execution_id=?', (execution,)).fetchall()
                self.assertIn(('attempt_started', None), diagnostics)
                self.assertIn(('provider_error', 503), diagnostics)
                self.assertIn(('quote_expired', None), diagnostics)

    def test_first_leg_reconciles_when_second_expires(self):
        fixture = {'quotes': [{'id': 'q0', 'expiresAt': '2099-01-01T00:00:00Z'}, {'id': 'q1', 'expiresAt': '2099-01-01T00:00:00Z'}], 'debit': '1.00', 'authServer': self.auth}
        def provider(action, **args):
            if action == 'prepare': return fixture
            if action == 'consent': return {'pending': self.pending, 'redirect': self.pending['interact']['redirect']}
            if action == 'continue': return {'access_token': {'value': 'secret'}}
            if action == 'send': return {'id': self.urls[0]}
            if action == 'poll': return {'outgoing': {'id': self.urls[0], 'failed': False}, 'incoming': {'completed': True, 'receivedAmount': {'value': '80', 'assetCode': 'ZAR', 'assetScale': 2}}}
            raise AssertionError(action)
        with patch('test_wallet_service.bridge', side_effect=provider) as client, patch('test_wallet_service.secrets.token_urlsafe', return_value='client-nonce'):
            execution = prepare(self.plan)['executionId']; consent(execution)
            data = '\n'.join(['client-nonce', 'provider-nonce', 'ref', self.auth]).encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            with patch('test_wallet_service.quote_valid', side_effect=[True, True, True, False]):
                self.assertEqual(finish(execution, 'ref', digest)['status'], 'PROCESSING')
            result = poll(execution)
            self.assertEqual(result['status'], 'PROCESSING')
            self.assertEqual({leg['status'] for leg in result['legs']}, {'PROCESSING', 'FAILED'})
            self.assertEqual(sum(call.args[0] == 'send' for call in client.call_args_list), 1)

    def test_secret_exception_text_is_not_logged_or_persisted(self):
        fixture = {'quotes': [{'id': 'q0', 'expiresAt': '2099-01-01T00:00:00Z'}, {'id': 'q1', 'expiresAt': '2099-01-01T00:00:00Z'}], 'debit': '1.00', 'authServer': self.auth}
        def provider(action, **args):
            if action == 'prepare': return fixture
            if action == 'consent': return {'pending': self.pending, 'redirect': self.pending['interact']['redirect']}
            if action == 'continue': return {'access_token': {'value': 'secret'}}
            if action == 'send': raise RuntimeError('secret-token in provider body')
            raise AssertionError(action)
        with patch('test_wallet_service.bridge', side_effect=provider), patch('test_wallet_service.secrets.token_urlsafe', return_value='client-nonce'):
            execution = prepare(self.plan)['executionId']; consent(execution)
            data = '\n'.join(['client-nonce', 'provider-nonce', 'ref', self.auth]).encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            with self.assertLogs(level='WARNING') as captured:
                result = finish(execution, 'ref', digest)
            self.assertEqual(result['status'], 'PROCESSING')
            self.assertNotIn('secret-token', str(captured.output))
            with closing(sqlite3.connect(os.environ['KWIKPAY_EXECUTION_DB'])) as db:
                events = db.execute('SELECT operation,outcome,provider_status FROM payment_diagnostics WHERE execution_id=?', (execution,)).fetchall()
                self.assertEqual(sum(event[1] == 'internal_error' for event in events), 2)
                self.assertNotIn('secret-token', str(events))

    def test_expired_quote_from_bridge_is_definitely_unsent(self):
        fixture = {'quotes': [{'id': 'q0', 'expiresAt': '2099-01-01T00:00:00Z'}, {'id': 'q1', 'expiresAt': '2099-01-01T00:00:00Z'}], 'debit': '1.00', 'authServer': self.auth}
        def provider(action, **args):
            if action == 'prepare': return fixture
            if action == 'consent': return {'pending': self.pending, 'redirect': self.pending['interact']['redirect']}
            if action == 'continue': return {'access_token': {'value': 'secret'}}
            if action == 'send': raise BridgeError('quote_expired')
            raise AssertionError(action)
        with patch('test_wallet_service.bridge', side_effect=provider), patch('test_wallet_service.secrets.token_urlsafe', return_value='client-nonce'):
            execution = prepare(self.plan)['executionId']; consent(execution)
            data = '\n'.join(['client-nonce', 'provider-nonce', 'ref', self.auth]).encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            result = finish(execution, 'ref', digest)
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual({item['status'] for item in result['legs']}, {'FAILED'})

    def test_invalid_expiries_fail_closed(self):
        for value in [None, '', 'garbage', '2099-01-01T00:00:00', '2000-01-01T00:00:00Z']:
            self.assertFalse(quote_valid({'expiresAt': value}))
        self.assertTrue(quote_valid({'expiresAt': '2099-01-01T02:00:00+02:00'}))

    def test_bridge_only_accepts_sanitized_error_fields(self):
        env = {'KWIKPAY_TEST_WALLET_ENABLED': '1', 'KWIKPAY_JAVA': 'java', 'KWIKPAY_BRIDGE_CLASSPATH': 'unused'}
        with patch.dict(os.environ, env), patch('test_wallet_service.subprocess.run') as run:
            run.return_value = SimpleNamespace(returncode=1, stderr='secret-token\nKWIKPAY_BRIDGE_ERROR provider_error 503\n', stdout='')
            with self.assertRaises(BridgeError) as caught:
                bridge('send', grant={'secret': 'secret-token'})
            self.assertEqual((caught.exception.category, caught.exception.provider_status), ('provider_error', 503))
            self.assertNotIn('secret-token', str(caught.exception))
            run.return_value.stderr = 'KWIKPAY_BRIDGE_ERROR secret-token 503'
            with self.assertRaises(BridgeError) as caught:
                bridge('send')
            self.assertEqual(caught.exception.category, 'bridge_error')
            run.return_value.stderr = 'KWIKPAY_BRIDGE_ERROR quote_expired -'
            with self.assertRaises(BridgeError) as caught:
                bridge('send')
            self.assertEqual(caught.exception.category, 'bridge_error')
            run.return_value.returncode = 42
            with self.assertRaises(BridgeError) as caught:
                bridge('send')
            self.assertEqual(caught.exception.category, 'quote_expired')
            run.side_effect = subprocess.TimeoutExpired('contains-secret-token', 1)
            with self.assertRaises(BridgeError) as caught:
                bridge('send')
            self.assertEqual(caught.exception.category, 'timeout')
            self.assertNotIn('secret-token', str(caught.exception))


if __name__ == '__main__': unittest.main()
