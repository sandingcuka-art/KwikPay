import 'package:flutter_test/flutter_test.dart';
import 'package:kwikpay_merchant/checkout.dart';

void main() {
  test('history does not suggest old unapproved requests are still active', () {
    expect(
      transactionHistoryHeading({
        'source': 'test_wallet',
        'requestStatus': 'AWAITING_CONSENT',
        'status': 'AWAITING_CONSENT',
      }),
      'Approval not recorded',
    );
    expect(
      transactionHistoryHeading({
        'source': 'test_wallet',
        'requestStatus': 'PROCESSING',
        'status': 'PROCESSING',
      }),
      'Wallet settlement not verified',
    );
    expect(
      transactionHistoryHeading({
        'source': 'test_wallet',
        'requestStatus': 'PROCESSING',
        'status': 'FAILED',
      }),
      'Payment needs attention',
    );
  });
  test('converts rand to exact cents and rejects invalid sale amounts', () {
    expect(cents('3.00'), 300);
    expect(cents('10.00'), 1000);
    expect(cents('10.01'), 1001);
    expect(cents('0.05'), 5);
    expect(cents('1000'), 100000);
    for (final input in ['', '0.01', '3.001', '-1', '1000.01', 'NaN']) {
      expect(cents(input), isNull, reason: input);
    }
  });
}
