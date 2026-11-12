import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kwikpay_customer/main.dart';
import 'package:qr_flutter/qr_flutter.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  var saved = '';
  setUp(() {
    saved = '';
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(settingsChannel, (call) async {
          if (call.method == 'load') return saved;
          if (call.method == 'save') {
            saved = call.arguments as String;
            return null;
          }
          return null;
        });
  });
  tearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(settingsChannel, null),
  );

  testWidgets('saves, reloads, validates and clears personal wallet settings', (
    tester,
  ) async {
    await tester.pumpWidget(const KwikPayCustomerApp());
    await tester.pump();
    await tester.tap(find.byTooltip('Wallet settings'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('settings-wallet')),
      'https://evil.example/test',
    );
    await tester.tap(find.text('Save wallet'));
    await tester.pumpAndSettle();
    expect(
      find.text('Enter your Interledger Test Wallet address.'),
      findsOneWidget,
    );
    await tester.enterText(
      find.byKey(const Key('settings-wallet')),
      r'$ilp.interledger-test.dev/team-member',
    );
    await tester.tap(find.text('Save wallet'));
    await tester.pumpAndSettle();
    expect(saved, 'https://ilp.interledger-test.dev/team-member');
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(const KwikPayCustomerApp());
    await tester.pump();
    expect(find.text(saved), findsOneWidget);
    await tester.tap(find.byTooltip('Wallet settings'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Clear saved wallet'));
    await tester.pumpAndSettle();
    expect(saved, isEmpty);
  });

  test('validates and converts wallet addresses without credentials', () {
    expect(walletAddress('  $demoWallet  '), demoWallet);
    expect(
      walletAddress(r'$ilp.interledger-test.dev/wikus-customer'),
      demoWallet,
    );
    for (final input in [
      '',
      'http://example.com/wallet',
      'https://',
      'https://user:secret@example.com/wallet',
      'https://example.com/?token=secret',
      'https://example.com/wallet#fragment',
      'https://example.com/a b',
    ]) {
      expect(walletAddress(input), isNull, reason: input);
    }
  });

  testWidgets('shows the wallet QR and allows editing', (tester) async {
    await tester.pumpWidget(const KwikPayCustomerApp());
    await tester.ensureVisible(find.text('Create QR code'));
    await tester.tap(find.text('Create QR code'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Enter a valid HTTPS'), findsOneWidget);

    await tester.ensureVisible(find.text('Use test customer wallet'));
    await tester.tap(find.text('Use test customer wallet'));
    await tester.ensureVisible(find.text('Create QR code'));
    await tester.tap(find.text('Create QR code'));
    await tester.pumpAndSettle();
    expect(find.byType(QrImageView), findsOneWidget);
    expect(find.text(demoWallet), findsOneWidget);
    expect(find.text('Show this to the merchant'), findsOneWidget);
    final capture = Platform.environment['KWIKPAY_QR_CAPTURE'];
    if (capture != null) {
      final boundary = tester.renderObject<RenderRepaintBoundary>(
        find.byKey(const Key('wallet-qr')),
      );
      await tester.runAsync(() async {
        final image = await boundary.toImage(pixelRatio: 2);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        await File(capture).writeAsBytes(bytes!.buffer.asUint8List());
        image.dispose();
      });
    }
    await tester.ensureVisible(find.text('Change wallet address'));
    await tester.tap(find.text('Change wallet address'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('wallet-input')), findsOneWidget);
    expect(find.text(demoWallet), findsOneWidget);
  });

  testWidgets('QR remains within a small phone screen', (tester) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      const RepaintBoundary(
        key: Key('customer-screen'),
        child: KwikPayCustomerApp(),
      ),
    );
    await tester.ensureVisible(find.text('Use test customer wallet'));
    await tester.tap(find.text('Use test customer wallet'));
    await tester.ensureVisible(find.text('Create QR code'));
    await tester.tap(find.text('Create QR code'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(
      tester.getSize(find.byType(QrImageView)).width,
      lessThanOrEqualTo(232),
    );
    final capture = Platform.environment['KWIKPAY_SCREEN_CAPTURE'];
    if (capture != null) {
      final boundary = tester.renderObject<RenderRepaintBoundary>(
        find.byKey(const Key('customer-screen')),
      );
      await tester.runAsync(() async {
        final image = await boundary.toImage(pixelRatio: 2);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        await File(capture).writeAsBytes(bytes!.buffer.asUint8List());
        image.dispose();
      });
    }
  });
}
