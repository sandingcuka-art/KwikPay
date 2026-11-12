# KwikPay Merchant Android

A local demo for scanning a customer's wallet or showing a merchant payment-request QR. The **Create payment request** action can connect to the local demo API or the Test Wallet API, depending on the build configuration. See [the two-phone demo instructions](../MOBILE_DEMO.md).

The existing **Scan wallet QR code** action reads a plain HTTPS wallet address, checks its format, and displays it locally. It does not verify ownership or whether the URL is an Open Payments wallet. Camera access can be changed in Android settings. Barcode scanning uses bundled ML Kit.

Build and check: `flutter pub get`, `flutter analyze`, `flutter test`, `flutter build apk --debug`. The debug APK is at `build/app/outputs/flutter-apk/app-debug.apk` and is not release signed. Use a different Android phone or screen to display the customer QR when testing the camera.
