import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('cabinet document tap preserves return location in Result URL', () {
    final source = File(
      'lib/features/cabinet/presentation/screens/cabinet_detail_screen.dart',
    ).readAsStringSync();

    // Allow Flutter formatting changes while enforcing URL-aware navigation.
    expect(source, contains(".go('/result/\$docId?from="));
    expect(source, contains('Uri.encodeComponent("/cabinet/'));
    expect(source, isNot(contains(".push('/result/\$docId")));
  });
}
