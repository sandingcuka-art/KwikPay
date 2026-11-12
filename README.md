## Hosted merchant terminal

On the Railway Test Wallet dashboard, **New sale** creates a request from R0.02 up to R10.00 using the saved pot split (each pot must receive at least R0.01). The customer scans its QR in the KwikPay Customer Android app and approves in their wallet. The terminal polls each leg and reports Open Payments amounts; wallet settlement remains unverified. The QR request expires after five minutes. The dashboard uses its existing sign-in, and the merchant API key is not sent to the browser.

# KwikPay

## Two-pot MVP preview

The current frontend lets a merchant name two pots, connect wallet addresses, set percentages, and preview a sale using `POST /api/payment-plans`. Run `python3 server.py` in this directory and `npm run dev` in `frontend/`, then open `http://127.0.0.1:5180/`. Pot settings persist in browser storage. The optional simulated split runs only in the browser and does not create or update payment records. This flow does not require PostgreSQL or the Java service.

**Sales** lists saved execution records and their leg statuses, with pages of 100. **Reports** uses all records in the currently selected local database. Test Wallet receipts and sales are excluded from confirmed totals until the wallet transaction status can be verified; a completed incoming payment alone is not enough. Earlier Test Wallet completions are displayed as processing/unverified without modifying their stored records. Tracking-only records and simulations are not counted as completed payments. The normal demo on port 5181 and the Test Wallet demo on port 5182 use separate databases.

The canonical request and response are specified in `../MVP.md`. Amounts use integer minor-unit strings; two percentages must total 100, and the final leg receives any rounding remainder. Pot settings are retained in this browser. The server returns a plan without creating a payment record.

The local scaffold records execution requests in a separate SQLite database at `runtime/executions.sqlite3` (override with `KWIKPAY_EXECUTION_DB`). Versioned SQL migrations create its execution and leg tables. `POST /api/payment-executions` stores the canonical plan idempotently and returns `CREATED`; `GET /api/payment-executions/{executionId}` returns its stored state. The UI polls and can display terminal results. The normal tracking-record flow does not send payments. An explicitly enabled, separate Test Wallet flow is described below; the MVP’s Java execution service and a production-ready handoff remain to be built.

The existing `/api/sales` and Java `/api/payments` record flow below is a separate legacy path, retained for compatibility; its payment records do not represent transfers.

KwikPay is a digital payment and settlement helper for South African spaza shops. It helps shop owners process sales, automatically split transaction value across business categories, and forward the payment record to an interoperable payment service.

## Legacy payment-record flow

The following instructions describe the earlier record flow, not the current two-pot frontend.

## Run the connected local app

Use three terminals. Python uses the standard library; no Python packages are needed.

1. Start the isolated PostgreSQL database and Java payment-record service:

   ```bash
   cd ../InterledgerPaymentService
   docker compose -p kwikpay-hack -f compose.local.yaml up -d --wait
   export JAVA_HOME=$(/usr/libexec/java_home -v 25)
   DB_URL=jdbc:postgresql://127.0.0.1:55434/payment_db ./mvnw -B -ntp spring-boot:run -Dspring-boot.run.arguments="--server.address=127.0.0.1 --server.port=8081"
   ```

   Java 21 or newer is required; this checkout was verified with the installed JDK 25.

2. From this repository, start the Python core:

   ```bash
   python3 server.py
   ```

3. From this repository, start the frontend:

   ```bash
   cd frontend
   npm ci
   npm run dev
   ```

Open **http://127.0.0.1:5180/**. Vite forwards `/api` to Python on **8025**; Python creates payment records in Java on **8081**, backed by the isolated database on **55434**. Existing databases and ports are preserved. The named Docker volume keeps records across restarts; do not use `docker compose down -v` if you need to retain them.

`GET /api/health` identifies the Python core. `POST /api/sales` accepts the payload below and returns allocations; including `shopId` also saves a `PENDING` payment record. Invalid inputs return JSON `400`; an unavailable payment service returns `502`. Amounts must be positive ZAR values in whole cents.

**Legacy boundary:** saving a pending payment record does not transfer money. Open Payments grants, customer consent, outgoing payments and reconciliation are not implemented.

## What this app does

KwikPay takes a sale amount and divides it according to configured percentages:

- Supplier
- Salaries
- Maintenance
- Profit

Example:

- Sale total: R20.00
- Supplier: 2% = R0.40
- Salaries: 3% = R0.60
- Maintenance: 5% = R1.00
- Profit: R18.00

This gives the business a clear view of where money is being allocated without doing manual calculations after each sale.

## Interledger integration

This repository is now connected to the external Interledger payment service at Holang-1/InterledgerPaymentService.

When a sale includes a shopId, KwikPay sends a payment creation request to the remote service at:

- POST /api/payments
- JSON payload:
  - shopId
  - amount
  - currency

The external service expects the currency to be ZAR and will return a payment object including the generated payment id and status.

## Project status

This project is in active development and is currently working through the following stage:

### Dev 2: payment service integration

Completed in this repo:

- Added Interledger payment submission from the sales API
- Added validation and guardrails around sale totals and percentages
- Hardened rules so invalid numbers and reserved rule names are rejected early
- Ensured allocations round cleanly to cents and preserve the total sale value
- Added regression tests covering the financial and Interledger behavior

## Environment variables

