import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'payment_status.dart';
import 'receipts.dart';

const _origin = String.fromEnvironment(
  'KWIKPAY_API_ORIGIN',
  defaultValue: 'http://127.0.0.1:8060',
);
const _testWallet = bool.fromEnvironment('KWIKPAY_TEST_WALLET');
const _walletLauncher = MethodChannel('kwikpay/test_wallet');

String? demoPath(String raw) {
  final uri = Uri.tryParse(raw);
  final origin = Uri.parse(_origin);
  if (uri == null ||
      uri.scheme != origin.scheme ||
      uri.host != origin.host ||
      uri.port != origin.port ||
      uri.userInfo.isNotEmpty ||
      uri.hasQuery ||
      uri.hasFragment ||
      !RegExp(
        _testWallet
            ? r'^/api/mobile-test/requests/[A-Za-z0-9_-]{32}$'
            : r'^/api/mobile-demo/requests/[A-Za-z0-9_-]{32}$',
      ).hasMatch(uri.path)) {
    return null;
  }
  return uri.path;
}

String money(String value) {
  final n = int.parse(value);
  return 'R${n ~/ 100}.${(n % 100).toString().padLeft(2, '0')}';
}

String evidence(dynamic value) =>
    value is String && RegExp(r'^\d+$').hasMatch(value)
    ? money(value)
    : 'unverified';

bool validDetails(Map<String, dynamic> result) {
  final rawTotal = result['amount'];
  final total = rawTotal is String && RegExp(r'^\d{1,6}$').hasMatch(rawTotal)
      ? int.tryParse(rawTotal)
      : null;
  final pots = result['pots'];
  if (result['merchant'] is! String ||
      result['currency'] != 'ZAR' ||
      result['status'] != 'AWAITING_CUSTOMER' ||
      total == null ||
      total < 2 ||
      total > 100000 ||
      pots is! List ||
      pots.length != 2) {
    return false;
  }
  var sum = 0;
  var percentage = 0;
  if (_testWallet && total > 1000) {
    return false;
  }
  for (final pot in pots) {
    if (pot is! Map ||
        pot['label'] is! String ||
        pot['percentage'] is! int ||
        pot['amount'] is! String) {
      return false;
    }
    final value = int.tryParse(pot['amount'] as String);
    final percent = pot['percentage'] as int;
    if (value == null || value < 0 || percent < 0 || percent > 100) {
      return false;
    }
    if (_testWallet) {
      final address = pot['walletAddress'];
      final uri = address is String ? Uri.tryParse(address) : null;
      if (uri == null ||
          uri.scheme != 'https' ||
          uri.host != 'ilp.interledger-test.dev' ||
          uri.userInfo.isNotEmpty ||
          uri.hasPort ||
          uri.hasQuery ||
          uri.hasFragment ||
          uri.path.isEmpty ||
          uri.path == '/' ||
          value == 0 ||
          percent == 0) {
        return false;
      }
    }
    sum += value;
    percentage += percent;
  }
  return sum == total && percentage == 100;
}

bool validTestWalletDebit(dynamic debit, dynamic saleAmount) {
  if (debit is! String ||
      saleAmount is! String ||
      !RegExp(r'^\d{1,4}$').hasMatch(debit) ||
      !RegExp(r'^\d{1,4}$').hasMatch(saleAmount)) {
    return false;
  }
  final value = int.parse(debit);
  final sale = int.parse(saleAmount);
  return sale >= 2 && sale <= 1000 && value > 0 && value <= sale;
}

class RequestFailure implements Exception {
  const RequestFailure(this.status);
  final int status;
}

Future<Map<String, dynamic>> _request(
  String method,
  String path, [
  Map<String, dynamic>? body,
]) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 5);
  try {
    final req = await client.openUrl(method, Uri.parse('$_origin$path'));
    req.followRedirects = false;
    if (body != null) {
      req.headers.contentType = ContentType.json;
      final bytes = utf8.encode(jsonEncode(body));
      req.contentLength = bytes.length;
      req.add(bytes);
    }
    final response = await req.close().timeout(
      Duration(seconds: _testWallet && method == 'POST' ? 120 : 8),
    );
    final data =
        jsonDecode(await response.transform(utf8.decoder).join())
            as Map<String, dynamic>;
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw RequestFailure(response.statusCode);
    }
    return data;
  } finally {
    client.close(force: true);
  }
}

