import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Any


class ReportingAPI:
    """Simple SQLite-backed storage and reporting layer for transactions and shop rules."""

    def __init__(self, db_path: str = "kwikpay.db"):
        self.db_path = db_path or os.environ.get("KWIKPAY_DB_PATH", "kwikpay.db")
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_columns(self, conn):
        columns = conn.execute("PRAGMA table_info(transactions)").fetchall()
        current_columns = {column[1] for column in columns}
        if "payment_status" not in current_columns:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'PENDING'"
            )

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_id TEXT NOT NULL,
                    rule_name TEXT NOT NULL,
                    percent REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(shop_id, rule_name)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_id TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    payment_reference TEXT,
                    split_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._ensure_columns(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_transactions_shop_id ON transactions(shop_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_transactions_payment_reference ON transactions(payment_reference)"
            )

    def save_rule(self, shop_id: str, rule_name: str, percent: float) -> Dict[str, Any]:
        if not shop_id or not rule_name:
            raise ValueError("shop_id and rule_name are required.")

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO rules (shop_id, rule_name, percent, active, updated_at)
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(shop_id, rule_name)
                DO UPDATE SET percent = excluded.percent,
                              active = 1,
                              updated_at = CURRENT_TIMESTAMP
                """,
                (shop_id, rule_name, float(percent)),
            )
            conn.commit()
        finally:
            conn.close()

        return self.get_rules(shop_id)

    def get_rule(self, shop_id: str, rule_name: str) -> float:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT percent FROM rules WHERE shop_id = ? AND rule_name = ? AND active = 1",
                (shop_id, rule_name),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(f"Rule '{rule_name}' was not found for shop '{shop_id}'.")
        return float(row["percent"])

    def delete_rule(self, shop_id: str, rule_name: str) -> bool:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE rules SET active = 0, updated_at = CURRENT_TIMESTAMP WHERE shop_id = ? AND rule_name = ?",
                (shop_id, rule_name),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_rules(self, shop_id: str) -> Dict[str, float]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT rule_name, percent FROM rules WHERE shop_id = ? AND active = 1 ORDER BY rule_name",
                (shop_id,),
            ).fetchall()
        finally:
            conn.close()
        return {row["rule_name"]: float(row["percent"]) for row in rows}

    def record_transaction(
        self,
        shop_id: str,
        amount: float,
        currency: str,
        split: Dict[str, float],
        payment_reference: str = None,
        payment_status: str = "PENDING",
    ) -> int:
        if not shop_id:
            raise ValueError("shop_id is required.")

        payload = json.dumps(split, sort_keys=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO transactions (shop_id, amount, currency, payment_reference, payment_status, split_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (shop_id, float(amount), currency, payment_reference, payment_status, payload, timestamp),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def get_payment_status(self, shop_id: str, payment_reference: str) -> str:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payment_status FROM transactions WHERE shop_id = ? AND payment_reference = ? ORDER BY id DESC LIMIT 1",
                (shop_id, payment_reference),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(f"Payment '{payment_reference}' was not found for shop '{shop_id}'.")
        return row["payment_status"]

    def update_payment_status(self, shop_id: str, payment_reference: str, payment_status: str) -> str:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE transactions SET payment_status = ? WHERE shop_id = ? AND payment_reference = ?",
                (payment_status, shop_id, payment_reference),
            )
            conn.commit()
        finally:
            conn.close()
        if cursor.rowcount == 0:
            raise KeyError(f"Payment '{payment_reference}' was not found for shop '{shop_id}'.")
        return payment_status

    def list_transactions(self, shop_id: str) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, shop_id, amount, currency, payment_reference, payment_status, split_json, created_at
                FROM transactions
                WHERE shop_id = ?
                ORDER BY created_at DESC
                """,
                (shop_id,),
            ).fetchall()
        finally:
            conn.close()

        results = []
        for row in rows:
            results.append(
                {
                    "id": row["id"],
                    "shop_id": row["shop_id"],
                    "amount": float(row["amount"]),
                    "currency": row["currency"],
                    "payment_reference": row["payment_reference"],
                    "payment_status": row["payment_status"],
                    "split": json.loads(row["split_json"]),
                    "created_at": row["created_at"],
                }
            )
        return results

    def shop_summary(self, shop_id: str) -> Dict[str, Any]:
        transactions = self.list_transactions(shop_id)
        total_sales = sum(item["amount"] for item in transactions)

        payment_status_counts = defaultdict(int)
        for transaction in transactions:
            payment_status_counts[transaction.get("payment_status", "PENDING")] += 1

        summary = {
            "shop_id": shop_id,
            "total_sales": float(total_sales),
            "transaction_count": len(transactions),
            "total_profit": 0.0,
            "supplier_total": 0.0,
            "salaries_total": 0.0,
            "maintenance_total": 0.0,
            "payment_status_summary": dict(sorted(payment_status_counts.items())),
            "rules": self.get_rules(shop_id),
        }

        for item in transactions:
            split = item.get("split", {})
            summary["total_profit"] += float(split.get("profit", 0.0))
            summary["supplier_total"] += float(split.get("supplier", 0.0))
            summary["salaries_total"] += float(split.get("salaries", 0.0))
            summary["maintenance_total"] += float(split.get("maintenance", 0.0))

        return summary
