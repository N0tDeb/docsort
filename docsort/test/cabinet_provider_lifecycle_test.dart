import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('cabinet async fetch guards post-await state writes after disposal', () {
    final source = File(
      'lib/features/cabinet/presentation/providers/cabinet_provider.dart',
    ).readAsStringSync();

    final awaitIndex =
        source.indexOf("await dio.get('/cabinet/folders')");
    expect(awaitIndex, isNonNegative);

    final afterAwait = source.substring(awaitIndex);

    expect(
      afterAwait,
      contains('if (!ref.mounted) return;'),
      reason:
          'The autoDispose notifier must stop before writing state after the async request if it has been disposed.',
    );
  });
}
