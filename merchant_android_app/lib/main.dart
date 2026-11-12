import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'checkout.dart';

const _testWallet = bool.fromEnvironment('KWIKPAY_TEST_WALLET');

void main() => runApp(const KwikPayMerchantApp());

/// Match the customer app's QR contract; this checks shape, not wallet ownership.
String? walletAddress(String input) {
  final value = input.trim();
  if (value.isEmpty || value.length > 512 || RegExp(r'\s').hasMatch(value)) {
    return null;
  }
  final normalized = value.startsWith(r'$')
      ? 'https://${value.substring(1)}'
      : value;
  final uri = Uri.tryParse(normalized);
  if (uri == null ||
      uri.scheme != 'https' ||
      uri.host.isEmpty ||
      uri.userInfo.isNotEmpty ||
      uri.hasPort ||
      uri.hasQuery ||
      uri.hasFragment) {
    return null;
  }
  return normalized;
}

class KwikPayMerchantApp extends StatelessWidget {
  const KwikPayMerchantApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'KwikPay Merchant',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff1769ff)),
        scaffoldBackgroundColor: const Color(0xfff2f6fa),
        useMaterial3: true,
      ),
      home: const MerchantHome(),
    );
  }
}

class MerchantHome extends StatefulWidget {
  const MerchantHome({super.key, this.cameraBuilder});
  final Widget Function(ValueChanged<String> onCode)? cameraBuilder;

  @override
  State<MerchantHome> createState() => _MerchantHomeState();
}

class _MerchantHomeState extends State<MerchantHome> {
  String? _wallet;

  Future<void> _scan() async {
    final wallet = await Navigator.of(context).push<String>(
      MaterialPageRoute(
        builder: (_) => WalletScanPage(cameraBuilder: widget.cameraBuilder),
      ),
    );
    if (mounted && wallet != null) setState(() => _wallet = wallet);
  }

