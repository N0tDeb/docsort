import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Result Review & Verify uses URL-synchronizing navigation', () {
    final source = File(
      'lib/features/upload/presentation/screens/result_screen.dart',
    ).readAsStringSync();

    // Review routes include an encoded return path so browser history works.
    expect(source, contains("return '/review/\$documentId?from="));
    expect(source, contains('context.go(_reviewRoute(documentId))'));
    expect(source, isNot(contains('context.push(_reviewRoute(documentId))')));
  });
}
