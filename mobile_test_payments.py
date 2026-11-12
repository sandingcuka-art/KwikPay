"""Isolated Test Wallet checkout for the two-phone demo."""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from execution_store import connection, get_execution
from payment_plan import create_payment_plan, wallet_address
import test_wallet_service
import dashboard_access

PAYER = test_wallet_service.PAYER
DESTINATIONS = [
    'https://ilp.interledger-test.dev/kwikpay-merch-2',
    'https://ilp.interledger-test.dev/kwikpay-merch-3',
]
DEFAULT_POTS = [
    {'label': 'Business income', 'walletAddress': DESTINATIONS[0], 'percentage': 80},
    {'label': 'Stock reserve', 'walletAddress': DESTINATIONS[1], 'percentage': 20},
]
TOKEN = r'[A-Za-z0-9_-]{32}'
lock = threading.Lock()
last_poll = {}


def initialise():
    with closing(connection()) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS mobile_requests (token_hash TEXT PRIMARY KEY, created INTEGER NOT NULL, expires INTEGER NOT NULL, state TEXT NOT NULL, execution_id TEXT, debit TEXT, redirect TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS mobile_schema_migrations (version INTEGER PRIMARY KEY)')
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM mobile_schema_migrations WHERE version=1').fetchone():
            migration = (Path(__file__).parent / 'migrations' / 'mobile_001_dashboard.sql').read_text()
            for statement in migration.split(';'):
                if statement.strip():
                    db.execute(statement)
            db.execute('INSERT INTO mobile_schema_migrations(version) VALUES (1)')
        if not db.execute('SELECT 1 FROM mobile_schema_migrations WHERE version=2').fetchone():
            migration = (Path(__file__).parent / 'migrations' / 'mobile_002_manual_verification.sql').read_text()
            for statement in migration.split(';'):
                if statement.strip():
                    db.execute(statement)
            db.execute('INSERT INTO mobile_schema_migrations(version) VALUES (2)')
        db.execute('INSERT OR IGNORE INTO mobile_config(id,version,pots_json) VALUES(1,1,?)', (json.dumps(DEFAULT_POTS),))


def read_config(db=None):
    if db is None:
        with closing(connection()) as db:
            return read_config(db)
    row = db.execute('SELECT version,pots_json FROM mobile_config WHERE id=1').fetchone()
    if not row:
        raise RuntimeError('Mobile configuration is unavailable.')
    return {'version': row[0], 'pots': json.loads(row[1])}


def save_config(data):
    if not isinstance(data, dict) or set(data) != {'version', 'pots'} or type(data['version']) is not int:
        raise ValueError('Invalid configuration.')
    pots = data['pots']
    if not isinstance(pots, list) or len(pots) != 2:
        raise ValueError('Exactly two pots are required.')
    cleaned = []
    for pot in pots:
        if not isinstance(pot, dict) or set(pot) != {'label', 'walletAddress', 'percentage'}:
            raise ValueError('Each pot needs a name, wallet address and percentage.')
        label, address, percent = pot['label'], pot['walletAddress'], pot['percentage']
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 60 or re.search(r'[\x00-\x1f\x7f]', label):
            raise ValueError('Pot names must contain 1–60 characters.')
        wallet_address(address)
        parsed = urlsplit(address)
        if parsed.hostname != 'ilp.interledger-test.dev' or parsed.path in ('', '/'):
            raise ValueError('Use a Test Wallet address for each pot.')
        if type(percent) is not int or not 1 <= percent <= 99:
            raise ValueError('Each pot percentage must be a whole number from 1 to 99.')
        cleaned.append({'label': label.strip(), 'walletAddress': address, 'percentage': percent})
    if sum(p['percentage'] for p in cleaned) != 100:
        raise ValueError('Pot percentages must total 100%.')
    with closing(connection()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('UPDATE mobile_config SET version=version+1,pots_json=? WHERE id=1 AND version=?', (json.dumps(cleaned), data['version'])).rowcount:
            raise ValueError('Settings changed elsewhere. Refresh before saving.')
        return read_config(db)


def make_plan(config, amount="300"):
    return create_payment_plan({'shopId': 'mobile-test', 'saleId': secrets.token_hex(16), 'payerWalletAddress': PAYER,
        'amount': {'value': amount, 'assetCode': 'ZAR', 'assetScale': 2},
        'rule': {'version': config['version'], 'destinations': config['pots']}})


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def request_row(token):
    with closing(connection()) as db:
        return db.execute('SELECT expires,state,execution_id,debit,redirect,snapshot_json FROM mobile_requests WHERE token_hash=?', (token_hash(token),)).fetchone()


def create_request(amount='300'):
    if not isinstance(amount, str) or not re.fullmatch(r'[0-9]{1,4}', amount) or not 2 <= int(amount) <= 1000:
        raise ValueError('Enter a sale amount from R0.02 to R10.00.')
    amount = str(int(amount))
    token = secrets.token_urlsafe(24)
    with closing(connection()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("DELETE FROM mobile_requests WHERE state='AWAITING_CUSTOMER' AND expires<=?", (int(time.time()),))
        if db.execute("SELECT count(*) FROM mobile_requests WHERE state IN ('AWAITING_CUSTOMER','PREPARING','AWAITING_CONSENT') AND expires>?", (int(time.time()),)).fetchone()[0] >= 100:
            raise ValueError('Test checkout capacity reached.')
        now = int(time.time())
        plan = make_plan(read_config(db), amount)
        if any(int(leg['amount']['value']) < 1 for leg in plan['legs']):
            raise ValueError('Increase the sale amount so each pot receives at least R0.01.')
        db.execute('INSERT INTO mobile_requests (token_hash,created,expires,state,snapshot_json) VALUES (?,?,?,?,?)', (token_hash(token), now, now + 300, 'AWAITING_CUSTOMER', json.dumps(plan)))
    return token


def start_request(token, wallet):
    wallet = test_wallet_service.test_payer(wallet)
    with closing(connection()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        changed = db.execute("UPDATE mobile_requests SET state='PREPARING' WHERE token_hash=? AND state='AWAITING_CUSTOMER' AND expires>?", (token_hash(token), int(time.time()))).rowcount
    if not changed:
        raise ValueError('Request expired or already started. Check its status before starting another.')
    try:
        row = request_row(token)
        # Older unprepared requests used the original fixed split; preserve that contract.
        plan = json.loads(row[5]) if row[5] else make_plan({'version': 1, 'pots': DEFAULT_POTS})
        plan['payerWalletAddress'] = wallet
        prepared = test_wallet_service.prepare(plan)
        execution = prepared['executionId']
        with closing(connection()) as db, db:
            db.execute('UPDATE mobile_requests SET execution_id=?, debit=? WHERE token_hash=?', (execution, prepared['debitMinor'], token_hash(token)))
        if int(prepared['debitMinor']) > int(plan['amount']['value']):
            raise ValueError('The quoted debit exceeds the sale amount. No payment was sent.')
        consent = test_wallet_service.consent(execution)
        with closing(connection()) as db, db:
            db.execute("UPDATE mobile_requests SET state='AWAITING_CONSENT',redirect=? WHERE token_hash=?", (consent['interactUrl'], token_hash(token)))
    except Exception:
        with closing(connection()) as db, db:
            db.execute("UPDATE mobile_requests SET state='PREPARATION_FAILED' WHERE token_hash=?", (token_hash(token),))
        raise


def poll_in_background(execution_id):
    try:
        test_wallet_service.poll(execution_id)
    finally:
        lock.release()


def schedule_poll(execution_id):
    if not lock.acquire(blocking=False):
        return
    try:
        if time.monotonic() - last_poll.get(execution_id, 0) >= 15:
            last_poll[execution_id] = time.monotonic()
            threading.Thread(target=poll_in_background, args=(execution_id,), daemon=True).start()
        else:
            lock.release()
    except Exception:
        lock.release()
        raise


def needs_poll(execution):
    """Stop provider reads once both amounts and incoming completion are recorded."""
    if not execution:
        return False
    planned = {leg['id']: leg for leg in execution['plan']['legs']}
    for leg in execution['legs']:
        if leg['status'] != 'PROCESSING':
            continue
        expected = planned.get(leg['legId'], {}).get('amount', {}).get('value')
        incoming = leg.get('incomingPayment') or {}
        observed = leg.get('openPayments') or {}
        sent = observed.get('sent')
        if not (incoming.get('completed') is True and incoming.get('received') == expected and observed.get('received') == expected and isinstance(sent, str) and sent.isascii() and sent.isdigit() and int(sent) > 0):
            return True
    return False


def public_request(token):
    row = request_row(token)
    if not row:
        return None
    expires, state, execution_id, debit, redirect, snapshot = row
    if state in ('AWAITING_CUSTOMER', 'AWAITING_CONSENT') and expires <= time.time():
        state = 'EXPIRED'
    execution = get_execution(execution_id) if execution_id else None
    plan = json.loads(snapshot) if snapshot else execution['plan'] if execution else make_plan({'version': 1, 'pots': DEFAULT_POTS})
    result = {'merchant': 'Demo shop', 'amount': plan['amount']['value'], 'currency': 'ZAR', 'status': state,
        'ruleVersion': plan['ruleVersion'], 'expiresAt': expires,
        'pots': [{'label': leg['label'], 'amount': leg['amount']['value'], 'percentage': leg['percentage'], 'walletAddress': leg['walletAddress']} for leg in plan['legs']]}
    if state == 'AWAITING_CONSENT':
        result.update({'debitMinor': debit, 'interactUrl': redirect})
    if execution_id:
        result['executionId'] = execution_id
        if state == 'PROCESSING' and needs_poll(execution):
            schedule_poll(execution_id)
        if execution:
            result['paymentStatus'] = execution['status']
            result['legs'] = [{'label': leg['label'], 'amount': leg['amount']['value'],
                **next(({'status': v['status'], 'walletStatus': v.get('walletStatus'), 'openPayments': v.get('openPayments')} for v in execution['legs'] if v['legId'] == leg['id']), {})}
                for leg in execution['plan']['legs']]
    return result


def mobile_records():
    with closing(connection()) as db:
        rows = db.execute('SELECT created,state,execution_id,expires FROM mobile_requests WHERE execution_id IS NOT NULL ORDER BY created DESC,rowid DESC').fetchall()
    records = []
    for created, state, execution_id, expires in rows:
        if state == 'AWAITING_CONSENT' and expires <= time.time():
            state = 'EXPIRED'
        execution = get_execution(execution_id)
        if state == 'PROCESSING' and needs_poll(execution):
            schedule_poll(execution_id)
        if execution:
            records.append((created, state, execution))
    return records


def dashboard_overview():
    records = mobile_records()
    with closing(connection()) as db:
        events = db.execute('SELECT e.execution_id,e.leg_id,e.verified,e.recorded_at FROM manual_verification_events e WHERE e.id=(SELECT MAX(last.id) FROM manual_verification_events last WHERE last.execution_id=e.execution_id AND last.leg_id=e.leg_id)').fetchall()
    confirmations = {(execution, leg): timestamp for execution, leg, verified, timestamp in events if verified}
    sent = received = 0
    pots = {}
    history = []
    for created, state, execution in records:
        plan = execution['plan']
        by_id = {leg['legId']: leg for leg in execution['legs']}
        legs = []
        for planned in plan['legs']:
            actual = by_id.get(planned['id'], {})
            observed = actual.get('openPayments')
            if observed:
                sent_value, received_value = int(observed['sent']), int(observed['received'])
                sent += sent_value
                received += received_value
                pots[planned['label']] = pots.get(planned['label'], 0) + received_value
            legs.append({'legId': planned['id'], 'label': planned['label'], 'planned': planned['amount']['value'], 'walletAddress': planned['walletAddress'],
                'status': actual.get('status', 'PENDING'), 'walletStatus': actual.get('walletStatus', 'UNVERIFIED'),
                'openPayments': observed, 'incomingPayment': actual.get('incomingPayment'), 'manuallyVerifiedAt': confirmations.get((execution['executionId'], planned['id']))})
        history.append({'executionId': execution['executionId'], 'createdAt': datetime.fromtimestamp(created, timezone.utc).isoformat(),
            'status': execution['status'], 'requestStatus': state, 'amount': plan['amount']['value'], 'legs': legs})
    return {'history': history[:100], 'summary': {'recordCount': len(records), 'observedSent': str(sent),
        'observedReceived': str(received), 'observedByPot': [{'label': label, 'value': str(value)} for label, value in sorted(pots.items())]}}


def record_manual_verification(execution_id, data):
    if not isinstance(data, dict) or set(data) != {'legId', 'verified'} or not isinstance(data['legId'], str) or type(data['verified']) is not bool:
        raise ValueError('Invalid manual confirmation.')
    with closing(connection()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT r.plan_json,l.status,e.sent_value,e.received_value FROM execution_records r JOIN mobile_requests m ON m.execution_id=r.id JOIN execution_legs l ON l.execution_id=r.id LEFT JOIN open_payments_evidence e ON e.execution_id=l.execution_id AND e.leg_id=l.leg_id WHERE r.id=? AND l.leg_id=?', (execution_id, data['legId'])).fetchone()
        if not row:
            raise ValueError('Payment leg not found.')
        plan = json.loads(row[0])
        leg = next((item for item in plan['legs'] if item['id'] == data['legId']), None)
        if not leg:
            raise ValueError('Payment leg not found.')
        if data['verified'] and (row[1] == 'FAILED' or not row[2] or not row[3] or int(row[2]) <= 0 or int(row[3]) != int(leg['amount']['value'])):
            raise ValueError('Wait for the expected Open Payments amounts before confirming this leg.')
        previous = db.execute('SELECT verified FROM manual_verification_events WHERE execution_id=? AND leg_id=? ORDER BY id DESC LIMIT 1', (execution_id, data['legId'])).fetchone()
        if bool(previous and previous[0]) != data['verified']:
            db.execute('INSERT INTO manual_verification_events(execution_id,leg_id,verified) VALUES(?,?,?)', (execution_id, data['legId'], int(data['verified'])))
    return {'recorded': True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def wallet_return(self, verified):
        if verified:
            title = 'Check your payment'
            message = 'Return to KwikPay to check the status of both payment legs. Wallet settlement may still be pending.'
        else:
            title = 'Payment status needs checking'
            message = 'We could not confirm the wallet response. Return to KwikPay and check the merchant status before attempting another payment.'
        body = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KwikPay</title><style>body{{margin:0;background:#f1f6fb;color:#10233b;font:16px system-ui,sans-serif}}main{{max-width:30rem;margin:12vh auto;padding:2rem}}h1{{font-size:1.8rem}}p{{line-height:1.5}}a{{display:block;padding:1rem;border-radius:.8rem;background:#1769ff;color:white;text-align:center;text-decoration:none;font-weight:700;margin:2rem 0}}small{{color:#53657b}}</style></head><body><main><strong>KWIKPAY · TEST WALLET</strong><h1>{title}</h1><p>{message}</p><a href="kwikpay-customer://payment-return">Return to KwikPay</a><small>If the app does not open, return to it using your phone's app switcher.</small></main></body></html>'''.encode()
        self.send_response(200 if verified else 400)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'")
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path)
        if path.path == '/health':
            return self.reply(200, {'status': 'ok', 'mode': 'test-wallet-r3'})
        if path.path.startswith('/downloads/'):
            if not dashboard_access.authorized(self.headers.get('Authorization', '')):
                return dashboard_access.deny(self)
            if path.query:
                return self.reply(404, {'detail': 'Not found.'})
            return dashboard_access.download(self, path.path)
        if path.path in ('/dashboard', '/dashboard/') or path.path.startswith('/assets/'):
            if not dashboard_access.authorized(self.headers.get('Authorization', '')):
                return dashboard_access.deny(self)
            return dashboard_access.serve(self, path.path)
        if path.path in ('/api/dashboard/config', '/api/dashboard/sales-overview'):
            if not dashboard_access.authorized(self.headers.get('Authorization', '')):
                return dashboard_access.deny(self)
            return self.reply(200, read_config() if path.path.endswith('/config') else dashboard_overview())
        if path.path == '/api/mobile-test/config' and not path.query:
            key = os.environ.get('KWIKPAY_MERCHANT_KEY', '')
            supplied = self.headers.get('X-KwikPay-Merchant-Key', '')
            try:
                allowed = bool(key) and secrets.compare_digest(supplied.encode('ascii'), key.encode('ascii'))
            except UnicodeEncodeError:
                allowed = False
            if not allowed:
                return self.reply(403, {'detail': 'Merchant access required.'})
            return self.reply(200, read_config())
        if path.path == '/payment-return' and path.query == 'status=processing':
            return self.wallet_return(True)
        if path.path == '/api/mobile-test/history' and not path.query:
            key = os.environ.get('KWIKPAY_MERCHANT_KEY', '')
            if not key or not secrets.compare_digest(self.headers.get('X-KwikPay-Merchant-Key', ''), key):
                return self.reply(403, {'detail': 'Merchant access required.'})
            items = []
            for created, state, execution in mobile_records()[:100]:
                plan = execution['plan']
                items.append({'id': execution['executionId'], 'source': 'test_wallet', 'amount': plan['amount']['value'],
                    'business': plan['legs'][0]['amount']['value'], 'stock': plan['legs'][1]['amount']['value'],
                    'potLabels': [leg['label'] for leg in plan['legs']], 'status': execution['status'], 'requestStatus': state,
                    'confirmedAt': datetime.fromtimestamp(created, timezone.utc).isoformat()})
            return self.reply(200, {'items': items})
        callback = re.fullmatch(r'/api/test-callback/(exec_[0-9a-f]{32})', path.path)
        if callback:
            params = parse_qs(path.query, keep_blank_values=True)
            if set(params) != {'interact_ref', 'hash'} or any(len(v) != 1 for v in params.values()):
                return self.wallet_return(False)
            with closing(connection()) as db:
                row = db.execute("SELECT token_hash FROM mobile_requests WHERE execution_id=? AND state='AWAITING_CONSENT' AND expires>?", (callback[1], int(time.time()))).fetchone()
            if not row:
                return self.wallet_return(False)
            def mark_processing():
                with closing(connection()) as db, db:
                    db.execute("UPDATE mobile_requests SET state='PROCESSING',redirect=NULL WHERE token_hash=?", (row[0],))
            try:
                test_wallet_service.finish(callback[1], params['interact_ref'][0], params['hash'][0], on_verified=mark_processing)
            except Exception:
                with closing(connection()) as db, db:
                    session = db.execute('SELECT state FROM test_wallet_sessions WHERE execution_id=?', (callback[1],)).fetchone()
                    if session and session[0] != 'PENDING':
                        db.execute("UPDATE mobile_requests SET state='PROCESSING',redirect=NULL WHERE token_hash=?", (row[0],))
                return self.wallet_return(False)
            mark_processing()
            self.send_response(303)
            self.send_header('Location', '/payment-return?status=processing')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        match = re.fullmatch('/api/mobile-test/requests/(' + TOKEN + ')', path.path)
        if match and not path.query:
            result = public_request(match[1])
            return self.reply(200 if result else 404, result or {'detail': 'Request not found.'})
        return self.reply(404, {'detail': 'Not found.'})

    def do_POST(self):
        match = re.fullmatch('/api/mobile-test/requests/(' + TOKEN + ')/prepare', self.path)
        verification = re.fullmatch(r'/api/dashboard/sales/(exec_[0-9a-f]{32})/manual-verification', self.path)
        config_write = self.path == '/api/dashboard/config'
        dashboard_sale = self.path == '/api/dashboard/requests'
        if self.path != '/api/mobile-test/requests' and not match and not config_write and not verification and not dashboard_sale:
            return self.reply(404, {'detail': 'Not found.'})
        if config_write or verification or dashboard_sale:
            if not dashboard_access.authorized(self.headers.get('Authorization', '')):
                return dashboard_access.deny(self)
            if self.headers.get('Origin') != os.environ.get('KWIKPAY_CALLBACK_ORIGIN'):
                return self.reply(403, {'detail': 'Invalid request origin.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if self.headers.get_content_type() != 'application/json' or not 0 < length <= 4096:
                raise ValueError('Invalid request.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Invalid request.')
            if config_write:
                try:
                    return self.reply(200, save_config(data))
                except ValueError as error:
                    return self.reply(400, {'detail': str(error)})
            if verification:
                try:
                    return self.reply(200, record_manual_verification(verification[1], data))
                except ValueError as error:
                    return self.reply(400, {'detail': str(error)})
            if match:
                if set(data) != {'walletAddress'}:
                    raise ValueError('Customer wallet is required.')
                start_request(match[1], data['walletAddress'])
                return self.reply(200, public_request(match[1]))
            if not dashboard_sale:
                key = os.environ.get('KWIKPAY_MERCHANT_KEY', '')
                if not key or not secrets.compare_digest(self.headers.get('X-KwikPay-Merchant-Key', ''), key):
                    return self.reply(403, {'detail': 'Merchant access required.'})
            if set(data) != {'amount'}:
                raise ValueError('Invalid sale amount.')
            try:
                token = create_request(data['amount'])
            except ValueError as error:
                if dashboard_sale:
                    return self.reply(400, {'detail': str(error)})
                raise
            return self.reply(201, {'checkoutUrl': os.environ['KWIKPAY_CALLBACK_ORIGIN'] + '/api/mobile-test/requests/' + token, **public_request(token)})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return self.reply(400, {'detail': 'Could not prepare this request. Check its status before starting another.'})
        except Exception:
            return self.reply(503, {'detail': 'Test Wallet request failed. Check its status before starting another.'})


if __name__ == '__main__':
    if os.environ.get('KWIKPAY_TEST_WALLET_ENABLED') != '1' or not os.environ.get('KWIKPAY_EXECUTION_DB') or not os.environ.get('KWIKPAY_CALLBACK_ORIGIN') or not os.environ.get('KWIKPAY_MERCHANT_KEY'):
        raise SystemExit('An isolated Test Wallet database and HTTPS callback must be configured.')
    origin = urlsplit(os.environ['KWIKPAY_CALLBACK_ORIGIN'])
    if origin.scheme != 'https' or not origin.hostname or not origin.hostname.endswith('.up.railway.app') or origin.port is not None or origin.username or origin.password or origin.path or origin.query or origin.fragment:
        raise SystemExit('Invalid Test Wallet callback origin.')
    if os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') != '/data' or os.environ['KWIKPAY_EXECUTION_DB'] != '/data/payments.sqlite3':
        raise SystemExit('A dedicated persistent /data volume is required.')
    initialise()
    with ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), Handler) as server:
        server.serve_forever()
