import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kwikpay_merchant/checkout.dart';

void main() {
  testWidgets('shows saved demo sale and its split', (tester) async {
    const channel = MethodChannel('kwikpay/demo_sales');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async => jsonEncode([
          {'amount': '300', 'business': '240', 'stock': '60', 'confirmedAt': '2026-11-02T16:00:00Z'},
        ]));
    addTearDown(() => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(channel, null));
    await tester.pumpWidget(const MaterialApp(home: DemoHistoryPage()));
    await tester.pumpAndSettle();
    expect(find.text('R3.00 · Demo confirmed'), findsOneWidget);
    expect(find.textContaining('Business R2.40 · Stock R0.60'), findsOneWidget);
    expect(find.textContaining('Check each status'), findsOneWidget);
  });
}
