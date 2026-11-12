"""Local-only execution records; no provider or payment actions are performed."""

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from payment_plan import create_payment_plan


def database_path():
    return Path(os.environ.get("KWIKPAY_EXECUTION_DB", Path(__file__).parent / "runtime" / "executions.sqlite3"))


def connection():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
    for version, filename in ((1, "001_execution_records.sql"), (2, "002_execution_legs.sql"), (3, "003_provider_legs.sql"), (4, "004_test_wallet_sessions.sql"), (5, "005_payment_diagnostics.sql"), (6, "006_open_payments_evidence.sql"), (7, "007_incoming_payment_evidence.sql")):
        if not db.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (version,)).fetchone():
            db.executescript((Path(__file__).parent / "migrations" / filename).read_text())
    return db


def create_execution(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get("id"), str) or not plan["id"].strip() or len(plan["id"]) > 100:
        raise ValueError("A valid payment plan ID is required.")
    legs = plan.get("legs")
    if not isinstance(legs, list) or len(legs) != 2 or any(not isinstance(leg, dict) for leg in legs):
        raise ValueError("Payment plan requires two legs.")
    if plan.get("status") != "CREATED" or any(leg.get("status") != "PENDING" for leg in legs):
        raise ValueError("Only newly created plans with pending legs can be recorded.")
    if any(not isinstance(leg.get("id"), str) or not leg["id"].strip() for leg in legs) or legs[0]["id"] == legs[1]["id"]:
        raise ValueError("Payment leg IDs must be non-empty and unique.")
    expected = create_payment_plan({"shopId": plan.get("shopId"), "saleId": plan.get("saleId"),
        "payerWalletAddress": plan.get("payerWalletAddress"), "amount": plan.get("amount"),
        "rule": {"version": plan.get("ruleVersion"), "destinations": legs}})
    if any(leg.get("amount") != check["amount"] for leg, check in zip(legs, expected["legs"])):
        raise ValueError("Payment leg amounts do not match the split.")
    encoded = json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False)
    execution_id = f"exec_{uuid4().hex}"
    with closing(connection()) as db, db:
        created = db.execute("INSERT INTO execution_records (id, plan_id, plan_json, status) VALUES (?, ?, ?, 'CREATED') ON CONFLICT(plan_id) DO NOTHING", (execution_id, plan["id"], encoded)).rowcount
        if created:
            db.executemany("INSERT INTO execution_legs (execution_id, leg_id, status) VALUES (?, ?, 'PENDING')", [(execution_id, leg["id"]) for leg in legs])
        row = db.execute("SELECT id, plan_json, status FROM execution_records WHERE plan_id = ?", (plan["id"],)).fetchone()
        states = db.execute("SELECT leg_id, status FROM execution_legs WHERE execution_id = ?", (row[0],)).fetchall()
    if row[1] != encoded:
        raise ValueError("Payment plan ID is already associated with a different plan.")
    return get_execution(row[0])


def get_execution(execution_id):
    with closing(connection()) as db, db:
        row = db.execute("SELECT id, plan_json, status FROM execution_records WHERE id = ?", (execution_id,)).fetchone()
        states = db.execute("SELECT leg_id, status FROM execution_legs WHERE execution_id = ?", (execution_id,)).fetchall() if row else []
        is_test = bool(row and db.execute("SELECT 1 FROM test_wallet_sessions WHERE execution_id=?", (execution_id,)).fetchone())
        evidence = db.execute("SELECT leg_id,sent_value,received_value,observed_at FROM open_payments_evidence WHERE execution_id=?", (execution_id,)).fetchall() if is_test else []
        incoming = db.execute("SELECT leg_id,incoming_url,completed,received_value,observed_at FROM incoming_payment_evidence WHERE execution_id=?", (execution_id,)).fetchall() if is_test else []
    if not row:
        return None
    result = response(row, states, is_test)
    if is_test:
        observations = {leg_id: {"sent": sent, "received": received, "observedAt": observed} for leg_id, sent, received, observed in evidence}
        incoming_by_leg = {leg_id: {"id": url, "completed": bool(completed), "received": received, "observedAt": observed} for leg_id, url, completed, received, observed in incoming}
        for leg in result["legs"]:
            leg["incomingPayment"] = incoming_by_leg.get(leg["legId"])
            leg["walletStatus"] = "UNVERIFIED"
            leg["openPayments"] = observations.get(leg["legId"])
    return result


