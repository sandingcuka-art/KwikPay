import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'checkout.dart';
import 'receipts.dart';

const settingsChannel = MethodChannel('kwikpay/settings');

const demoWallet = 'https://ilp.interledger-test.dev/wikus-customer';

void main() => runApp(const KwikPayCustomerApp());

/// The QR payload is the HTTPS wallet address, not a payment or credential.
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

class KwikPayCustomerApp extends StatelessWidget {
  const KwikPayCustomerApp({super.key});

  @override
  Widget build(BuildContext context) {
    const blue = Color(0xff1769ff);
    return MaterialApp(
      title: 'KwikPay Customer',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: blue,
          surface: Colors.white,
        ),
        scaffoldBackgroundColor: const Color(0xfff2f6fa),
        useMaterial3: true,
        inputDecorationTheme: InputDecorationTheme(
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
          filled: true,
          fillColor: Colors.white,
        ),
      ),
      home: const WalletScreen(),
    );
  }
}

class WalletScreen extends StatefulWidget {
  const WalletScreen({super.key});

  @override
  State<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends State<WalletScreen> {
  final _formKey = GlobalKey<FormState>();
  final _wallet = TextEditingController();
  String? _shownWallet;
  Timer? _receiptRefresh;

  @override
  void initState() {
    super.initState();
    unawaited(_loadSettings());
    unawaited(refreshReceipts().catchError((_) => false));
    _receiptRefresh = Timer(const Duration(seconds: 8), () {
      unawaited(refreshReceipts().catchError((_) => false));
    });
  }

  Future<void> _loadSettings() async {
    try {
      final saved = await settingsChannel.invokeMethod<String>('load');
      if (mounted && saved != null && _wallet.text.isEmpty) {
        setState(() => _wallet.text = saved);
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not load wallet settings.')),
        );
      }
    }
  }

  Future<void> _openSettings() async {
    final saved = await Navigator.of(context).push<String>(
      MaterialPageRoute(
        builder: (_) => WalletSettingsPage(initial: _wallet.text),
      ),
    );
    if (mounted && saved != null) {
      setState(() {
        _wallet.text = saved;
        _shownWallet = null;
      });
    }
  }

  @override
  void dispose() {
    _receiptRefresh?.cancel();
    _wallet.dispose();
    super.dispose();
  }

  void _showQr() {
    if (!_formKey.currentState!.validate()) return;
    FocusScope.of(context).unfocus();
    setState(() => _shownWallet = walletAddress(_wallet.text));
  }

