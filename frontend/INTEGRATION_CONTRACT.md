# KwikPay Dev1 Integration Contract

> Legacy contract: the authoritative two-pot MVP request and `PaymentPlan` are in `../../MVP.md`. The current UI calls `POST /api/payment-plans`; the older shapes below describe the retained legacy UI only.

The UI is intentionally isolated from backend implementation details. All backend integration belongs in `src/api.ts`.

## Implemented locally

- `GET /api/health`: identifies the Python core; `paymentExecution` is `false`.
- `POST /api/sales`: validates positive ZAR amounts in whole cents and calculates allocations. With `shopId`, calls Java `POST /api/payments` and returns the response in `payment` (`id`, `shopId`, `amount`, `currency`, `status: PENDING`, `createdAt`). HTTP `201` means a record was saved, not a transfer completed.
- `POST /api/payment-executions`: HTTP `501`; consent and wallet execution are not implemented.
- Java on port 8081 already exposes `GET /api/payments/{id}` and `GET /api/payments/shop/{shopId}`. These are not yet wired to the sample dashboard.

Python listens on 8025. Vite on 5180 proxies `/api` to it. The **target** endpoints below describe remaining work, not implemented functionality. The live UI blocks simulated consent and completion.

## Current Dev2 compatibility

Dev2 currently returns:

```json
{
  "amount": 100,
  "split": {
    "supplier": 20,
    "salaries": 5,
    "maintenance": 5,
    "profit": 70
  }
}
```

The UI can normalize that response into a `PaymentPlan`.

## Target shared contract

Dev2 should ultimately create this model and Dev3 should execute it:

```json
{
  "id": "plan_123",
  "saleId": "sale_456",
  "shopId": "shop_001",
  "assetCode": "ZAR",
  "assetScale": 2,
  "totalMinor": 10000,
  "status": "PREVIEW",
  "legs": [
    {
      "id": "leg_1",
      "label": "supplier",
      "amountMinor": 2000,
      "percentage": 20,
      "walletAddress": "https://wallet.example/supplier",
      "status": "PENDING"
    },
    {
      "id": "leg_2",
      "label": "profit",
      "amountMinor": 7000,
      "percentage": 70,
      "walletAddress": "https://wallet.example/merchant",
      "status": "PENDING"
    }
  ]
}
```

## Target endpoints

### Dev2

```http
POST /api/payment-plans
```

Input:

```json
{
  "amountMinor": 10000,
  "assetCode": "ZAR",
  "assetScale": 2,
  "rules": [
    { "label": "supplier", "percentage": 20, "walletAddress": "..." }
  ]
}
```

Output: `PaymentPlan`.

### Dev3

```http
POST /api/payment-executions
```

Input: `PaymentPlan`.

Initial output:

```json
{
  "executionId": "exec_123",
  "paymentPlanId": "plan_123",
  "status": "AWAITING_CONSENT",
  "interactUrl": "https://wallet-provider.example/consent/..."
}
```

Then:

```http
GET /api/payment-executions/exec_123
```

Final output should expose plan status and per-leg status. Valid final states include `COMPLETED`, `PARTIAL`, and `FAILED`.

## MVP acceptance test

1. Configure 80/20 split.
2. Capture a R100 sale.
3. UI shows R80 + R20 payment legs before payment.
4. Customer completes real Open Payments consent.
5. Dev3 executes both outgoing payments.
6. UI shows both legs completed.
7. Two receiving Test Wallet balances reflect R80 and R20.
8. UI shows `Funds held by KwikPay: R0.00`.
