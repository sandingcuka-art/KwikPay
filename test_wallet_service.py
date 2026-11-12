"""Local-only Test Wallet execution. No provider tokens reach the browser."""
import json
import logging
import re
from datetime import datetime, timezone
import os
import secrets
import sqlite3
import subprocess
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from execution_store import connection, create_execution, get_execution, claim_outgoing, record_outgoing, reconcile_outgoing, record_incoming
from grant_callback import verify_interaction_hash
from payment_plan import wallet_address

PAYER = "https://ilp.interledger-test.dev/wikus-customer"


class BridgeError(RuntimeError):
    def __init__(self, category, provider_status=None):
        super().__init__("Test Wallet request failed.")
        self.category = category
        self.provider_status = provider_status


def bridge(action, **kwargs):
    if os.environ.get("KWIKPAY_TEST_WALLET_ENABLED") != "1":
        raise BridgeError("disabled")
    try:
        process = subprocess.run([os.environ["KWIKPAY_JAVA"], "-cp", os.environ["KWIKPAY_BRIDGE_CLASSPATH"], "kwikpay.SplitBridge"],
            input=json.dumps({"action": action, **kwargs}), text=True, capture_output=True, timeout=50)
    except subprocess.TimeoutExpired:
        raise BridgeError("timeout") from None
    except (OSError, KeyError):
        raise BridgeError("bridge_unavailable") from None
    if process.returncode:
        match = re.search(r"(?m)^KWIKPAY_BRIDGE_ERROR (provider_error|validation_error|bridge_error|quote_expired) ([1-5][0-9]{2}|-)$", process.stderr)
        if not match or (match.group(1) == "quote_expired") != (process.returncode == 42):
            raise BridgeError("bridge_error")
        raise BridgeError(match.group(1), None if match.group(2) == "-" else int(match.group(2)))
    try:
        return json.loads(process.stdout)
    except (ValueError, TypeError):
        raise BridgeError("invalid_response") from None


def quote_valid(quote):
    try:
        expires = datetime.fromisoformat(quote["expiresAt"].replace("Z", "+00:00"))
        return expires.tzinfo is not None and expires.utcoffset() is not None and expires > datetime.now(timezone.utc)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return False


def quotes_valid(quotes):
    return isinstance(quotes, list) and len(quotes) == 2 and all(quote_valid(quote) for quote in quotes)


def stored_quotes(raw):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def diagnostic(execution_id, leg_id, operation, error):
    category = error.category if isinstance(error, BridgeError) else "internal_error"
    status = error.provider_status if isinstance(error, BridgeError) else None
    with closing(connection()) as db, db:
        # Avoid filling the database with identical poll failures every few seconds.
        if operation == "poll" and db.execute("SELECT 1 FROM payment_diagnostics WHERE id=(SELECT MAX(id) FROM payment_diagnostics WHERE execution_id=? AND leg_id=? AND operation='poll') AND outcome=? AND provider_status IS ?", (execution_id, leg_id, category, status)).fetchone():
            return
        db.execute("INSERT INTO payment_diagnostics (execution_id, leg_id, operation, outcome, provider_status) VALUES (?, ?, ?, ?, ?)", (execution_id, leg_id, operation, category, status))
    logging.warning("Test Wallet operation=%s execution=%s leg=%s outcome=%s provider_status=%s", operation, execution_id, leg_id, category, status)


def expire_unsent(db, execution_id, leg_ids):
    for leg_id in leg_ids:
        changed = db.execute("UPDATE execution_legs SET status='FAILED' WHERE execution_id=? AND leg_id=? AND status='PREPARED' AND NOT EXISTS (SELECT 1 FROM provider_legs p WHERE p.execution_id=? AND p.leg_id=?)", (execution_id, leg_id, execution_id, leg_id)).rowcount
        if changed:
            db.execute("INSERT INTO payment_diagnostics (execution_id, leg_id, operation, outcome) VALUES (?, ?, 'send', 'quote_expired')", (execution_id, leg_id))
    states = [row[0] for row in db.execute("SELECT status FROM execution_legs WHERE execution_id=?", (execution_id,))]
    if states and all(state in ("COMPLETED", "FAILED") for state in states):
        overall = "FAILED" if all(state == "FAILED" for state in states) else "PARTIAL"
        db.execute("UPDATE execution_records SET status=? WHERE id=?", (overall, execution_id))


