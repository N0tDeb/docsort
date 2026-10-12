import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Result screen uses clean user-visible strings', () {
    final source = File(
      'lib/features/upload/presentation/screens/result_screen.dart',
    ).readAsStringSync();

    expect(
      source,
      isNot(contains("Document saved to Cabinet Ã")),
    );
    expect(
      source,
      contains("'Document saved to Cabinet'"),
    );

    expect(
      source,
      isNot(contains("flags.join(' Ã")),
    );
    expect(
      source,
      contains(r"flags.join(' \u2022 ')"),
    );

    expect(
      source,
      isNot(contains("field['value'] ?? 'Ã")),
    );
    expect(
      source,
      contains(r"field['value'] ?? '\u2014'"),
    );
  });
}
