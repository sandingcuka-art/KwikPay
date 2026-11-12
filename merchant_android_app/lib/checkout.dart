import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'payment_status.dart';

const _origin = String.fromEnvironment(
  'KWIKPAY_API_ORIGIN',
  defaultValue: 'http://127.0.0.1:8060',
);
const _testWallet = bool.fromEnvironment('KWIKPAY_TEST_WALLET');
const merchantAccess = MethodChannel('kwikpay/merchant_access');
const _requestsPath = _testWallet
    ? '/api/mobile-test/requests'
    : '/api/mobile-demo/requests';
const _sales = MethodChannel('kwikpay/demo_sales');

String transactionHistoryHeading(Map<dynamic, dynamic> sale) {
  if (sale['source'] != 'test_wallet') return 'Demo confirmed';
  if (sale['requestStatus'] == 'AWAITING_CONSENT') {
    return 'Approval not recorded';
  }
  if (sale['requestStatus'] == 'PROCESSING' && sale['status'] == 'PROCESSING') {
    return 'Wallet settlement not verified';
  }
  return paymentHeading({
    'status': sale['requestStatus'],
    'paymentStatus': sale['status'],
  });
}

String historyPotLabel(Map<dynamic, dynamic> sale, int index) {
  final labels = sale['potLabels'];
  return labels is List && labels.length == 2 && labels[index] is String
      ? labels[index] as String
      : index == 0
      ? 'Business'
      : 'Stock';
}

class MerchantAccessRequired implements Exception {
  const MerchantAccessRequired();
}

class MerchantAccessPage extends StatefulWidget {
  const MerchantAccessPage({super.key});
  @override
  State<MerchantAccessPage> createState() => _MerchantAccessPageState();
}

class _MerchantAccessPageState extends State<MerchantAccessPage> {
  final _form = GlobalKey<FormState>();
  final _key = TextEditingController();
  bool _configured = false;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final configured =
          await merchantAccess.invokeMethod<bool>('configured') ?? false;
      if (mounted) {
        setState(() {
          _configured = configured;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _error = 'Could not load merchant access settings.';
          _loading = false;
        });
      }
    }
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await merchantAccess.invokeMethod<void>('save', _key.text.trim());
      _key.clear();
      if (mounted) {
        setState(() {
          _configured = true;
          _loading = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Merchant access saved on this device.'),
          ),
        );
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _error = 'Could not save merchant access. Please try again.';
          _loading = false;
        });
      }
    }
  }

  Future<void> _paste() async {
    try {
      final text = (await Clipboard.getData(Clipboard.kTextPlain))?.text;
      if (!mounted) return;
      if (text == null || text.trim().isEmpty) {
        setState(() => _error = 'Copy the merchant access key first.');
        return;
      }
      _key.text = text.trim();
      setState(() => _error = null);
    } catch (_) {
      if (mounted) setState(() => _error = 'Could not read the clipboard.');
    }
  }

  Future<void> _clear() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await merchantAccess.invokeMethod<void>('clear');
      if (mounted) {
        setState(() {
          _configured = false;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _error = 'Could not clear merchant access.';
          _loading = false;
        });
      }
    }
  }

  @override
  void dispose() {
    _key.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Merchant access')),
    body: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _form,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Connect this device',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 12),
                const Text(
                  'Enter the merchant access key shared securely by your team. It is encrypted on this device.',
                  style: TextStyle(height: 1.5),
                ),
                const SizedBox(height: 20),
                if (_configured)
                  const Text('Merchant access is saved on this device.'),
                const SizedBox(height: 12),
                TextFormField(
                  key: const Key('merchant-access-key'),
                  controller: _key,
                  obscureText: true,
                  autocorrect: false,
                  enableSuggestions: false,
                  decoration: InputDecoration(
                    labelText: 'Merchant access key',
                    border: const OutlineInputBorder(),
                    suffixIcon: TextButton(
                      onPressed: _loading ? null : _paste,
                      child: const Text('Paste'),
                    ),
                  ),
                  validator: (value) =>
                      value == null ||
                          !RegExp(r'^[!-~]{1,256}$').hasMatch(value.trim())
                      ? 'Enter the merchant access key.'
                      : null,
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: const TextStyle(color: Colors.red)),
                ],
                const SizedBox(height: 20),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _loading ? null : _save,
                    child: Text(_loading ? 'Please wait…' : 'Save access'),
                  ),
                ),
                if (_configured)
                  TextButton(
                    onPressed: _loading ? null : _clear,
                    child: const Text('Clear access'),
                  ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

class DemoHistoryPage extends StatefulWidget {
  const DemoHistoryPage({super.key});
  @override
  State<DemoHistoryPage> createState() => _DemoHistoryPageState();
}

class _DemoHistoryPageState extends State<DemoHistoryPage> {
  late final Future<List<dynamic>> sales = _load();
  Future<List<dynamic>> _load() async => _testWallet
      ? (await _request('GET', '/api/mobile-test/history'))['items']
            as List<dynamic>
      : jsonDecode(await _sales.invokeMethod<String>('list') ?? '[]')
            as List<dynamic>;
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text(
        _testWallet ? 'Transaction history' : 'Demo transaction history',
      ),
    ),
    body: FutureBuilder<List<dynamic>>(
      future: sales,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Center(
            child: Text(
              snapshot.error is MerchantAccessRequired
                  ? 'Set your merchant access key on the home screen.'
                  : 'Could not load transaction history.',
            ),
          );
        }
        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.data!.isEmpty) {
          return const Center(
            child: Text(
              _testWallet
                  ? 'No Test Wallet transactions saved yet.'
                  : 'No confirmed demo transactions yet.',
            ),
          );
        }
        return ListView(
          children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text(
                _testWallet
                    ? 'Saved Test Wallet requests. Wallet settlement remains unverified.'
                    : 'Records saved on this device. Check each status.',
              ),
            ),
            for (final sale in snapshot.data!)
              ListTile(
                leading: const Icon(Icons.receipt_long),
                title: Text(
                  '${money(sale['amount'] as String)} · ${transactionHistoryHeading(sale as Map)}',
                ),
                subtitle: Text(
                  '${sale['source'] == 'test_wallet' ? 'Planned: ' : ''}${historyPotLabel(sale, 0)} ${money(sale['business'] as String)} · ${historyPotLabel(sale, 1)} ${money(sale['stock'] as String)}\n${DateTime.parse(sale['confirmedAt'] as String).toLocal().toString().substring(0, 16)}',
                ),
                isThreeLine: true,
              ),
          ],
        );
      },
    ),
  );
}

