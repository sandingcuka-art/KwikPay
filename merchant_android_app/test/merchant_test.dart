import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kwikpay_merchant/main.dart';

const customer = 'https://ilp.interledger-test.dev/wikus-customer';

void main() {
  test('accepts customer app QR addresses and rejects unsafe inputs', () {
    expect(walletAddress(customer), customer);
    expect(
      walletAddress(r'$ilp.interledger-test.dev/wikus-customer'),
      customer,
    );
    for (final input in [
      '',
      'http://example.com',
      'https://',
      'https://user:secret@example.com/a',
      'https://example.com/?token=secret',
      'https://example.com/a#fragment',
      'https://example.com/a b',
    ]) {
      expect(walletAddress(input), isNull, reason: input);
    }
  });

  testWidgets('invalid code stays on scanner; valid code returns the wallet', (
    tester,
  ) async {
    String? scanned;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () async {
                scanned = await Navigator.of(context).push<String>(
                  MaterialPageRoute(
                    builder: (_) => WalletScanPage(
                      cameraBuilder: (onCode) => Column(
                        children: [
                          TextButton(
                            onPressed: () => onCode('not a wallet'),
                            child: const Text('Invalid code'),
                          ),
                          TextButton(
                            onPressed: () => onCode(customer),
                            child: const Text('Valid code'),
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              },
              child: const Text('Open scanner'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Open scanner'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Invalid code'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('invalid-qr')), findsOneWidget);
    expect(scanned, isNull);
    await tester.tap(find.text('Valid code'));
    await tester.pumpAndSettle();
    expect(scanned, customer);
    expect(find.text('Open scanner'), findsOneWidget);
  });

  testWidgets('merchant shell clearly indicates payments are not connected', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const KwikPayMerchantApp());
    expect(find.text('Scan wallet QR code'), findsOneWidget);
    expect(
      find.textContaining('Wallet approval and payments are not connected'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('scanned address appears on merchant review screen', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: MerchantHome(
          cameraBuilder: (onCode) => TextButton(
            onPressed: () => onCode(customer),
            child: const Text('Simulate camera scan'),
          ),
        ),
      ),
    );
    await tester.ensureVisible(find.text('Scan wallet QR code'));
    await tester.tap(find.text('Scan wallet QR code'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Simulate camera scan'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('captured-wallet')), findsOneWidget);
    expect(find.text(customer), findsOneWidget);
    expect(find.text('Customer wallet captured'), findsOneWidget);
    expect(find.textContaining('have not been verified'), findsOneWidget);
    expect(find.text('Scan another wallet'), findsOneWidget);
  });
}
