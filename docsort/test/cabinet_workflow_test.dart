import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/features/cabinet/presentation/providers/cabinet_provider.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Dio _cabinetDio() {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        expect(options.path, '/cabinet/folders');

        handler.resolve(
          Response<dynamic>(
            requestOptions: options,
            statusCode: 200,
            data: const [
              {'id': 'review', 'name': 'Needs Review', 'document_count': 0},
              {'id': 'finance', 'name': 'Finance', 'document_count': 1},
            ],
          ),
        );
      },
    ),
  );

  return dio;
}

Future<void> _settleUntil(bool Function() condition) async {
  for (var i = 0; i < 30; i++) {
    if (condition()) return;
    await Future<void>.delayed(Duration.zero);
  }

  fail('Provider state did not settle in time');
}

void main() {
  test('cabinet keeps empty folders returned by backend', () async {
    final container = ProviderContainer.test(
      overrides: [dioProvider.overrideWithValue(_cabinetDio())],
    );

    final subscription = container.listen(
      cabinetListProvider,
      (_, _) {},
      fireImmediately: true,
    );

    addTearDown(subscription.close);

    await _settleUntil(() => container.read(cabinetListProvider).hasValue);

    final folders = container.read(cabinetListProvider).requireValue;

    expect(folders.map((folder) => folder.name), ['Needs Review', 'Finance']);

    expect(folders.first.documentCount, 0);
    expect(folders.last.documentCount, 1);
  });
}
