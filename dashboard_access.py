"""Authentication and static-file handling for the isolated Test Wallet dashboard."""
import base64
import binascii
import hmac
import mimetypes
import os
import shutil
from pathlib import Path


def authorized(header):
    password = os.environ.get('KWIKPAY_DASHBOARD_PASSWORD', '')
    if not password or not header.startswith('Basic ') or len(header) > 4096:
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True)
        username, supplied = decoded.split(b':', 1)
        return hmac.compare_digest(username, b'merchant') and hmac.compare_digest(supplied, password.encode())
    except (ValueError, binascii.Error):
        return False


def deny(handler):
    handler.send_response(401)
    handler.send_header('WWW-Authenticate', 'Basic realm="KwikPay dashboard", charset="UTF-8"')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Content-Length', '0')
    handler.end_headers()


def serve(handler, path):
    root = Path(os.environ.get('KWIKPAY_DASHBOARD_DIR', '/app/dashboard')).resolve()
    relative = 'index.html' if path in ('/dashboard', '/dashboard/') else path.lstrip('/')
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return handler.reply(404, {'detail': 'Not found.'})
    body = target.read_bytes()
    handler.send_response(200)
    handler.send_header('Content-Type', mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


DOWNLOADS = {
    '/downloads/manifest.json': 'manifest.json',
    '/downloads/kwikpay-customer-0.2.0.apk': 'kwikpay-customer-0.2.0.apk',
    '/downloads/kwikpay-merchant-0.2.0.apk': 'kwikpay-merchant-0.2.0.apk',
    '/downloads/kwikpay-merchant-0.2.1.apk': 'kwikpay-merchant-0.2.1.apk',
    '/downloads/kwikpay-merchant-0.2.2.apk': 'kwikpay-merchant-0.2.2.apk',
}


def download(handler, path):
    name = DOWNLOADS.get(path)
    if not name:
        return handler.reply(404, {'detail': 'Not found.'})
    root = Path(os.environ.get('KWIKPAY_DOWNLOADS_DIR', '/app/downloads')).resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return handler.reply(404, {'detail': 'Download is unavailable.'})
    with target.open('rb') as source:
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json' if name.endswith('.json') else 'application/vnd.android.package-archive')
        if name.endswith('.apk'):
            handler.send_header('Content-Disposition', f'attachment; filename="{name}"')
        handler.send_header('Content-Length', str(target.stat().st_size))
        handler.send_header('Cache-Control', 'private, no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.end_headers()
        shutil.copyfileobj(source, handler.wfile, length=1024 * 128)
