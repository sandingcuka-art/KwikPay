"""Run the Test Wallet service with the provider key in a private temporary file."""
import os
import runpy
import tempfile

key = os.environ.pop('TEST_WALLET_PRIVATE_KEY', None)
if not key:
    raise SystemExit('Missing Test Wallet private key.')
fd, path = tempfile.mkstemp(prefix='kwikpay-test-wallet-')
try:
    with os.fdopen(fd, 'w') as handle:
        handle.write(key)
    os.environ['TEST_WALLET_PRIVATE_KEY_FILE'] = path
    runpy.run_module('mobile_test_payments', run_name='__main__')
finally:
    os.unlink(path)