  @override
  Widget build(BuildContext context) {
    final shown = _shownWallet;
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
                          color: const Color(0xff1769ff),
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
                      const Expanded(
                        child: Column(
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
                              'CUSTOMER',
                              style: TextStyle(
                                fontSize: 10,
                                letterSpacing: 1.8,
                                color: Color(0xff53657b),
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        onPressed: _openSettings,
                        tooltip: 'Wallet settings',
                        icon: const Icon(Icons.settings_outlined),
                      ),
                    ],
                  ),
                  const SizedBox(height: 38),
                  Text(
                    shown == null
                        ? 'Pay with KwikPay'
                        : 'Show this to the merchant',
                    style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                      color: const Color(0xff10233b),
                      fontWeight: FontWeight.w800,
                      height: 1.12,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    shown == null
                        ? 'Scan the merchant’s request to review your payment.'
                        : 'The merchant can scan this code to get your wallet address.',
                    style: const TextStyle(
                      color: Color(0xff53657b),
                      fontSize: 16,
                      height: 1.5,
                    ),
                  ),
                  const SizedBox(height: 28),
                  if (shown == null) ...[
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        onPressed: () => Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => CustomerCheckoutPage(
                              initialWallet: _wallet.text,
                              validateWallet: walletAddress,
                            ),
                          ),
                        ),
                        icon: const Icon(Icons.qr_code_scanner),
                        label: const Text('Scan merchant request'),
                        style: FilledButton.styleFrom(
                          minimumSize: const Size.fromHeight(54),
                          backgroundColor: const Color(0xff1769ff),
                          textStyle: const TextStyle(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 18),
                    SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        onPressed: () => Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => const ReceiptHistoryPage(),
                          ),
                        ),
                        icon: const Icon(Icons.receipt_long_outlined),
                        label: const Text('Payment history'),
                      ),
                    ),
                    const SizedBox(height: 16),
                    const Divider(color: Color(0xffd1ddea)),
                    const SizedBox(height: 18),
                    const Row(
                      children: [
                        Icon(
                          Icons.account_balance_wallet_outlined,
                          color: Color(0xff244e9a),
                          size: 22,
                        ),
                        SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            'Or share your wallet address',
                            style: TextStyle(
                              fontSize: 17,
                              fontWeight: FontWeight.w700,
                              color: Color(0xff10233b),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Form(
                      key: _formKey,
                      child: TextFormField(
                        key: const Key('wallet-input'),
                        controller: _wallet,
                        keyboardType: TextInputType.url,
                        textInputAction: TextInputAction.done,
                        autocorrect: false,
                        enableSuggestions: false,
                        decoration: const InputDecoration(
                          labelText: 'Wallet address',
                          hintText: 'https://… or \$wallet.example',
                          alignLabelWithHint: true,
                        ),
                        validator: (value) => walletAddress(value ?? '') == null
                            ? 'Enter a valid HTTPS wallet address or \$ payment pointer.'
                            : null,
                        onFieldSubmitted: (_) => _showQr(),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextButton.icon(
                      onPressed: () {
                        _wallet.text = demoWallet;
                        _formKey.currentState?.validate();
                      },
                      icon: const Icon(Icons.science_outlined, size: 18),
                      label: const Text('Use test customer wallet'),
                    ),
                    const SizedBox(height: 18),
                    SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        onPressed: _showQr,
                        style: OutlinedButton.styleFrom(
                          minimumSize: const Size.fromHeight(54),
                        ),
                        icon: const Icon(Icons.qr_code_2),
                        label: const Text(
                          'Create QR code',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),
                    const Text(
                      'Your wallet address is shared when scanned. Creating a QR code does not make a payment.',
                      style: TextStyle(color: Color(0xff53657b), height: 1.45),
                    ),
                  ] else ...[
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(20),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(20),
                        border: Border.all(color: const Color(0xffdce6f0)),
                      ),
                      child: Column(
                        children: [
                          LayoutBuilder(
                            builder: (context, constraints) => RepaintBoundary(
                              key: const Key('wallet-qr'),
                              child: Semantics(
                                label:
                                    'QR code containing wallet address $shown',
                                child: QrImageView(
                                  data: shown,
                                  version: QrVersions.auto,
                                  size: constraints.maxWidth < 250
                                      ? constraints.maxWidth
                                      : 250,
                                  backgroundColor: Colors.white,
                                  padding: const EdgeInsets.all(28),
                                ),
                              ),
                            ),
                          ),
                          const SizedBox(height: 12),
                          const Text(
                            'WALLET ADDRESS',
                            style: TextStyle(
                              color: Color(0xff53657b),
                              fontSize: 11,
                              fontWeight: FontWeight.w800,
                              letterSpacing: 1.3,
                            ),
                          ),
                          const SizedBox(height: 8),
                          SelectableText(
                            shown,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              color: Color(0xff10233b),
                              fontWeight: FontWeight.w600,
                              height: 1.4,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 18),
                    SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        onPressed: () => setState(() => _shownWallet = null),
                        icon: const Icon(Icons.edit_outlined, size: 18),
                        label: const Text('Change wallet address'),
                        style: OutlinedButton.styleFrom(
                          minimumSize: const Size.fromHeight(54),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    const Text(
                      'A scan shares your wallet address only. Any payment requires your wallet approval.',
                      style: TextStyle(color: Color(0xff53657b), height: 1.45),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class WalletSettingsPage extends StatefulWidget {
  const WalletSettingsPage({super.key, required this.initial});
  final String initial;

  @override
  State<WalletSettingsPage> createState() => _WalletSettingsPageState();
}

class _WalletSettingsPageState extends State<WalletSettingsPage> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _address = TextEditingController(
    text: widget.initial,
  );
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _address.dispose();
    super.dispose();
  }

  Future<void> _save({bool clear = false}) async {
    if (!clear && !_form.currentState!.validate()) return;
    final value = clear ? '' : walletAddress(_address.text)!;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await settingsChannel.invokeMethod<void>('save', value);
      if (mounted) Navigator.pop(context, value);
    } catch (_) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = 'Could not save settings. Please try again.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Wallet settings')),
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
                  'Your wallet address',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 12),
                const Text(
                  'Enter your own Interledger Test Wallet address. You will approve payments in your wallet.',
                  style: TextStyle(height: 1.5),
                ),
                const SizedBox(height: 24),
                TextFormField(
                  key: const Key('settings-wallet'),
                  controller: _address,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  enableSuggestions: false,
                  decoration: const InputDecoration(
                    labelText: 'Test Wallet address',
                    hintText: r'$ilp.interledger-test.dev/your-wallet',
                  ),
                  validator: (value) {
                    final address = walletAddress(value ?? '');
                    final uri = address == null ? null : Uri.parse(address);
                    return uri == null ||
                            uri.host != 'ilp.interledger-test.dev' ||
                            uri.path.isEmpty ||
                            uri.path == '/'
                        ? 'Enter your Interledger Test Wallet address.'
                        : null;
                  },
                ),
                const SizedBox(height: 12),
                const Text(
                  'Stored on this device. Never enter a password or private key.',
                  style: TextStyle(color: Color(0xff53657b)),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: const TextStyle(color: Colors.red)),
                ],
                const SizedBox(height: 24),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _saving ? null : _save,
                    child: Text(_saving ? 'Saving…' : 'Save wallet'),
                  ),
                ),
                TextButton(
                  onPressed: _saving ? null : () => _save(clear: true),
                  child: const Text('Clear saved wallet'),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