def response(row, states, is_test=False):
    plan = json.loads(row[1])
    # shortcut: Open Payments does not expose the wallet transaction status here; preserve old results as unverified until it does.
    states = [(leg_id, 'PROCESSING' if is_test and status == 'COMPLETED' else status) for leg_id, status in states]
    status = 'PROCESSING' if is_test and row[2] in ('COMPLETED', 'PARTIAL') and any(s == 'PROCESSING' for _, s in states) else row[2]
    return {"executionId": row[0], "paymentPlanId": plan["id"], "status": status, "plan": plan,
            "legs": [{"legId": leg_id, "status": state} for leg_id, state in states]}


def claim_outgoing(execution_id, leg_id):
    """Record one submission attempt before any network call; uncertain attempts are never retried."""
    with closing(connection()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        allowed = db.execute("SELECT r.plan_json FROM execution_records r JOIN execution_legs l ON l.execution_id=r.id "
                             "WHERE r.id=? AND l.leg_id=? AND r.status='PROCESSING' AND l.status='PREPARED'",
                             (execution_id, leg_id)).fetchone()
        if not allowed:
            return False
        leg = next((item for item in json.loads(allowed[0])["legs"] if item["id"] == leg_id), None)
        if not leg or int(leg["amount"]["value"]) <= 0:
            return False
        claimed = db.execute("INSERT OR IGNORE INTO provider_legs (execution_id, leg_id) VALUES (?, ?)",
                             (execution_id, leg_id)).rowcount
        if claimed:
            db.execute("UPDATE execution_legs SET status='PROCESSING' WHERE execution_id=? AND leg_id=?", (execution_id, leg_id))
            db.execute("INSERT INTO payment_diagnostics (execution_id, leg_id, operation, outcome) VALUES (?, ?, 'send', 'attempt_started')", (execution_id, leg_id))
        return bool(claimed)


def record_outgoing(execution_id, leg_id, outgoing_url):
    """Persist the provider resource identity; never replace an existing identity."""
    from urllib.parse import urlsplit
    url = urlsplit(outgoing_url)
    if url.scheme != "https" or url.hostname != "ilp.interledger-test.dev" or url.port is not None or url.username or url.password or url.query or url.fragment or not url.path:
        raise ValueError("Invalid Test Wallet outgoing payment URL.")
    with closing(connection()) as db, db:
        changed = db.execute("UPDATE provider_legs SET outgoing_url=? WHERE execution_id=? AND leg_id=? AND outgoing_url IS NULL",
                             (outgoing_url, execution_id, leg_id)).rowcount
        row = db.execute("SELECT outgoing_url FROM provider_legs WHERE execution_id=? AND leg_id=?", (execution_id, leg_id)).fetchone()
        if not row or (not changed and row[0] != outgoing_url):
            raise ValueError("Outgoing payment identity does not match the recorded attempt.")


def reconcile_outgoing(execution_id, leg_id, outgoing_url, received, failed, sent=None):
    """Apply verified provider data; unconfirmed or partial receipts stay nonterminal."""
    if not isinstance(received, dict) or received.get("assetCode") != "ZAR" or received.get("assetScale") != 2 or not isinstance(received.get("value"), str) or not received["value"].isascii() or not received["value"].isdigit() or not isinstance(failed, bool):
        raise ValueError("Invalid outgoing payment result.")
    with closing(connection()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT r.plan_json, l.status, p.outgoing_url, p.received_value FROM execution_records r "
                         "JOIN execution_legs l ON l.execution_id=r.id JOIN provider_legs p "
                         "ON p.execution_id=l.execution_id AND p.leg_id=l.leg_id "
                         "WHERE r.id=? AND l.leg_id=?", (execution_id, leg_id)).fetchone()
        if not row or row[2] != outgoing_url:
            raise ValueError("Outgoing payment does not match the recorded leg.")
        leg = next((item for item in json.loads(row[0])["legs"] if item["id"] == leg_id), None)
        if not leg:
            raise ValueError("Payment leg not found in stored plan.")
        value, expected = int(received["value"]), int(leg["amount"]["value"])
        if row[3] is not None and value < int(row[3]):
            raise ValueError("Received amount cannot decrease.")
        if value > expected:
            raise ValueError("Received amount exceeds the planned leg amount.")
        if sent is not None:
            if not isinstance(sent, dict) or sent.get("assetCode") != "ZAR" or sent.get("assetScale") != 2 or not isinstance(sent.get("value"), str) or not sent["value"].isascii() or not sent["value"].isdigit():
                raise ValueError("Invalid sent amount.")
            previous = db.execute("SELECT sent_value FROM open_payments_evidence WHERE execution_id=? AND leg_id=?", (execution_id, leg_id)).fetchone()
            if previous and int(sent["value"]) < int(previous[0]):
                raise ValueError("Sent amount cannot decrease.")
        # shortcut: a completed incoming payment does not confirm the wallet transaction; keep success processing until wallet status is available.
        status = "FAILED" if failed and value == 0 else "PROCESSING"
        if row[1] in ("COMPLETED", "FAILED") and row[1] != status:
            raise ValueError("Cannot overwrite a terminal result.")
        db.execute("UPDATE provider_legs SET received_value=? WHERE execution_id=? AND leg_id=?", (received["value"], execution_id, leg_id))
        if sent is not None:
            db.execute("INSERT INTO open_payments_evidence (execution_id,leg_id,sent_value,received_value) VALUES (?,?,?,?) ON CONFLICT(execution_id,leg_id) DO UPDATE SET sent_value=excluded.sent_value,received_value=excluded.received_value,observed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')", (execution_id, leg_id, sent["value"], received["value"]))
        db.execute("UPDATE execution_legs SET status=? WHERE execution_id=? AND leg_id=?", (status, execution_id, leg_id))
        states = [r[0] for r in db.execute("SELECT status FROM execution_legs WHERE execution_id=?", (execution_id,))]
        overall = "COMPLETED" if all(s == "COMPLETED" for s in states) else "FAILED" if all(s == "FAILED" for s in states) else "PARTIAL" if all(s in ("COMPLETED", "FAILED") for s in states) else "PROCESSING"
        db.execute("UPDATE execution_records SET status=? WHERE id=?", (overall, execution_id))
    return get_execution(execution_id)


def record_incoming(execution_id, leg_id, incoming):
    """Save a provider observation only when it matches the stored quote and leg."""
    from urllib.parse import urlsplit
    if not isinstance(incoming, dict) or type(incoming.get("completed")) is not bool:
        raise ValueError("Invalid incoming payment result.")
    received = incoming.get("receivedAmount")
    if not isinstance(received, dict) or received.get("assetCode") != "ZAR" or received.get("assetScale") != 2 or not isinstance(received.get("value"), str) or not received["value"].isascii() or not received["value"].isdigit():
        raise ValueError("Invalid incoming payment amount.")
    incoming_id = incoming.get("id")
    if not isinstance(incoming_id, str):
        raise ValueError("Invalid incoming payment ID.")
    uri = urlsplit(incoming_id)
    if uri.scheme != "https" or uri.hostname != "ilp.interledger-test.dev" or uri.port is not None or uri.username or uri.password or uri.query or uri.fragment or not uri.path:
        raise ValueError("Invalid incoming payment ID.")
    with closing(connection()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT r.plan_json,s.quotes_json FROM execution_records r JOIN test_wallet_sessions s ON s.execution_id=r.id JOIN provider_legs p ON p.execution_id=r.id WHERE r.id=? AND p.leg_id=? AND p.outgoing_url IS NOT NULL", (execution_id, leg_id)).fetchone()
        if not row:
            raise ValueError("No recorded payment leg.")
        plan = json.loads(row[0]); quotes = json.loads(row[1])
        index = next((i for i, leg in enumerate(plan["legs"]) if leg["id"] == leg_id), None)
        if index is None or index >= len(quotes):
            raise ValueError("Payment leg not found.")
        leg = plan["legs"][index]
        if quotes[index].get("receiver") != incoming_id or incoming.get("walletAddress") != leg["walletAddress"] or int(received["value"]) > int(leg["amount"]["value"]):
            raise ValueError("Incoming payment does not match the stored leg.")
        previous = db.execute("SELECT incoming_url,completed,received_value FROM incoming_payment_evidence WHERE execution_id=? AND leg_id=?", (execution_id, leg_id)).fetchone()
        if previous and (previous[0] != incoming_id or (previous[1] and not incoming["completed"]) or int(received["value"]) < int(previous[2])):
            raise ValueError("Incoming payment evidence cannot be replaced or reversed.")
        db.execute("INSERT INTO incoming_payment_evidence (execution_id,leg_id,incoming_url,completed,received_value) VALUES (?,?,?,?,?) ON CONFLICT(execution_id,leg_id) DO UPDATE SET completed=excluded.completed,received_value=excluded.received_value,observed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')", (execution_id, leg_id, incoming_id, int(incoming["completed"]), received["value"]))


def sales_overview(offset=0):
    """Read local execution history and totals without including grant credentials."""
    with closing(connection()) as db:
        db.execute("BEGIN")
        rows = db.execute("SELECT r.id,r.plan_json,r.status,r.created_at, s.execution_id IS NOT NULL "
                          "FROM execution_records r LEFT JOIN test_wallet_sessions s ON s.execution_id=r.id "
                          "ORDER BY r.created_at DESC,r.rowid DESC").fetchall()
        legs = db.execute("SELECT l.execution_id,l.leg_id,l.status,p.received_value FROM execution_legs l "
                          "LEFT JOIN provider_legs p ON p.execution_id=l.execution_id AND p.leg_id=l.leg_id").fetchall()
    by_execution = {}
    for execution_id, leg_id, status, received in legs:
        by_execution.setdefault(execution_id, {})[leg_id] = (status, received)
    status_counts = {status: 0 for status in ('CREATED', 'AWAITING_CONSENT', 'PROCESSING', 'COMPLETED', 'PARTIAL', 'FAILED')}
    completed = 0
    confirmed_sales = 0
    confirmed_receipts = 0
    confirmed_by_pot = {}
    history = []
    for row_index, (execution_id, encoded, status, created_at, is_test) in enumerate(rows):
        plan = json.loads(encoded)
        leg_states = by_execution.get(execution_id, {})
        if is_test:
            leg_states = {leg_id: ('PROCESSING' if state == 'COMPLETED' else state, received) for leg_id, (state, received) in leg_states.items()}
            if status in ('COMPLETED', 'PARTIAL') and any(state == 'PROCESSING' for state, _ in leg_states.values()):
                status = 'PROCESSING'
        status_counts[status] = status_counts.get(status, 0) + 1
        if is_test and status == 'COMPLETED':
            completed += 1
            confirmed_sales += int(plan['amount']['value'])
        if is_test:
            for leg in plan['legs']:
                state, received = leg_states.get(leg['id'], ('PENDING', None))
                if state != 'COMPLETED':
                    continue
                if received is not None:
                    value = int(received)
                    confirmed_receipts += value
                    confirmed_by_pot[leg['label']] = confirmed_by_pot.get(leg['label'], 0) + value
        if offset <= row_index < offset + 100:
            history.append({'executionId': execution_id, 'createdAt': created_at.replace(' ', 'T') + 'Z',
                'status': status, 'source': 'test_wallet' if is_test else 'tracking', 'amount': plan['amount'],
                'legs': [{'label': leg['label'], 'amount': leg['amount'],
                          'status': leg_states.get(leg['id'], ('PENDING', None))[0]} for leg in plan['legs']]})
    return {'history': history, 'summary': {'recordCount': len(rows), 'completedTestSales': completed,
            'completedSalesValue': str(confirmed_sales), 'confirmedReceipts': str(confirmed_receipts),
            'statusCounts': status_counts, 'confirmedByPot': [{'label': label, 'value': str(value)} for label, value in sorted(confirmed_by_pot.items())]}}
