import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kwikpay_merchant/checkout.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets(
    'merchant access can be saved and cleared without displaying it',
    (tester) async {
      String? saved;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, (call) async {
            if (call.method == 'Clipboard.getData') {
              return {'text': ' local-test-key '};
            }
            return null;
          });
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(merchantAccess, (call) async {
            switch (call.method) {
              case 'configured':
                return saved != null;
              case 'save':
                saved = call.arguments as String;
                return null;
              case 'clear':
                saved = null;
                return null;
            }
            return null;
          });
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(merchantAccess, null),
      );
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(SystemChannels.platform, null),
      );
      await tester.pumpWidget(const MaterialApp(home: MerchantAccessPage()));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save access'));
      await tester.pumpAndSettle();
      expect(find.text('Enter the merchant access key.'), findsOneWidget);
      await tester.tap(find.text('Paste'));
      await tester.pumpAndSettle();
      final field = tester.widget<TextFormField>(
        find.byKey(const Key('merchant-access-key')),
      );
      expect(
        tester.widget<EditableText>(find.byType(EditableText)).obscureText,
        isTrue,
      );
      expect(field.controller!.text, 'local-test-key');
      await tester.tap(find.text('Save access'));
      await tester.pumpAndSettle();
      expect(saved, 'local-test-key');
      expect(
        find.text('Merchant access is saved on this device.'),
        findsOneWidget,
      );
      expect(find.text('local-test-key'), findsNothing);
      await tester.tap(find.text('Clear access'));
      await tester.pumpAndSettle();
      expect(saved, isNull);
    },
  );
}