  @override
  Widget build(BuildContext context) {
    final wallet = _wallet;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(24, 28, 24, 32),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 42,
                        height: 42,
                        decoration: BoxDecoration(
                          color: const Color(0xff07182c),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        alignment: Alignment.center,
                        child: const Text(
                          'K',
                          style: TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w900,
                            fontSize: 23,
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      const Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'KwikPay',
                            style: TextStyle(
                              fontSize: 20,
                              fontWeight: FontWeight.w800,
                              color: Color(0xff10233b),
                            ),
                          ),
                          Text(
                            'MERCHANT',
                            style: TextStyle(
                              fontSize: 10,
                              letterSpacing: 1.8,
                              color: Color(0xff53657b),
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: 38),
                  Text(
                    wallet == null
                        ? 'Scan customer wallet'
                        : 'Customer wallet captured',
                    style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                      color: const Color(0xff10233b),
                      fontWeight: FontWeight.w800,
                      height: 1.12,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    wallet == null
                        ? 'Ask the customer to show their wallet QR code, then scan it to continue.'
                        : 'Review the address before using it for a sale.',
                    style: const TextStyle(
                      color: Color(0xff53657b),
                      fontSize: 16,
                      height: 1.5,
                    ),
                  ),
                  const SizedBox(height: 28),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(22),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: const Color(0xffdce6f0)),
                    ),
                    child: wallet == null
                        ? const Column(
                            children: [
                              Icon(
                                Icons.qr_code_scanner_rounded,
                                size: 64,
                                color: Color(0xff1769ff),
                              ),
                              SizedBox(height: 14),
                              Text(
                                'Ready when your customer is',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  color: Color(0xff10233b),
                                  fontWeight: FontWeight.w700,
                                  fontSize: 17,
                                ),
                              ),
                              SizedBox(height: 8),
                              Text(
                                'Your camera opens only when you start scanning.',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  color: Color(0xff53657b),
                                  height: 1.45,
                                ),
                              ),
                            ],
                          )
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text(
                                'CUSTOMER WALLET',
                                style: TextStyle(
                                  color: Color(0xff53657b),
                                  fontSize: 11,
                                  fontWeight: FontWeight.w800,
                                  letterSpacing: 1.3,
                                ),
                              ),
                              const SizedBox(height: 10),
                              SelectableText(
                                wallet,
                                key: const Key('captured-wallet'),
                                style: const TextStyle(
                                  color: Color(0xff10233b),
                                  fontWeight: FontWeight.w600,
                                  height: 1.5,
                                ),
                              ),
                              const SizedBox(height: 14),
                              const Text(
                                'Address format checked; wallet ownership and availability have not been verified.',
                                style: TextStyle(
                                  color: Color(0xff53657b),
                                  height: 1.45,
                                ),
                              ),
                            ],
                          ),
                  ),
                  const SizedBox(height: 20),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: () => Navigator.of(context).push(
                        MaterialPageRoute(
                          builder: (_) => const MerchantCheckoutPage(),
                        ),
                      ),
                      icon: const Icon(Icons.point_of_sale),
                      label: const Text('Create payment request'),
                    ),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: () => Navigator.of(context).push(
                        MaterialPageRoute(
                          builder: (_) => const DemoHistoryPage(),
                        ),
                      ),
                      icon: const Icon(Icons.receipt_long),
                      label: const Text(
                        _testWallet
                            ? 'Transaction history'
                            : 'Demo transaction history',
                      ),
                    ),
                  ),
                  if (_testWallet) ...[
                    const SizedBox(height: 10),
                    SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        onPressed: () => Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => const MerchantAccessPage(),
                          ),
                        ),
                        icon: const Icon(Icons.key_outlined),
                        label: const Text('Merchant access'),
                      ),
                    ),
                  ],
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: _scan,
                      icon: const Icon(Icons.qr_code_scanner),
                      label: Text(
                        wallet == null
                            ? 'Scan wallet QR code'
                            : 'Scan another wallet',
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      style: FilledButton.styleFrom(
                        minimumSize: const Size.fromHeight(54),
                        backgroundColor: const Color(0xff1769ff),
                      ),
                    ),
                  ),
                  const SizedBox(height: 18),
                  const Text(
                    _testWallet
                        ? 'Test Wallet trial · The customer approves in their wallet.'
                        : 'Demo only · Wallet approval and payments are not connected.',
                    style: TextStyle(color: Color(0xff53657b), height: 1.45),
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

// A camera builder lets widget tests exercise the scan flow without camera hardware.
class WalletScanPage extends StatefulWidget {
  const WalletScanPage({super.key, this.cameraBuilder});
  final Widget Function(ValueChanged<String> onCode)? cameraBuilder;

  @override
  State<WalletScanPage> createState() => _WalletScanPageState();
}

class _WalletScanPageState extends State<WalletScanPage> {
  bool _handled = false;
  bool _invalid = false;
  int _cameraAttempt = 0;

  void _onCode(String value) {
    if (_handled) return;
    final address = walletAddress(value);
    if (address == null) {
      if (!_invalid) setState(() => _invalid = true);
      return;
    }
    _handled = true;
    Navigator.of(context).pop(address);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Scan customer wallet')),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                children: [
                  const Text(
                    'Point your camera at the customer’s wallet QR code.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 16,
                      height: 1.5,
                      color: Color(0xff53657b),
                    ),
                  ),
                  const SizedBox(height: 18),
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(18),
                      child:
                          widget.cameraBuilder?.call(_onCode) ??
                          MobileScanner(
                            key: ValueKey(_cameraAttempt),
                            onDetect: (capture) {
                              for (final code in capture.barcodes) {
                                if (code.format == BarcodeFormat.qrCode &&
                                    code.rawValue != null) {
                                  _onCode(code.rawValue!);
                                  break;
                                }
                              }
                            },
                            placeholderBuilder: (_) => const ColoredBox(
                              color: Color(0xff07182c),
                              child: Center(child: CircularProgressIndicator()),
                            ),
                            errorBuilder: (context, error) => ColoredBox(
                              color: const Color(0xff07182c),
                              child: Center(
                                child: Padding(
                                  padding: const EdgeInsets.all(24),
                                  child: Column(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      const Icon(
                                        Icons.no_photography_outlined,
                                        color: Colors.white,
                                        size: 38,
                                      ),
                                      const SizedBox(height: 12),
                                      Text(
                                        error.errorCode ==
                                                MobileScannerErrorCode
                                                    .permissionDenied
                                            ? 'Camera access is off. Allow camera access in Android settings, then try again.'
                                            : 'The camera could not start. Check that it is available and try again.',
                                        textAlign: TextAlign.center,
                                        style: const TextStyle(
                                          color: Colors.white,
                                          height: 1.4,
                                        ),
                                      ),
                                      const SizedBox(height: 12),
                                      FilledButton(
                                        onPressed: () =>
                                            setState(() => _cameraAttempt++),
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
                  const SizedBox(height: 16),
                  if (_invalid)
                    const Text(
                      'That QR code is not a valid wallet address. Try another code.',
                      key: Key('invalid-qr'),
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Color(0xffa93333), height: 1.4),
                    )
                  else
                    const Text(
                      'Only the wallet address is read. No payment is made.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Color(0xff53657b), height: 1.4),
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
