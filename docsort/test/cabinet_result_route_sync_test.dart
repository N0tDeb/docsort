import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('cabinet document tap uses URL-synchronizing Result navigation', () {
    final source = File(
      'lib/features/cabinet/presentation/screens/cabinet_detail_screen.dart',
    ).readAsStringSync();

    expect(
      source,
      isNot(contains("context\r\n                      .push('/result/\$docId')")),
    );

    expect(
      source,
      contains("context\r\n                      .go('/result/\$docId')"),
    );
  });
}
