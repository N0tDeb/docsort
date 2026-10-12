import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Result Review & Verify uses URL-synchronizing navigation', () {
    final source = File(
      'lib/features/upload/presentation/screens/result_screen.dart',
    ).readAsStringSync();

    expect(
      source,
      isNot(contains("context.push('/review/\$documentId')")),
    );

    expect(
      source,
      contains("context.go('/review/\$documentId')"),
    );
  });
}