class CustomerCheckoutPage extends StatefulWidget {
  const CustomerCheckoutPage({
    super.key,
    required this.initialWallet,
    required this.validateWallet,
  });
  final String initialWallet;
  final String? Function(String) validateWallet;
  @override
  State<CustomerCheckoutPage> createState() => _CustomerCheckoutPageState();
}

class _CustomerCheckoutPageState extends State<CustomerCheckoutPage> {
  late final TextEditingController wallet;
  bool loading = false;
  bool shared = false;
  bool confirmed = false;
  bool attempted = false;
  Map<String, dynamic>? payment;
  Timer? statusTimer;
  bool invalid = false;
  int cameraAttempt = 0;
  String? path;
  String? blockedCode;
  String? error;
  Map<String, dynamic>? details;
  final receiptTime = DateTime.now().toLocal().toString().substring(0, 16);
  bool receiptErrorShown = false;

  Future<void> recordReceipt(Map<String, dynamic> result) async {
    try {
      await saveReceipt(result, receiptTime, path: path);
    } catch (_) {
      if (mounted && !receiptErrorShown) {
        receiptErrorShown = true;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Could not save this receipt on your device.'),
          ),
        );
      }
    }
  }

  @override
  void initState() {
    super.initState();
    wallet = TextEditingController(text: widget.initialWallet);
  }

  @override
  void dispose() {
    statusTimer?.cancel();
    wallet.dispose();
    super.dispose();
  }

  Future<void> scan(String raw) async {
    if (loading || details != null || raw == blockedCode) return;
    final nextPath = demoPath(raw);
    if (nextPath == null) {
      if (!invalid) setState(() => invalid = true);
      return;
    }
    setState(() {
      loading = true;
      invalid = false;
      error = null;
    });
    try {
      final result = await _request('GET', nextPath);
      if (!validDetails(result)) {
        throw const FormatException('Invalid or already claimed request');
      }
      if (!mounted) return;
      setState(() {
        path = nextPath;
        details = result;
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          blockedCode = raw;
          error =
              'Request unavailable or expired. Ask the merchant for a new code.';
        });
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> share() async {
    final address = widget.validateWallet(wallet.text);
    if (address == null) {
      setState(
        () => error = 'Enter a valid HTTPS wallet address or payment pointer.',
      );
      return;
    }
    setState(() {
      loading = true;
      error = null;
      if (_testWallet) attempted = true;
    });
    try {
      final result = await _request(
        'POST',
        '$path/${_testWallet ? 'prepare' : 'review'}',
        {'walletAddress': address},
      );
      if (mounted) {
        setState(() {
          shared = true;
          if (_testWallet) payment = result;
        });
      }
      if (_testWallet) {
        await recordReceipt(result);
        statusTimer?.cancel();
        statusTimer = Timer.periodic(
          const Duration(seconds: 8),
          (_) => refreshPayment(),
        );
      }
    } on RequestFailure catch (failure) {
      if (mounted) {
        setState(
          () => error = switch (failure.status) {
            400 =>
              _testWallet
                  ? 'Request unavailable or already attempted. Check its status before starting another.'
                  : 'The demo API rejected this wallet address.',
            409 => 'This request is already being reviewed by another wallet.',
            410 => 'This request has expired. Ask the merchant for a new QR.',
            _ =>
              _testWallet
                  ? 'Unable to prepare. Check status before starting another request.'
                  : 'The demo API could not accept the wallet address.',
          },
        );
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => error =
              'Could not reach the demo API. Check your connection and try again.',
        );
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> refreshPayment() async {
    if (path == null) return;
    try {
      final result = await _request('GET', path!);
      if (_testWallet) await recordReceipt(result);
      if (mounted) {
        setState(() {
          payment = result;
          shared = result['status'] != 'AWAITING_CUSTOMER';
          error = null;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => error =
              'Status unavailable. Check with the merchant before trying again.',
        );
      }
    }
  }

  Future<void> openWallet() async {
    final uri = Uri.tryParse(payment?['interactUrl'] as String? ?? '');
    final debit = payment?['debitMinor'];
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host != 'auth.interledger-test.dev' ||
        uri.userInfo.isNotEmpty ||
        uri.hasPort ||
        payment?['amount'] != details?['amount'] ||
        !validTestWalletDebit(debit, details?['amount'])) {
      setState(() => error = 'The wallet authorization details are invalid.');
      return;
    }
    try {
      await _walletLauncher.invokeMethod<void>('open', uri.toString());
    } catch (_) {
      if (mounted) setState(() => error = 'Could not open Test Wallet.');
    }
  }

  Future<void> confirm() async {
    final address = widget.validateWallet(wallet.text);
    if (address == null || path == null) return;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final result = await _request('POST', '$path/confirm', {
        'walletAddress': address,
      });
      if (result['status'] != 'DEMO_CONFIRMED') {
        throw const FormatException('Unexpected status');
      }
      if (mounted) setState(() => confirmed = true);
    } catch (_) {
      if (mounted) {
        setState(
          () => error =
              'Could not confirm the demo. The request may have expired.',
        );
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final item = details;
    return Scaffold(
      appBar: AppBar(title: const Text('Scan a payment request')),
      body: SafeArea(
        child: item == null
            ? Column(
                children: [
                  const Padding(
                    padding: EdgeInsets.all(20),
                    child: Text(
                      'Scan the merchant’s KwikPay request QR.',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 16),
                    ),
                  ),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 20),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(18),
                        child: MobileScanner(
                          key: ValueKey(cameraAttempt),
                          onDetect: (capture) {
                            for (final code in capture.barcodes) {
                              if (code.format == BarcodeFormat.qrCode &&
                                  code.rawValue != null) {
                                scan(code.rawValue!);
                                break;
                              }
                            }
                          },
                          placeholderBuilder: (_) => const ColoredBox(
                            color: Color(0xff07182c),
                            child: Center(child: CircularProgressIndicator()),
                          ),
                          errorBuilder: (_, failure) => ColoredBox(
                            color: const Color(0xff07182c),
                            child: Center(
                              child: Padding(
                                padding: const EdgeInsets.all(24),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Text(
                                      failure.errorCode ==
                                              MobileScannerErrorCode
                                                  .permissionDenied
                                          ? 'Allow camera access in Android settings, then try again.'
                                          : 'Camera unavailable. Check it is available and try again.',
                                      textAlign: TextAlign.center,
                                      style: const TextStyle(
                                        color: Colors.white,
                                      ),
                                    ),
                                    const SizedBox(height: 12),
                                    FilledButton(
                                      onPressed: () =>
                                          setState(() => cameraAttempt++),
                                      child: const Text('Try camera again'),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                  if (loading)
                    const Padding(
                      padding: EdgeInsets.all(12),
                      child: Text('Loading request…'),
                    ),
                  if (invalid || error != null)
                    Padding(
                      padding: const EdgeInsets.all(16),
                      child: Text(
                        error ?? 'This is not a trusted KwikPay request QR.',
                        style: const TextStyle(color: Color(0xffa93333)),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  if (blockedCode != null)
                    TextButton(
                      onPressed: () => setState(() {
                        blockedCode = null;
                        error = null;
                      }),
                      child: const Text('Try scanning again'),
                    ),
                  const Padding(
                    padding: EdgeInsets.all(12),
                    child: Text(
                      _testWallet
                          ? 'Test Wallet payment. Approval happens in your wallet.'
                          : 'Demo only. No payment is made.',
                    ),
                  ),
                ],
              )
            : Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 520),
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          _testWallet
                              ? 'TEST WALLET · R10 LIMIT'
                              : 'DEMO · NO PAYMENT',
                          style: TextStyle(
                            fontSize: 11,
                            letterSpacing: 1.1,
                            fontWeight: FontWeight.w800,
                            color: Color(0xff53657b),
                          ),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          _testWallet && shared
                              ? 'Test Wallet payment'
                              : confirmed
                              ? 'Demo confirmed'
                              : shared
                              ? 'Confirm demo transaction'
                              : 'Review payment request',
                          style: Theme.of(context).textTheme.headlineMedium
                              ?.copyWith(
                                fontWeight: FontWeight.w800,
                                color: const Color(0xff10233b),
                              ),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          item['merchant'] as String,
                          style: const TextStyle(
                            color: Color(0xff53657b),
                            fontSize: 16,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          money(item['amount'] as String),
                          style: const TextStyle(
                            fontSize: 36,
                            fontWeight: FontWeight.w800,
                            color: Color(0xff10233b),
                          ),
                        ),
                        const SizedBox(height: 20),
                        if (!_testWallet ||
                            payment?['status'] != 'PROCESSING') ...[
                          const Text(
                            'Payment split',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                              color: Color(0xff10233b),
                            ),
                          ),
                          const SizedBox(height: 8),
                          for (final pot in item['pots'] as List)
                            Padding(
                              padding: const EdgeInsets.symmetric(vertical: 7),
                              child: Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      '${pot['label']} · ${pot['percentage']}%',
                                      style: const TextStyle(
                                        color: Color(0xff53657b),
                                      ),
                                    ),
                                  ),
                                  const SizedBox(width: 12),
                                  Text(
                                    money(pot['amount'] as String),
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w800,
                                      color: Color(0xff10233b),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          if (_testWallet)
                            ExpansionTile(
                              tilePadding: EdgeInsets.zero,
                              title: const Text(
                                'View destination addresses',
                                style: TextStyle(
                                  fontSize: 14,
                                  color: Color(0xff244e9a),
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              children: [
                                for (final pot in item['pots'] as List)
                                  Padding(
                                    padding: const EdgeInsets.only(bottom: 12),
                                    child: Align(
                                      alignment: Alignment.centerLeft,
                                      child: SelectableText(
                                        '${pot['label']}: ${pot['walletAddress']}',
                                        style: const TextStyle(
                                          fontSize: 13,
                                          color: Color(0xff53657b),
                                        ),
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                        ],
                        const SizedBox(height: 22),
                        if (_testWallet && (shared || attempted)) ...[
                          PaymentStatusPanel(payment: payment),
                          if (payment?['status'] == 'AWAITING_CONSENT')
                            Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(
                                'Maximum debit: ${money(payment!['debitMinor'] as String)}. Review and approve in your Test Wallet.',
                              ),
                            ),
                          const SizedBox(height: 16),
                          if (payment?['status'] == 'AWAITING_CONSENT')
                            SizedBox(
                              width: double.infinity,
                              child: FilledButton(
                                onPressed: openWallet,
                                child: const Text('Continue to Test Wallet'),
                              ),
                            ),
                          TextButton(
                            onPressed: refreshPayment,
                            child: const Text('Refresh status'),
                          ),
                        ] else if (!shared) ...[
                          TextField(
                            controller: wallet,
                            keyboardType: TextInputType.url,
                            autocorrect: false,
                            decoration: const InputDecoration(
                              labelText: 'Your wallet address',
                              border: OutlineInputBorder(),
                            ),
                          ),
                          const SizedBox(height: 16),
                          SizedBox(
                            width: double.infinity,
                            child: FilledButton(
                              onPressed: loading ? null : share,
                              child: Text(
                                loading
                                    ? (_testWallet
                                          ? 'Preparing quote…'
                                          : 'Sharing…')
                                    : (_testWallet
                                          ? 'Prepare Test Wallet payment'
                                          : 'Share wallet address'),
                              ),
                            ),
                          ),
                        ] else if (!confirmed) ...[
                          const Text(
                            'Confirm to show the merchant this demo transaction. No wallet approval or payment will take place.',
                          ),
                          const SizedBox(height: 16),
                          SizedBox(
                            width: double.infinity,
                            child: FilledButton(
                              onPressed: loading ? null : confirm,
                              child: Text(
                                loading
                                    ? 'Confirming…'
                                    : 'Confirm demo transaction',
                              ),
                            ),
                          ),
                        ] else
                          const Text(
                            'The merchant can see your confirmation. No money was sent.',
                            style: TextStyle(height: 1.5),
                          ),
                        const SizedBox(height: 16),
                        if (!_testWallet ||
                            payment?['status'] == 'AWAITING_CONSENT' ||
                            !shared)
                          const Text(
                            _testWallet
                                ? 'Only approve in Test Wallet if the amount and merchant are correct.'
                                : 'Sharing your wallet address does not approve or send a payment.',
                            style: TextStyle(
                              color: Color(0xff53657b),
                              height: 1.45,
                            ),
                          ),
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