def expire_claimed(execution_id, leg_id):
    # Only call after the bridge explicitly reports expiry before making its send request.
    with closing(connection()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute("UPDATE execution_legs SET status='FAILED' WHERE execution_id=? AND leg_id=? AND status='PROCESSING' AND EXISTS (SELECT 1 FROM provider_legs p WHERE p.execution_id=? AND p.leg_id=? AND p.outgoing_url IS NULL)", (execution_id, leg_id, execution_id, leg_id)).rowcount
        if changed:
            db.execute("INSERT INTO payment_diagnostics (execution_id, leg_id, operation, outcome) VALUES (?, ?, 'send', 'quote_expired_before_request')", (execution_id, leg_id))
            states = [row[0] for row in db.execute("SELECT status FROM execution_legs WHERE execution_id=?", (execution_id,))]
            if states and all(state in ("COMPLETED", "FAILED") for state in states):
                db.execute("UPDATE execution_records SET status=? WHERE id=?", ("FAILED" if all(state == "FAILED" for state in states) else "PARTIAL", execution_id))


def test_payer(address):
    address = wallet_address(address)
    uri = urlsplit(address)
    if uri.hostname != "ilp.interledger-test.dev" or uri.path in ("", "/"):
        raise ValueError("Use an Interledger Test Wallet address.")
    return address


def prepare(plan):
    if not isinstance(plan, dict):
        raise ValueError("A payment plan is required.")
    payer = test_payer(plan.get("payerWalletAddress"))
    legs = plan.get("legs")
    if not isinstance(legs, list) or len(legs) != 2 or any(not isinstance(leg, dict) for leg in legs):
        raise ValueError("Exactly two payment legs are required.")
    for leg in legs:
        address = leg.get("walletAddress")
        amount = leg.get("amount")
        if not isinstance(address, str) or urlsplit(address).hostname != "ilp.interledger-test.dev":
            raise ValueError("Use Test Wallet destination addresses.")
        if not isinstance(amount, dict) or not isinstance(amount.get("value"), str) or not re.fullmatch(r"[0-9]{1,6}", amount["value"]) or int(amount["value"]) <= 0:
            raise ValueError("Each payment leg must have a positive amount.")
    if sum(int(leg["amount"]["value"]) for leg in legs) > 100000:
        raise ValueError("The Test Wallet sale is limited to R1000.00.")
    execution = create_execution(plan)
    execution_id = execution["executionId"]
    with closing(connection()) as db, db:
        if not db.execute("INSERT OR IGNORE INTO test_wallet_sessions (execution_id, state) VALUES (?, 'PREPARING')", (execution_id,)).rowcount:
            raise ValueError("This payment plan has already been prepared or attempted.")
    try:
        prepared = bridge("prepare", payerWalletAddress=payer, legs=[{"walletAddress": leg["walletAddress"], "amountMinor": leg["amount"]["value"]} for leg in legs])
        quotes = prepared["quotes"]
        amount = Decimal(prepared["debit"])
        minor = amount * 100
        if not quotes_valid(quotes):
            raise BridgeError("quote_expired")
        if not amount.is_finite() or amount <= 0 or minor != minor.to_integral_value() or minor > 100000:
            raise RuntimeError("Invalid provider quote.")
        with closing(connection()) as db, db:
            db.execute("UPDATE test_wallet_sessions SET state='QUOTED', quotes_json=?, debit_minor=?, auth_server=? WHERE execution_id=? AND state='PREPARING'",
                       (json.dumps(quotes), str(int(minor)), prepared["authServer"], execution_id))
            db.execute("UPDATE execution_legs SET status='PREPARED' WHERE execution_id=?", (execution_id,))
        return {"executionId": execution_id, "debitMinor": str(int(minor))}
    except Exception as exc:
        diagnostic(execution_id, None, "prepare", exc)
        with closing(connection()) as db, db:
            db.execute("UPDATE test_wallet_sessions SET state='ERROR' WHERE execution_id=?", (execution_id,))
        raise


def consent(execution_id):
    nonce = secrets.token_urlsafe(32)
    expired = False
    with closing(connection()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT debit_minor, state, pending_json, quotes_json FROM test_wallet_sessions WHERE execution_id=?", (execution_id,)).fetchone()
        if not row or row[1] not in ("QUOTED", "PENDING"):
            raise ValueError("Payment is not ready for authorization.")
        if not quotes_valid(stored_quotes(row[3])):
            expired = True
            ids = [leg[0] for leg in db.execute("SELECT leg_id FROM execution_legs WHERE execution_id=?", (execution_id,))]
            expire_unsent(db, execution_id, ids)
            db.execute("UPDATE test_wallet_sessions SET state='EXPIRED' WHERE execution_id=?", (execution_id,))
        elif row[1] == "PENDING":
            return {"interactUrl": json.loads(row[2])["interact"]["redirect"]}
        else:
            db.execute("UPDATE test_wallet_sessions SET state='REQUESTING', nonce=? WHERE execution_id=?", (nonce, execution_id))
    if expired:
        raise ValueError("The quote expired. Start a new payment to obtain a fresh quote.")
    try:
        pending = bridge("consent", payerWalletAddress=test_payer(get_execution(execution_id)["plan"]["payerWalletAddress"]), debitMinor=row[0], nonce=nonce, executionId=execution_id)
        with closing(connection()) as db, db:
            db.execute("UPDATE test_wallet_sessions SET state='PENDING', pending_json=? WHERE execution_id=? AND state='REQUESTING'", (json.dumps(pending["pending"]), execution_id))
            db.execute("UPDATE execution_records SET status='AWAITING_CONSENT' WHERE id=?", (execution_id,))
        return {"interactUrl": pending["redirect"]}
    except Exception as exc:
        diagnostic(execution_id, None, "consent", exc)
        with closing(connection()) as db, db:
            db.execute("UPDATE test_wallet_sessions SET state='ERROR' WHERE execution_id=?", (execution_id,))
        raise


def finish(execution_id, interact_ref, received_hash, on_verified=None):
    expired = False
    with closing(connection()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT nonce, pending_json, auth_server, quotes_json FROM test_wallet_sessions WHERE execution_id=? AND state='PENDING'", (execution_id,)).fetchone()
        if not row:
            raise ValueError("No pending authorization.")
        pending = json.loads(row[1])
        if not verify_interaction_hash(row[0], pending["interact"]["finish"], interact_ref, row[2], received_hash):
            raise ValueError("Wallet callback could not be verified.")
        if not quotes_valid(stored_quotes(row[3])):
            expired = True
            ids = [leg[0] for leg in db.execute("SELECT leg_id FROM execution_legs WHERE execution_id=?", (execution_id,))]
            expire_unsent(db, execution_id, ids)
            db.execute("UPDATE test_wallet_sessions SET state='EXPIRED' WHERE execution_id=?", (execution_id,))
        else:
            db.execute("UPDATE test_wallet_sessions SET state='CONTINUING' WHERE execution_id=?", (execution_id,))
    if expired:
        return get_execution(execution_id)
    if on_verified is not None:
        on_verified()
    try:
        grant = bridge("continue", pending=pending, interactRef=interact_ref)
    except Exception as exc:
        diagnostic(execution_id, None, "continue", exc)
        raise
    with closing(connection()) as db, db:
        db.execute("UPDATE test_wallet_sessions SET state='APPROVED', grant_json=?, pending_json=NULL WHERE execution_id=? AND state='CONTINUING'", (json.dumps(grant), execution_id))
        db.execute("UPDATE execution_records SET status='PROCESSING' WHERE id=?", (execution_id,))
    execution = get_execution(execution_id)
    for leg, quote in zip(execution["plan"]["legs"], json.loads(row[3])):
        if not quote_valid(quote):
            with closing(connection()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                expire_unsent(db, execution_id, [leg["id"]])
            continue
        if not claim_outgoing(execution_id, leg["id"]):
            continue
        try:
            outgoing = bridge("send", payerWalletAddress=test_payer(execution["plan"]["payerWalletAddress"]), grant=grant, quote=quote)
            url = outgoing["id"]
            record_outgoing(execution_id, leg["id"], url)
        except Exception as exc:
            diagnostic(execution_id, leg["id"], "send", exc)
            if isinstance(exc, BridgeError) and exc.category == "quote_expired":
                expire_claimed(execution_id, leg["id"])
            # shortcut: an unknown provider outcome requires manual reconciliation; never retry automatically.
            continue
    return get_execution(execution_id)


def poll(execution_id):
    with closing(connection()) as db:
        session = db.execute("SELECT grant_json FROM test_wallet_sessions WHERE execution_id=? AND state='APPROVED'", (execution_id,)).fetchone()
        rows = db.execute("SELECT p.leg_id, p.outgoing_url FROM provider_legs p JOIN execution_legs l ON l.execution_id=p.execution_id AND l.leg_id=p.leg_id WHERE p.execution_id=? AND p.outgoing_url IS NOT NULL AND l.status='PROCESSING'", (execution_id,)).fetchall()
        session_row = db.execute("SELECT quotes_json FROM test_wallet_sessions WHERE execution_id=? AND state='APPROVED'", (execution_id,)).fetchone()
    if session:
        grant = json.loads(session[0])
        quotes = json.loads(session_row[0])
        plan = get_execution(execution_id)["plan"]
        leg_indexes = {leg["id"]: index for index, leg in enumerate(plan["legs"])}
        for leg_id, url in rows:
            index = leg_indexes.get(leg_id)
            if index is None or index >= len(quotes):
                continue
            try:
                evidence = bridge("poll", grant=grant, outgoingUrl=url, destination=plan["legs"][index]["walletAddress"], quote=quotes[index])
                outgoing, incoming = evidence["outgoing"], evidence["incoming"]
                if outgoing.get("id") != url:
                    raise BridgeError("validation_error")
                received = incoming.get("receivedAmount")
                failed = outgoing.get("failed")
                if incoming.get("id") is not None:
                    record_incoming(execution_id, leg_id, incoming)
                if received is not None and isinstance(failed, bool) and (incoming.get("completed") is True or failed):
                    reconcile_outgoing(execution_id, leg_id, url, received, failed, outgoing.get("sentAmount"))
            except (ValueError, RuntimeError, KeyError, subprocess.SubprocessError, OSError) as exc:
                diagnostic(execution_id, leg_id, "poll", exc)
                # An expired outgoing grant does not prevent reading the matched incoming resource.
                try:
                    incoming = bridge("incoming", destination=plan["legs"][index]["walletAddress"], incomingUrl=quotes[index]["receiver"])
                    record_incoming(execution_id, leg_id, incoming)
                except (ValueError, RuntimeError, KeyError, IndexError, subprocess.SubprocessError, OSError) as incoming_exc:
                    diagnostic(execution_id, leg_id, "incoming", incoming_exc)
                continue
    return get_execution(execution_id)
