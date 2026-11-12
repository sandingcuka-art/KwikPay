import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kwikpay_customer/payment_status.dart';

void main() {
  final full = <String, dynamic>{
    'status': 'PROCESSING',
    'paymentStatus': 'PROCESSING',
    'legs': [
      {
        'label': 'Business income',
        'amount': '240',
        'status': 'PROCESSING',
        'openPayments': {'sent': '240', 'received': '240'},
      },
      {
        'label': 'Stock reserve',
        'amount': '60',
        'status': 'PROCESSING',
        'openPayments': {'sent': '60', 'received': '60'},
      },
    ],
  };

  testWidgets('shows provider evidence separately from unverified settlement', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: PaymentStatusPanel(payment: full)),
        ),
      ),
    );
    expect(find.text('Transfer amounts recorded'), findsOneWidget);
    expect(find.text('Business income'), findsOneWidget);
    expect(find.text('Stock reserve'), findsOneWidget);
    expect(find.text('R2.40'), findsNWidgets(2));
    expect(find.text('R0.60'), findsNWidgets(2));
    expect(find.text('Wallet settlement not verified'), findsOneWidget);
    expect(find.textContaining('completed', findRichText: true), findsNothing);
  });

  testWidgets('does not infer missing evidence and highlights failure', (
    tester,
  ) async {
    final incomplete = <String, dynamic>{
      'status': 'PROCESSING',
      'paymentStatus': 'FAILED',
      'legs': [
        {
          'label': 'Business income',
          'amount': '240',
          'status': 'FAILED',
          'openPayments': null,
        },
        {
          'label': 'Stock reserve',
          'amount': '60',
          'status': 'PROCESSING',
          'openPayments': {'sent': '60', 'received': null},
        },
      ],
    };
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: PaymentStatusPanel(payment: incomplete),
          ),
        ),
      ),
    );
    expect(find.text('Payment needs attention'), findsOneWidget);
    expect(find.text('Needs attention'), findsOneWidget);
    expect(find.text('Not available'), findsNWidgets(3));
    expect(find.text('Transfer amounts recorded'), findsNothing);
  });

  test('does not hide an expired request behind an older payment status', () {
    expect(
      paymentHeading({
        'status': 'EXPIRED',
        'paymentStatus': 'AWAITING_CONSENT',
      }),
      'Payment request expired',
    );
    expect(paymentHeading({'status': 'PREPARING', 'paymentStatus': 'CREATED'}), 'Preparing your payment');
  });
}
