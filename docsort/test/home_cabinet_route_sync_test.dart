import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Home Cabinet bottom navigation keeps browser URL synchronized', () {
    final source = File(
      'lib/features/home/presentation/screens/home_screen.dart',
    ).readAsStringSync().replaceAll('\r\n', '\n');

    expect(
      source,
      contains(
        "case 2:\n"
        "        context.go('/cabinet');\n"
        "        break;",
      ),
    );
  });
}
