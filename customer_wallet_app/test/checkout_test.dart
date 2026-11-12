import 'package:flutter_test/flutter_test.dart';
import 'package:kwikpay_customer/checkout.dart';

void main() {
  const testWallet = bool.fromEnvironment('KWIKPAY_TEST_WALLET');
  test('formats provider evidence without claiming missing amounts', () {
    expect(evidence('240'), 'R2.40');
    expect(evidence(null), 'unverified');
  });
  test('accepts only configured demo QR URLs', () {
    const origin = String.fromEnvironment(
      'KWIKPAY_API_ORIGIN',
      defaultValue: 'http://127.0.0.1:8060',
    );
    final token = 'a' * 32;
    final path =
        '/api/${testWallet ? 'mobile-test' : 'mobile-demo'}/requests/$token';
    expect(demoPath('$origin$path'), path);
    for (final input in [
      'https://evil.example$path',
      '$origin$path?x=1',
      'http://localhost:8060$path',
      '$origin/other',
    ]) {
      expect(demoPath(input), isNull);
    }
  });
  test('limits wallet authorization to the selected sale and R10', () {
    expect(validTestWalletDebit('1000', '1000'), isTrue);
    expect(validTestWalletDebit('999', '1000'), isTrue);
    for (final pair in [
      ['1001', '1000'],
      ['1000', '999'],
      ['0', '300'],
      ['-1', '300'],
      ['300', '1001'],
      ['3.00', '300'],
    ]) {
      expect(validTestWalletDebit(pair[0], pair[1]), isFalse, reason: '$pair');
    }
  });
  test('rejects inconsistent request amounts and claimed requests', () {
    final data = <String, dynamic>{
      'merchant': 'Demo shop',
      'amount': '300',
      'currency': 'ZAR',
      'status': 'AWAITING_CUSTOMER',
      'pots': [
        {
          'label': 'Business',
          'percentage': 80,
          'amount': '240',
          'walletAddress': 'https://ilp.interledger-test.dev/kwikpay-merch-2',
        },
        {
          'label': 'Stock',
          'percentage': 20,
          'amount': '60',
          'walletAddress': 'https://ilp.interledger-test.dev/kwikpay-merch-3',
        },
      ],
    };
    expect(validDetails(data), isTrue);
    if (testWallet) {
      final maxSale = {
        ...data,
        'amount': '1000',
        'pots': [
          {
            ...(data['pots'] as List)[0] as Map<String, dynamic>,
            'amount': '800',
          },
          {
            ...(data['pots'] as List)[1] as Map<String, dynamic>,
            'amount': '200',
          },
        ],
      };
      expect(validDetails(maxSale), isTrue);
      expect(validDetails({...maxSale, 'amount': '1001'}), isFalse);
    }
    expect(validDetails({...data, 'amount': '301'}), isFalse);
    expect(validDetails({...data, 'status': 'CUSTOMER_REVIEWING'}), isFalse);
    if (testWallet) {
      final changed = {
        ...data,
        'pots': [
          {
            'label': 'Operating',
            'percentage': 60,
            'amount': '180',
            'walletAddress': 'https://ilp.interledger-test.dev/kwikpay-merch-1',
          },
          {
            'label': 'Stock',
            'percentage': 40,
            'amount': '120',
            'walletAddress': 'https://ilp.interledger-test.dev/kwikpay-merch-3',
          },
        ],
      };
      expect(validDetails(changed), isTrue);
      expect(
        validDetails({
          ...changed,
          'pots': [
            {
              'label': 'Operating',
              'percentage': 60,
              'amount': '180',
              'walletAddress': 'https://evil.example/merchant',
            },
            {
              'label': 'Stock',
              'percentage': 40,
              'amount': '120',
              'walletAddress':
                  'https://ilp.interledger-test.dev/kwikpay-merch-3',
            },
          ],
        }),
        isFalse,
      );
    }
  });
}
