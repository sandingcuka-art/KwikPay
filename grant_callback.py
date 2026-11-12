"""Verify the Open Payments interaction hash before continuing a grant."""

import base64
import hashlib
import hmac


def verify_interaction_hash(client_nonce, server_nonce, interact_ref, grant_url, received_hash):
    values = (client_nonce, server_nonce, interact_ref, grant_url, received_hash)
    if any(not isinstance(value, str) or not value or len(value) > 2048 or not value.isascii() or "\n" in value or "\r" in value for value in values):
        return False
    data = "\n".join(values[:4]).encode("ascii")
    expected = hashlib.sha256(data).digest()
    try:
        received = received_hash.encode("ascii")
        # GNAP uses unpadded base64url; some provider callbacks use standard base64.
        decoded = base64.b64decode(received + b"=" * (-len(received) % 4), altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error):
        return False
    return hmac.compare_digest(expected, decoded)