int? cents(String input) {
  final match = RegExp(r'^(\d{1,4})(?:\.(\d{1,2}))?$').firstMatch(input.trim());
  if (match == null) return null;
  final value =
      int.parse(match[1]!) * 100 + int.parse((match[2] ?? '').padRight(2, '0'));
  return value >= 2 && value <= 100000 ? value : null;
}

String money(String cents) {
  final n = int.parse(cents);
  return 'R${n ~/ 100}.${(n % 100).toString().padLeft(2, '0')}';
}

String evidence(dynamic value) =>
    value is String && RegExp(r'^\d+$').hasMatch(value)
    ? money(value)
    : 'unverified';

Future<Map<String, dynamic>> _request(
  String method,
  String path, [
  Map<String, dynamic>? body,
]) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 5);
  try {
    final request = await client.openUrl(method, Uri.parse('$_origin$path'));
    request.followRedirects = false;
    if (_testWallet &&
        ((method == 'POST' && path == _requestsPath) ||
            path == '/api/mobile-test/history' ||
            path == '/api/mobile-test/config')) {
      final key = await merchantAccess.invokeMethod<String>('load');
      if (key == null || key.isEmpty) throw const MerchantAccessRequired();
      request.headers.set('X-KwikPay-Merchant-Key', key);
    }
    if (body != null) {
      request.headers.contentType = ContentType.json;
      final bytes = utf8.encode(jsonEncode(body));
      request.contentLength = bytes.length;
      request.add(bytes);
    }
    final response = await request.close().timeout(const Duration(seconds: 8));
    final text = await response.transform(utf8.decoder).join();
    final data = jsonDecode(text) as Map<String, dynamic>;
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(data['detail'] ?? 'Request unavailable.');
    }
    return data;
  } finally {
    client.close(force: true);
  }
}

class MerchantCheckoutPage extends StatefulWidget {
  const MerchantCheckoutPage({super.key});
  @override
  State<MerchantCheckoutPage> createState() => _MerchantCheckoutPageState();
}

class _MerchantCheckoutPageState extends State<MerchantCheckoutPage> {
  final amount = TextEditingController(text: '3.00');
  Map<String, dynamic>? request;
  String? error;
  bool busy = false;
  Timer? timer;
  bool recording = false;
  bool recorded = false;
  bool loadingConfig = _testWallet;
  Map<String, dynamic>? config;

