import 'package:flutter/material.dart';

BigInt? _minor(dynamic value) =>
    value is String && RegExp(r'^\d+$').hasMatch(value)
    ? BigInt.tryParse(value)
    : null;

String _amount(dynamic value) {
  final amount = _minor(value);
  if (amount == null) return 'Not available';
  return 'R${amount ~/ BigInt.from(100)}.${(amount % BigInt.from(100)).toString().padLeft(2, '0')}';
}

bool _reported(dynamic leg) {
  if (leg is! Map || leg['status'] == 'FAILED') return false;
  final values = leg['openPayments'];
  if (values is! Map) return false;
  final sent = _minor(values['sent']);
  final received = _minor(values['received']);
  final expected = _minor(leg['amount']);
  return sent != null &&
      sent > BigInt.zero &&
      received != null &&
      expected != null &&
      expected > BigInt.zero &&
      received == expected;
}

String paymentHeading(Map<String, dynamic>? payment) {
  if (payment?['status'] == 'EXPIRED') return 'Payment request expired';
  if (payment?['status'] == 'PREPARATION_FAILED') {
    return 'Payment needs attention';
  }
  if (payment?['status'] == 'AWAITING_CONSENT') {
    return 'Waiting for wallet approval';
  }
  if (payment?['status'] == 'PREPARING') return 'Preparing your payment';
  final state = payment?['paymentStatus'] ?? payment?['status'];
  if (state == 'FAILED' || state == 'PREPARATION_FAILED' || state == 'PARTIAL') {
    return 'Payment needs attention';
  }
  if (state == 'EXPIRED') return 'Payment request expired';
  if (state == 'AWAITING_CONSENT') return 'Waiting for wallet approval';
  if (state == 'PREPARING') return 'Preparing your payment';
  if (state == 'AWAITING_CUSTOMER') return 'Waiting for the customer';
  final legs = payment?['legs'];
  if (legs is List && legs.length == 2 && legs.every(_reported)) {
    return 'Transfer amounts recorded';
  }
  return 'Checking payment details';
}

class PaymentStatusPanel extends StatelessWidget {
  const PaymentStatusPanel({super.key, required this.payment});
  final Map<String, dynamic>? payment;

  @override
  Widget build(BuildContext context) {
    final requestState = payment?['status'];
    final state =
        requestState == 'EXPIRED' || requestState == 'PREPARATION_FAILED'
        ? requestState
        : payment?['paymentStatus'] ?? requestState;
    final legs = payment?['legs'];
    final checkingSettlement =
        state == 'PROCESSING' ||
        state == 'COMPLETED' ||
        state == 'PARTIAL' ||
        state == 'FAILED';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(
          liveRegion: true,
          child: Text(
            paymentHeading(payment),
            style: const TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w800,
              color: Color(0xff10233b),
            ),
          ),
        ),
        if (legs is List && checkingSettlement) ...[
          const SizedBox(height: 8),
          const Text(
            'Amounts reported by Open Payments',
            style: TextStyle(color: Color(0xff53657b), height: 1.4),
          ),
          const SizedBox(height: 14),
          for (final leg in legs)
            if (leg is Map)
              Container(
                width: double.infinity,
                margin: const EdgeInsets.only(bottom: 10),
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: const Color(0xffdce6f0)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      leg['label'] is String
                          ? leg['label'] as String
                          : 'Payment leg',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w800,
                        color: Color(0xff10233b),
                      ),
                    ),
                    if (leg['status'] == 'FAILED')
                      const Padding(
                        padding: EdgeInsets.only(top: 6),
                        child: Text(
                          'Needs attention',
                          style: TextStyle(
                            color: Color(0xffa93333),
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 24,
                      runSpacing: 8,
                      children: [
                        _Evidence(
                          label: 'Sent',
                          value: leg['openPayments'] is Map
                              ? leg['openPayments']['sent']
                              : null,
                        ),
                        _Evidence(
                          label: 'Received',
                          value: leg['openPayments'] is Map
                              ? leg['openPayments']['received']
                              : null,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
        ],
        if (checkingSettlement) ...[
          const SizedBox(height: 8),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xfffff7e8),
              borderRadius: BorderRadius.circular(14),
            ),
            child: const Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Wallet settlement not verified',
                  style: TextStyle(
                    color: Color(0xff704b0c),
                    fontWeight: FontWeight.w800,
                  ),
                ),
                SizedBox(height: 5),
                Text(
                  'Check the wallet before repeating this payment.',
                  style: TextStyle(color: Color(0xff704b0c), height: 1.4),
                ),
              ],
            ),
          ),
        ] else if (state == 'PREPARATION_FAILED' || state == 'EXPIRED') ...[
          const SizedBox(height: 8),
          const Text(
            'Check the existing request with the merchant before starting another.',
            style: TextStyle(color: Color(0xff53657b), height: 1.4),
          ),
        ],
      ],
    );
  }
}

class _Evidence extends StatelessWidget {
  const _Evidence({required this.label, required this.value});
  final String label;
  final dynamic value;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(
        label,
        style: const TextStyle(color: Color(0xff53657b), fontSize: 13),
      ),
      const SizedBox(height: 2),
      Text(
        _amount(value),
        style: const TextStyle(
          color: Color(0xff10233b),
          fontWeight: FontWeight.w700,
        ),
      ),
    ],
  );
}
