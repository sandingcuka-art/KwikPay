# Two-phone checkout demo

This is an isolated, local-only prototype of a merchant-presented request QR. It does **not** connect to Open Payments or send money. It uses a temporary in-memory request store; requests expire after five minutes and disappear when the process stops. The split is fixed at 80% business income and 20% stock reserve for this demo.

1. Start `python3 -B -u mobile_demo_api.py` in this directory. It binds only to `127.0.0.1:8060`.
2. Connect both Android phones with USB debugging, then run `adb -s DEVICE_SERIAL reverse tcp:8060 tcp:8060` for each phone. Install the merchant and customer debug APKs on their respective devices.
3. On the merchant app, select **Create payment request** and create the QR. On the customer app, choose **Scan merchant request** and review the amount. Sharing the wallet address tells the merchant the customer is reviewing; it does not authorize a payment.

The QR contains an unpredictable request URL accepted only at the local demo origin. Cleartext HTTP is enabled only in the Android debug manifests for USB forwarding. Do not use this demo API, its bearer-like QR URLs, or HTTP for a deployed checkout. A real flow still needs merchant/customer authentication, HTTPS, durable idempotency and per-leg execution state, wallet-provider authorization, and reconciliation.
