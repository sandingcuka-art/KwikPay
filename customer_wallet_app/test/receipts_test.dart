import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kwikpay_customer/receipts.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('kwikpay/receipts');
  final payment = <String, dynamic>{
    'executionId': 'exec_1',
    'merchant': 'Demo shop',
    'amount': '300',
    'status': 'PROCESSING',
    'interactUrl': 'secret-url',
    'legs': [
      {
        'label': 'Business',
        'amount': '240',
        'status': 'PROCESSING',
        'walletStatus': 'UNVERIFIED',
        'openPayments': {'sent': '240', 'received': '240', 'token': 'secret'},
      },
    ],
  };

  test('only saves receipt data, never authorization URLs or tokens', () async {
    String? saved;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          saved = (call.arguments as Map)['receipt'] as String;
          return null;
        });
    await saveReceipt(payment, '2026-11-03 09:00');
    expect(saved, isNot(contains('secret')));
    expect(jsonDecode(saved!)['legs'][0]['openPayments']['received'], '240');
    expect(receiptSnapshot({'amount': '300'}, 'now'), isNull);
  });

  test('refreshes matching records and refuses mismatched payments', () async {
    final path = '/api/mobile-test/requests/${'a' * 32}';
    final stored = {
      ...receiptSnapshot(payment, '2026-11-03 09:00')!,
      'requestPath': path,
    };
    final saves = <Map>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          if (call.method == 'list') return jsonEncode([stored]);
          saves.add(call.arguments as Map);
          return null;
        });
    expect(
      await refreshReceipts(
        fetch: (requested) async {
          expect(requested, path);
          return payment;
        },
      ),
      isTrue,
    );
    expect(saves, hasLength(1));
    expect(saves.single['path'], path);
    expect(
      await refreshReceipts(
        fetch: (_) async => {...payment, 'executionId': 'different'},
      ),
      isFalse,
    );
    expect(saves, hasLength(1));
  });

  testWidgets('shows device receipt and unverified settlement', (tester) async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          channel,
          (call) async =>
              jsonEncode([receiptSnapshot(payment, '2026-11-03 09:00')]),
        );
    await tester.pumpWidget(const MaterialApp(home: ReceiptHistoryPage()));
    await tester.pumpAndSettle();
    expect(find.text('Demo shop'), findsOneWidget);
    expect(find.text('R3.00'), findsOneWidget);
    await tester.tap(find.text('Demo shop'));
    await tester.pumpAndSettle();
    expect(find.text('Wallet settlement not verified'), findsOneWidget);
  });
}