The app reads percentage values from environment variables when no explicit values are passed:

- KWIKPAY_SUPPLIER_PERCENT=2
- KWIKPAY_SALARIES_PERCENT=3
- KWIKPAY_MAINTENANCE_PERCENT=5
- INTERLEDGER_PAYMENT_SERVICE_URL=http://127.0.0.1:8081

## Example call

```python
from sales_api import create_sale_response

response = create_sale_response({
    "amount": 20,
    "shopId": "shop-42",
    "supplier": 2,
    "salaries": 3,
    "maintenance": 5,
})

print(response)
```

Example response shape:

```json
{
  "amount": 20.0,
  "split": {
    "supplier": 0.4,
    "salaries": 0.6,
    "maintenance": 1.0,
    "profit": 18.0
  },
  "payment": {
    "id": "uuid",
    "shopId": "shop-42",
    "amount": 20.0,
    "currency": "ZAR",
    "status": "PENDING"
  }
}
```

## Business value

KwikPay is designed to reduce friction for small businesses, improve financial visibility, and make digital payments easier for communities that still rely heavily on cash. It helps owners stay in control of their money while supporting more transparent, scalable operations.

## Run the tests

```bash
python -m unittest
```

## Development notes

The local codebase is intentionally lightweight and business-focused. It acts as a rules engine and sales API while the external Interledger Spring service handles payment persistence and settlement orchestration.

## Isolated Test Wallet split

The local Test Wallet integration is opt-in. The configured `wikus-customer` payer can send a ZAR sale to two selected Test Wallet addresses with positive leg amounts, up to R1000.00 total; the final quoted debit is also capped at R1000.00. For example, an R3.00 sale can send R2.40 to `kwikpay-merch-2` and R0.60 to `kwikpay-merch-3`. The UI on port 5182 requests two provider quotes, displays the payer debit, and sends the user to Test Wallet for consent. The callback verifies the interaction hash before continuing the grant. Each outgoing leg is claimed once; an uncertain submission is left pending for manual investigation rather than retried. Provider tokens are kept server-side in a private local SQLite database, not returned to the browser.

This local flow is for Test Wallet only. It is not production ready: it has no merchant authentication, automatic recovery of uncertain submissions, or production secret management. Multiple wallet addresses can share one underlying balance. Approval and settlement must be verified against the provider; an execution marked processing is not a successful transfer.

To run the isolated test flow, compile the SDK bridge and generate its runtime classpath:

```sh
cd ../InterledgerPaymentService/open-payments-java-poc
JAVA_HOME=$(/usr/libexec/java_home -v 25) ../mvnw -Dmaven.repo.local=/private/tmp/kwikpay-poc-m2 compile dependency:build-classpath -Dmdep.outputFile=/private/tmp/kwikpay-sdk-classpath.txt
```

In a separate terminal, start the local backend with a dedicated private database. Set the key ID and private-key path locally; never commit their values or print token responses:

```sh
cd /Users/raven/projects/kwikpay/hack/KwikPay
umask 077
export TEST_WALLET_ADDRESS=https://ilp.interledger-test.dev/kwikpay-merch-1
export TEST_WALLET_KEY_ID='YOUR_KEY_ID'
export TEST_WALLET_PRIVATE_KEY_FILE='/absolute/path/to/private.key'
export KWIKPAY_TEST_WALLET_ENABLED=1
export KWIKPAY_EXECUTION_DB="$PWD/runtime/test-wallet.sqlite3"
export KWIKPAY_JAVA="$(/usr/libexec/java_home -v 25)/bin/java"
export KWIKPAY_BRIDGE_CLASSPATH="$(cd ../InterledgerPaymentService/open-payments-java-poc && pwd)/target/classes:$(cat /private/tmp/kwikpay-sdk-classpath.txt)"
python3 -B server.py --port 8027
```

In another terminal, run `KWIKPAY_CORE_URL=http://127.0.0.1:8027 npm run dev -- --host 127.0.0.1 --port 5182 --strictPort` from `frontend/`. Open `http://127.0.0.1:5182/`. Both ports and the loopback callback are fixed for this isolated demo. The database contains sensitive grant tokens and is restricted to the local account; do not share it. The browser session that approves the grant must be signed into the payer’s Test Wallet profile.

Test Wallet quotes must have a valid future `expiresAt`. Expired or malformed quotes are rejected before wallet authorization and rechecked after approval and immediately before each outgoing request. A known unsubmitted leg is marked failed; an uncertain submission stays processing and is never retried automatically. Start a new payment to obtain fresh quotes; do not reuse an uncertain execution.

For future executions, the private Test Wallet database records UTC timestamps and safe categories in `payment_diagnostics`: `attempt_started`, `quote_expired`, `quote_expired_before_request`, `provider_error`, `timeout`, `bridge_unavailable`, `validation_error`, `invalid_response`, `bridge_error`, `disabled`, or `internal_error`. Provider status is stored only when available. Inspect a specific execution locally without exposing the token-bearing session table:

```sh
sqlite3 runtime/test-wallet.sqlite3 "SELECT created_at, leg_id, operation, outcome, provider_status FROM payment_diagnostics WHERE execution_id='EXECUTION_ID' ORDER BY id;"
```

Diagnostics exclude raw provider bodies, callback parameters and credentials. Earlier executions do not acquire historical error details from this migration.
