"""Checkout request demo. This service never creates payments."""

import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from payment_plan import wallet_address

PORT = 8060
PUBLIC_ORIGIN = os.environ.get('PUBLIC_ORIGIN', f'http://127.0.0.1:{PORT}').rstrip('/')
TTL_SECONDS = 300
requests = {}
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Request URLs contain bearer-like demo tokens.
        return

    def reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if self.headers.get_content_type() != 'application/json' or not 0 < n <= 4096:
                raise ValueError
            value = json.loads(self.rfile.read(n))
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, UnicodeDecodeError):
            raise ValueError('Invalid request.') from None

    def do_GET(self):
        if self.path == '/health':
            return self.reply(200, {'status': 'ok', 'mode': 'demo-no-payments'})
        match = re.fullmatch(r'/api/mobile-demo/requests/([A-Za-z0-9_-]{32})', self.path)
        if not match:
            return self.reply(404, {'detail': 'Request not found.'})
        with lock:
            item = requests.get(match[1])
            if not item:
                return self.reply(404, {'detail': 'Request not found.'})
            if time.time() >= item['expiresAtUnix']:
                return self.reply(410, {'detail': 'This request has expired.'})
            data = {k: v for k, v in item.items() if k not in ('expiresAtUnix', 'customerWallet')}
        self.reply(200, data)

    def do_POST(self):
        match = re.fullmatch(r'/api/mobile-demo/requests/([A-Za-z0-9_-]{32})/(review|confirm)', self.path)
        if self.path != '/api/mobile-demo/requests' and not match:
            return self.reply(404, {'detail': 'Request not found.'})
        try:
            data = self.body()
            if match:
                if set(data) != {'walletAddress'}:
                    raise ValueError('A customer wallet address is required.')
                wallet = wallet_address(data['walletAddress'])
                with lock:
                    item = requests.get(match[1])
                    if not item:
                        return self.reply(404, {'detail': 'Request not found.'})
                    if time.time() >= item['expiresAtUnix']:
                        return self.reply(410, {'detail': 'This request has expired.'})
                    if item.get('customerWallet') not in (None, wallet):
                        return self.reply(409, {'detail': 'This request is already being reviewed.'})
                    if match[2] == 'confirm':
                        if item.get('customerWallet') != wallet:
                            return self.reply(409, {'detail': 'Share your wallet before confirming.'})
                        if item['status'] != 'DEMO_CONFIRMED':
                            item['status'] = 'DEMO_CONFIRMED'
                            item['confirmedAt'] = datetime.now(timezone.utc).isoformat()
                    elif item['status'] != 'DEMO_CONFIRMED':
                        item['customerWallet'] = wallet
                        item['status'] = 'CUSTOMER_REVIEWING'
                    status = item['status']
                return self.reply(200, {'status': status})
            if set(data) != {'amount'} or not isinstance(data['amount'], str) or not re.fullmatch(r'[0-9]{1,6}', data['amount']):
                raise ValueError('Amount must be whole cents.')
            amount = int(data['amount'])
            if not 2 <= amount <= 100000:
                raise ValueError('Enter an amount from R0.02 to R1000.00.')
            first = amount * 80 // 100
            now = time.time()
            token = secrets.token_urlsafe(24)
            item = {'merchant': 'Demo shop', 'amount': str(amount), 'currency': 'ZAR',
                    'status': 'AWAITING_CUSTOMER', 'expiresAtUnix': now + TTL_SECONDS,
                    'expiresAt': datetime.fromtimestamp(now + TTL_SECONDS, timezone.utc).isoformat(),
                    'pots': [{'label': 'Business income', 'amount': str(first), 'percentage': 80},
                             {'label': 'Stock reserve', 'amount': str(amount - first), 'percentage': 20}]}
            with lock:
                for expired in [key for key, value in requests.items() if now >= value['expiresAtUnix']]:
                    del requests[expired]
                # shortcut: in-memory demo storage is capped; use durable storage for real sales.
                if len(requests) >= 1000:
                    return self.reply(503, {'detail': 'Demo capacity reached. Try again later.'})
                requests[token] = item
            self.reply(201, {'checkoutUrl': f'{PUBLIC_ORIGIN}/api/mobile-demo/requests/{token}',
                             **{k: v for k, v in item.items() if k != 'expiresAtUnix'}})
        except ValueError as exc:
            self.reply(400, {'detail': str(exc)})


if __name__ == '__main__':
    host = '0.0.0.0' if os.environ.get('PORT') else '127.0.0.1'
    port = int(os.environ.get('PORT', PORT))
    with ThreadingHTTPServer((host, port), Handler) as server:
        print(f'Checkout demo (no payments) listening on {host}:{port}', flush=True)
        server.serve_forever()
