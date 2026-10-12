import 'package:flutter_test/flutter_test.dart';

import 'package:docsort/features/home/presentation/providers/home_provider.dart';

void main() {
  test('home metrics prefer explicit 24 hour activity metric', () {
    final metrics = HomeMetrics.fromJson({
      'active_users_24h': 7,
      'active_users_today': 99,
    });

    expect(metrics.active24h, 7);
  });

  test('home metrics support the active_users_today API alias', () {
    final metrics = HomeMetrics.fromJson({'active_users_today': 3});

    expect(metrics.active24h, 3);
  });
}