  @override
  void initState() {
    super.initState();
    if (_testWallet) loadConfig();
  }

  Future<void> loadConfig() async {
    setState(() {
      loadingConfig = true;
      error = null;
    });
    try {
      final result = await _request('GET', '/api/mobile-test/config');
      if (result['pots'] is! List || (result['pots'] as List).length != 2) {
        throw const FormatException('Invalid split settings');
      }
      if (mounted) setState(() => config = result);
    } catch (exception) {
      if (mounted) {
        setState(() {
          config = null;
          error = exception is MerchantAccessRequired
              ? 'Set your merchant access key on the home screen.'
              : 'Could not load the saved split. Check your connection and try again.';
        });
      }
    } finally {
      if (mounted) setState(() => loadingConfig = false);
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    amount.dispose();
    super.dispose();
  }

  Future<void> createRequest() async {
    final value = cents(amount.text);
    if (value == null) {
      setState(
        () => error =
            'Enter an amount from R0.02 to R1000.00, with at most two decimals.',
      );
      return;
    }
    if (_testWallet && value > 1000) {
      setState(() => error = 'This Test Wallet trial is limited to R10.00.');
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await _request('POST', _requestsPath, {
        'amount': '$value',
      });
      if (result['amount'] != '$value' ||
          result['currency'] != 'ZAR' ||
          result['status'] != 'AWAITING_CUSTOMER') {
        throw const FormatException('Unexpected request details');
      }
      final uri = Uri.tryParse(result['checkoutUrl'] as String? ?? '');
      final origin = Uri.parse(_origin);
      if (uri == null ||
          uri.scheme != origin.scheme ||
          uri.host != origin.host ||
          uri.port != origin.port ||
          !RegExp(
            _testWallet
                ? r'^/api/mobile-test/requests/[A-Za-z0-9_-]{32}$'
                : r'^/api/mobile-demo/requests/[A-Za-z0-9_-]{32}$',
          ).hasMatch(uri.path) ||
          uri.hasQuery ||
          uri.hasFragment ||
          uri.userInfo.isNotEmpty) {
        throw const FormatException('Invalid demo request URL');
      }
      if (!mounted) return;
      setState(() => request = result);
      timer?.cancel();
      timer = Timer.periodic(const Duration(seconds: 3), (_) => poll(uri.path));
    } catch (_) {
      if (mounted) {
        setState(
          () => error =
              'Could not create a request. Check your connection and try again.',
        );
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> poll(String path) async {
    try {
      final result = await _request('GET', path);
      if (mounted && request?['checkoutUrl'] == '$_origin$path') {
        setState(() {
          request = {...request!, ...result};
          error = null;
        });
        if (result['status'] == 'DEMO_CONFIRMED' && !recorded && !recording) {
          recording = true;
          try {
            final pots = result['pots'] as List;
            await _sales.invokeMethod<void>(
              'add',
              jsonEncode({
                'amount': result['amount'],
                'business': pots[0]['amount'],
                'stock': pots[1]['amount'],
                'confirmedAt': result['confirmedAt'],
              }),
            );
            recorded = true;
            timer?.cancel();
          } catch (_) {
            if (mounted) {
              setState(
                () => error =
                    'Confirmed, but demo history could not be saved. Retrying…',
              );
            }
          } finally {
            recording = false;
          }
        }
        if (_testWallet &&
            result['status'] == 'PROCESSING' &&
            !recording &&
            result['executionId'] is String) {
          recording = true;
          try {
            final pots = result['pots'] as List;
            await _sales.invokeMethod<void>(
              'add',
              jsonEncode({
                'id': result['executionId'],
                'source': 'test_wallet',
                'status': result['paymentStatus'] ?? 'PROCESSING',
                'amount': result['amount'],
                'business': pots[0]['amount'],
                'stock': pots[1]['amount'],
                'confirmedAt': DateTime.now().toUtc().toIso8601String(),
              }),
            );
          } catch (_) {
            if (mounted) {
              setState(
                () => error =
                    'Payment status received, but local history could not be saved.',
              );
            }
          } finally {
            recording = false;
          }
        }
      }
    } catch (_) {
      if (mounted && request?['checkoutUrl'] == '$_origin$path') {
        setState(
          () => error =
              'Status unavailable. Check this payment in your wallet before starting another.',
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final item = request;
    return Scaffold(
      appBar: AppBar(title: const Text('New payment request')),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    _testWallet
                        ? 'TEST WALLET · UP TO R10'
                        : 'DEMO · NO PAYMENT',
                    style: TextStyle(
                      color: Color(0xff53657b),
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1.2,
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    item == null
                        ? 'Create a sale'
                        : _testWallet && item['status'] != 'AWAITING_CUSTOMER'
                        ? 'Payment update'
                        : 'Customer scans this code',
                    style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                      fontWeight: FontWeight.w800,
                      color: const Color(0xff10233b),
                    ),
                  ),
                  const SizedBox(height: 12),
                  if (item == null ||
                      !_testWallet ||
                      item['status'] == 'AWAITING_CUSTOMER')
                    Text(
                      item == null
                          ? (_testWallet
                                ? 'Enter the sale amount. The API applies your saved split.'
                                : 'Enter the sale amount. The demo uses the 80/20 pot split.')
                          : 'Ask the customer to scan with the KwikPay Customer app. The request expires after five minutes.',
                      style: const TextStyle(
                        color: Color(0xff53657b),
                        fontSize: 16,
                        height: 1.45,
                      ),
                    ),
                  const SizedBox(height: 24),
                  if (item == null) ...[
                    if (_testWallet) ...[
                      if (loadingConfig)
                        const Text('Loading saved split…')
                      else if (config != null) ...[
                        const Text(
                          'Saved split',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                        for (final pot in config!['pots'] as List)
                          Text('${pot['label']} · ${pot['percentage']}%'),
                      ] else
                        TextButton(
                          onPressed: loadConfig,
                          child: const Text('Retry split settings'),
                        ),
                      const SizedBox(height: 18),
                    ],
                    TextField(
                      controller: amount,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      decoration: const InputDecoration(
                        labelText: 'Sale amount (ZAR)',
                        prefixText: 'R ',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 18),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed:
                            busy ||
                                (_testWallet &&
                                    (loadingConfig || config == null))
                            ? null
                            : createRequest,
                        child: Text(busy ? 'Creating…' : 'Create request QR'),
                      ),
                    ),
                  ] else ...[
                    if (!_testWallet || item['status'] == 'AWAITING_CUSTOMER')
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Column(
                          children: [
                            Text(
                              money(item['amount'] as String),
                              style: const TextStyle(
                                fontSize: 28,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            if (_testWallet && item['pots'] is List)
                              for (final pot in item['pots'] as List)
                                Text(
                                  '${pot['label']} · ${pot['percentage']}% · ${money(pot['amount'] as String)}',
                                ),
                            const SizedBox(height: 8),
                            LayoutBuilder(
                              builder: (context, constraints) => QrImageView(
                                data: item['checkoutUrl'] as String,
                                size: constraints.maxWidth < 250
                                    ? constraints.maxWidth
                                    : 250,
                                backgroundColor: Colors.white,
                                padding: const EdgeInsets.all(28),
                              ),
                            ),
                            Text(
                              _testWallet
                                  ? paymentHeading(item)
                                  : item['status'] == 'DEMO_CONFIRMED'
                                  ? 'Demo confirmed · no payment sent'
                                  : item['status'] == 'CUSTOMER_REVIEWING'
                                  ? 'Customer is reviewing'
                                  : 'Waiting for customer',
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                                color: Color(0xff315d99),
                              ),
                            ),
                          ],
                        ),
                      ),
                    if (_testWallet &&
                        item['status'] != 'AWAITING_CUSTOMER') ...[
                      Text(
                        '${money(item['amount'] as String)} sale',
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 20),
                      PaymentStatusPanel(payment: item),
                    ] else ...[
                      const SizedBox(height: 14),
                      Text(
                        _testWallet
                            ? 'Waiting for the customer to scan and review.'
                            : 'Wallet approval and transfers are not connected. No money is moved.',
                        style: const TextStyle(
                          color: Color(0xff53657b),
                          height: 1.4,
                        ),
                      ),
                    ],
                    const SizedBox(height: 16),
                    OutlinedButton(
                      onPressed: () {
                        timer?.cancel();
                        setState(() {
                          request = null;
                          error = null;
                          recorded = false;
                        });
                      },
                      child: const Text('Start another request'),
                    ),
                  ],
                  if (error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 16),
                      child: Text(
                        error!,
                        style: const TextStyle(color: Color(0xffa93333)),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
