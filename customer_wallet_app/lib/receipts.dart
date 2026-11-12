import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'payment_status.dart';

const _storage = MethodChannel('kwikpay/receipts');
const _origin = String.fromEnvironment(
  'KWIKPAY_API_ORIGIN',
  defaultValue: 'http://127.0.0.1:8060',
);
final _requestPath = RegExp(r'^/api/mobile-test/requests/[A-Za-z0-9_-]{32}$');
bool _refreshing = false;

Map<String, dynamic>? receiptSnapshot(
  Map<String, dynamic> payment,
  String createdAt,
) {
  if (payment['executionId'] is! String || payment['amount'] is! String) {
    return null;
  }
  final legs = payment['legs'];
  return {
    'executionId': payment['executionId'],
    'createdAt': createdAt,
    'merchant': payment['merchant'] is String
        ? payment['merchant']
        : 'Merchant',
    'amount': payment['amount'],
    'status': payment['status'],
    'paymentStatus': payment['paymentStatus'],
    if (legs is List)
      'legs': [
        for (final leg in legs)
          if (leg is Map)
            {
              'label': leg['label'],
              'amount': leg['amount'],
              'status': leg['status'],
              'walletStatus': leg['walletStatus'],
              if (leg['openPayments'] is Map)
                'openPayments': {
                  'sent': leg['openPayments']['sent'],
                  'received': leg['openPayments']['received'],
                },
            },
      ],
  };
}

Future<void> saveReceipt(
  Map<String, dynamic> payment,
  String createdAt, {
  String? path,
}) async {
  final receipt = receiptSnapshot(payment, createdAt);
  if (receipt != null) {
    if (path != null && !_requestPath.hasMatch(path)) {
      throw const FormatException('Invalid receipt reference');
    }
    await _storage.invokeMethod<void>('save', {
      'receipt': jsonEncode(receipt),
      'path': path,
    });
  }
}

Future<List<dynamic>> loadReceipts() async =>
    jsonDecode((await _storage.invokeMethod<String>('list')) ?? '[]')
        as List<dynamic>;

// Refresh only saved read references; a lookup never creates or retries a payment.
Future<Map<String, dynamic>> _fetchStatus(String path) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 5);
  try {
    final request = await client.getUrl(Uri.parse('$_origin$path'));
    request.followRedirects = false;
    final response = await request.close().timeout(const Duration(seconds: 8));
    if (response.statusCode != 200) {
      throw const FormatException('Status unavailable');
    }
    final body = await response
        .transform(utf8.decoder)
        .join()
        .timeout(const Duration(seconds: 8));
    return jsonDecode(body) as Map<String, dynamic>;
  } finally {
    client.close(force: true);
  }
}

Future<bool> refreshReceipts({
  Future<Map<String, dynamic>> Function(String)? fetch,
}) async {
  if (_refreshing) return true;
  _refreshing = true;
  var success = true;
  try {
    final items = await loadReceipts();
    for (var start = 0; start < items.length; start += 5) {
      final batch = items.skip(start).take(5);
      await Future.wait(
        batch.map((item) async {
          if (item is! Map<String, dynamic>) return;
          final path = item['requestPath'];
          if (path is! String || !_requestPath.hasMatch(path)) return;
          try {
            final result = await (fetch ?? _fetchStatus)(path);
            if (result['executionId'] != item['executionId'] ||
                result['amount'] != item['amount']) {
              throw const FormatException('Receipt does not match');
            }
            await saveReceipt(result, item['createdAt'] as String, path: path);
          } catch (_) {
            success = false;
          }
        }),
      );
    }
    return success;
  } finally {
    _refreshing = false;
  }
}

class ReceiptHistoryPage extends StatefulWidget {
  const ReceiptHistoryPage({super.key});
  @override
  State<ReceiptHistoryPage> createState() => _ReceiptHistoryPageState();
}

class _ReceiptHistoryPageState extends State<ReceiptHistoryPage> {
  List<dynamic>? receipts;
  String? error;
  Timer? timer;
  bool working = false;

  @override
  void initState() {
    super.initState();
    update();
    timer = Timer.periodic(const Duration(seconds: 8), (_) => update());
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> update() async {
    if (working) return;
    working = true;
    try {
      final ok = await refreshReceipts();
      final items = await loadReceipts();
      if (mounted) {
        setState(() {
          receipts = items;
          error = ok
              ? null
              : 'Some statuses could not be refreshed. Showing the last saved information.';
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() => error = 'Could not load receipts on this device.');
      }
    } finally {
      working = false;
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Payment history')),
    body: receipts == null
        ? Center(
            child: error == null
                ? const CircularProgressIndicator()
                : Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(error!),
                      TextButton(
                        onPressed: update,
                        child: const Text('Try again'),
                      ),
                    ],
                  ),
          )
        : receipts!.isEmpty
        ? const Center(
            child: Padding(
              padding: EdgeInsets.all(32),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.receipt_long_outlined,
                    size: 48,
                    color: Color(0xff1769ff),
                  ),
                  SizedBox(height: 20),
                  Text(
                    'Your receipts live here',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.w800,
                      color: Color(0xff10233b),
                    ),
                  ),
                  SizedBox(height: 10),
                  Text(
                    'No receipts yet. Your future KwikPay payments will appear here.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Color(0xff53657b), height: 1.5),
                  ),
                ],
              ),
            ),
          )
        : ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text(
                error ??
                    'Saved on this device. Open Payments status refreshes while this screen is open. Older receipts may not refresh.',
                style: const TextStyle(color: Color(0xff53657b)),
              ),
              const SizedBox(height: 16),
              for (final item in receipts!)
                if (item is Map<String, dynamic>)
                  Card(
                    color: Colors.white,
                    elevation: 0,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: ExpansionTile(
                      title: Text(
                        item['merchant'] as String? ?? 'Merchant',
                        style: const TextStyle(
                          fontWeight: FontWeight.w800,
                          color: Color(0xff10233b),
                        ),
                      ),
                      subtitle: Text(
                        '${item['createdAt'] ?? ''}\n${paymentHeading(item)}${item['paymentStatus'] == 'PROCESSING' ? '\nWallet settlement unverified' : ''}${item['requestPath'] == null ? '\nSaved status; refresh unavailable' : ''}',
                        style: const TextStyle(
                          color: Color(0xff53657b),
                          height: 1.5,
                        ),
                      ),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            _amount(item['amount']),
                            style: const TextStyle(
                              fontWeight: FontWeight.bold,
                              fontSize: 18,
                            ),
                          ),
                          const SizedBox(width: 4),
                          const Icon(
                            Icons.expand_more,
                            color: Color(0xff53657b),
                          ),
                        ],
                      ),
                      children: [
                        Padding(
                          padding: const EdgeInsets.all(16),
                          child: PaymentStatusPanel(payment: item),
                        ),
                      ],
                    ),
                  ),
            ],
          ),
  );
}

String _amount(dynamic value) {
  if (value is! String || !RegExp(r'^\d{1,9}$').hasMatch(value)) return '—';
  final cents = int.parse(value);
  return 'R${cents ~/ 100}.${(cents % 100).toString().padLeft(2, '0')}';
}
