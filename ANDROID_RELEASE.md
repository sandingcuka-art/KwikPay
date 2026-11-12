# Android team release 0.2.0

Merchant update 0.2.2 (version code 4) retains the Paste button and allows Test Wallet sales up to R10. Its APK SHA-256 is `07c42f0ec704ed26d51ac59a661c3373092957ad13e139f21c6afdeb7ba02682`. It uses the same signing certificate and can update earlier release builds without clearing app data. The customer release remains at 0.2.0. Railway completed the 0.2.1 deployment after its upload command timed out.

The customer and merchant Test Wallet APKs target Android 7.0 (API 24) and later. Both have version code 2 and use the release certificate SHA-256 `98fe0e98ff4a29941addd780ef5793d5e5d58121f7d20e072d54856742e9c6de`.

| App | Package | APK SHA-256 |
| --- | --- | --- |
| Customer | `za.co.kwikpay.kwikpay_customer` | `23617a09a05dc272318cce72288e83486b54b1d7882897da21c9d987347abb07` |
| Merchant | `za.co.kwikpay.kwikpay_merchant` | `720c71c3a60ebceadca3b8f6a199eb25fe29cccde7bf72d9b493f19074d9ffd8` |

The dashboard Apps page provides authenticated downloads. Merchants enter the shared merchant API key in **Merchant access**; provide that key separately through a secure channel. It is stored on the device using Android Keystore encryption and is not bundled in either APK.

For the Railway build, the downloads staging directory contains the customer APK, the merchant 0.2.0 APK, the manifest, and zstd patch files for merchant versions 0.2.1 and 0.2.2. The Dockerfile reconstructs both newer signed APKs from the 0.2.0 APK during the build to keep the upload small while retaining older download links. Verify the rebuilt APK checksums against the release manifest.

The release signing keystore is in `.kwikpay-signing/`, with a local copy in `.kwikpay-signing-backup/`. Its password is in the login Keychain under service `KwikPay Team Android Signing` and account `kwikpay-team-test-v1`. Keep these out of source control and back up both the keystore and password securely on a separate device. The same signing identity is required for future updates.

For later builds, provide `KWIKPAY_ANDROID_KEYSTORE`, `KWIKPAY_ANDROID_STORE_PASSWORD`, and `KWIKPAY_ANDROID_KEY_PASSWORD` in the build environment, then run `flutter build apk --release --build-name=0.2.0 --build-number=2 --dart-define=KWIKPAY_API_ORIGIN=https://test-wallet-payments-production.up.railway.app --dart-define=KWIKPAY_TEST_WALLET=true` in each app directory. Increase the version for the next release and retain versioned APKs and checksums.

Existing debug-signed installations cannot be updated in place by these release-signed APKs. Do not remove an existing app without preserving its local data. A fresh merchant installation and access-setting persistence were checked on the Samsung; the customer release was not installed over its existing debug app. Platform distribution requirements can change; see [Android developer verification](https://developer.android.com/developer-verification/guides).
