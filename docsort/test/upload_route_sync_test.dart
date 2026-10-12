import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('single-file upload enters processing with a recoverable job URL', () {
    final source = File(
      'lib/features/upload/presentation/screens/upload_screen.dart',
    ).readAsStringSync();

    // The processing URL carries its encoded job ID for refresh/deep links.
    expect(
      source,
      contains("context.go('/processing?job=\${Uri.encodeQueryComponent(jobId)}')"),
    );
    expect(source, isNot(contains("context.push('/processing")));
  });

  test('processing completion enters review with URL-synchronizing navigation', () {
    final source = File(
      'lib/features/upload/presentation/screens/processing_screen.dart',
    ).readAsStringSync();

    expect(source, isNot(contains("context.pushReplacement('/review/")));
    expect(source, contains("context.go('/review/"));
  });
}
