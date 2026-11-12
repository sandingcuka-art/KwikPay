# KwikPay Customer

An Android demo that turns an Open Payments wallet address into a QR code a merchant can scan. Enter an HTTPS wallet address or a `$` payment pointer and select **Create QR code**. The test shortcut fills the existing Interledger Test Wallet customer address.

The **Scan merchant request** action shows the amount and split. In the Test Wallet build it uses the configured Test Wallet API; payment requires approval in the customer’s wallet. The separate USB demo build does not send payments. See [the two-phone demo instructions](../MOBILE_DEMO.md).

The QR contains the normalized HTTPS address as plain UTF-8 text. For example, `$ilp.interledger-test.dev/wikus-customer` becomes `https://ilp.interledger-test.dev/wikus-customer`. The merchant scanner should treat it as a wallet address, validate it, and let the merchant review it. The QR is not a payment, approval, or wallet credential. Creating it works offline; scanning shares the address with the scanner. Use **Wallet settings** to save a Test Wallet address on the device for checkout. Each teammate should enter their own address; wallet approval still takes place in the wallet. Do not enter private keys or passwords. The shared Test Wallet API must support customer-selected payer addresses before teammates can complete payments.

Run `flutter pub get`, then `flutter run` on an Android device. Run `flutter analyze`, `flutter test`, and `flutter build apk --debug` for local verification. The debug APK is at `build/app/outputs/flutter-apk/app-debug.apk`; it is not a release-signed build.
