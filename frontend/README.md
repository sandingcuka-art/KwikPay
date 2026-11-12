# KwikPay Merchant UI — Dev1 MVP

## Current two-pot flow

Use the labelled Test Wallet shortcut buttons to fill the customer and merchant addresses. **Sales** shows saved execution records and leg statuses; **Reports** shows all-time completed Test Wallet sales and confirmed receipts, including a per-pot breakdown. Each local backend has its own database; the Test Wallet checkout is on port 5182.

Start `python3 server.py` from the repository root, then run `npm run dev` here. Enter two pot names and wallet addresses, save the 100% split, enter a sale amount and customer wallet, and preview the canonical plan returned by `/api/payment-plans`. Create a tracking record to see its status; the page polls while the record is nonterminal and restores the active record after reload. Pot settings are saved in this browser on this device. The optional simulation displays illustrative results locally and does not create or change an execution record. That default flow does not send payments. The opt-in R1 Test Wallet flow, setup, and its limitations are documented in the root README.

To verify the rendered journey against the local API at desktop and mobile sizes, run from the repository root:

```bash
python3 -B /Users/raven/.agents/skills/webapp-testing/scripts/with_server.py --server 'python3 -B server.py' --port 8025 --server 'cd frontend && npm run dev' --port 5180 -- python3 -B frontend/tests/two_pot_journey.py
```

The sections below describe the earlier legacy UI and record flow, which remain in source but are not the current application entry point. Its `ui_regression.py` targets that legacy interface.

React + Vite + TypeScript merchant-facing MVP for the Dev1 lane.

## Connected local flow (default)

Start PostgreSQL, Java and Python using the root README, then run `npm ci` and `npm run dev` here. The UI is served at **http://127.0.0.1:5180/** and Vite forwards `/api` to the Python core on **8025**.

Configure rules, capture a sale, and choose **Calculate & save sale**. The Python core calculates the allocation and the Java service persists a **PENDING** payment record in PostgreSQL. Its actual ID appears in the UI. Wallet transfers and customer consent remain unavailable; the UI cannot mark a live payment complete. Dashboard figures are labelled sample data, and rules are not yet persisted.

In Split rules, **Use this split** applies your edits for the current session. Back or navigation away discards unapplied edits; reloading restores defaults. Saved sales offer **Done** and **New sale**, with the full payment reference available on expansion.

## UI regression check

With the frontend running, Python Playwright and Google Chrome installed:

```bash
python3 -B tests/ui_regression.py
```

Checks desktop, tablet and mobile layouts, labels, focus, contrast, draft/apply behaviour, error recovery and saved-sale actions. Sale responses are intercepted fixtures; the check creates no payment records. Screenshots are written to the system temporary directory under `kwikpay-ui-taste`.

## Simulated demo flow (explicit opt-in)

1. Overview/dashboard
2. Configure split rules
3. Capture sale
4. Preview generated payment plan
5. Simulated Open Payments customer consent
6. Split payment result with per-leg status and `R0.00` held by KwikPay

## Run

```bash
npm install
npm run dev
```

## API strategy

The UI defaults to the live local backend. To opt into the entirely simulated consent/completion flow, create `.env.local`:

```env
VITE_USE_LIVE_API=false
```

Restart Vite after changing environment variables. `src/api.ts` is the integration seam. Leave `VITE_CORE_API_URL` empty to use the same-origin Vite proxy; a separately hosted API would need its own CORS configuration.

The current live compatibility path expects:

```http
POST /api/sales
```

with:

```json
{
  "amount": 100,
  "shopId": "kwikpay-demo-shop",
  "currency": "ZAR",
  "supplier": 20,
  "salaries": 5,
  "maintenance": 5
}
```

The UI then normalizes the current Dev2 response into a `PaymentPlan` with payment legs so Dev3 can later consume the same model.
