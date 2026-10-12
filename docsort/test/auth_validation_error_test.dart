import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/core/network/session_store.dart';
import 'package:docsort/features/auth/presentation/providers/auth_provider.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class MemorySessionStore implements SessionStore {
  final Map<String, String> values = {};

  @override
  Future<void> delete(String key) async {
    values.remove(key);
  }

  @override
  Future<String?> read(String key) async => values[key];

  @override
  Future<void> write(String key, String value) async {
    values[key] = value;
  }
}

void main() {
  test(
    'registration handles FastAPI list validation errors without staying loading',
    () async {
      final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));

      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            expect(options.path, '/auth/signup');

            handler.reject(
              DioException(
                requestOptions: options,
                type: DioExceptionType.badResponse,
                response: Response<dynamic>(
                  requestOptions: options,
                  statusCode: 422,
                  data: const {
                    'detail': [
                      {
                        'type': 'value_error',
                        'loc': ['body', 'email'],
                        'msg': 'value is not a valid email address',
                        'input': 'not-an-email',
                      },
                    ],
                  },
                ),
              ),
            );
          },
        ),
      );

      final container = ProviderContainer.test(
        overrides: [
          sessionStoreProvider.overrideWithValue(MemorySessionStore()),
          dioProvider.overrideWithValue(dio),
        ],
      );

      final ok = await container
          .read(authProvider.notifier)
          .register('Validation Test', 'not-an-email', 'ValidPass123', '');

      expect(ok, isFalse);
      expect(container.read(authProvider).status, AuthStatus.error);
      expect(
        container.read(authProvider).errorMessage,
        contains('valid email'),
      );
    },
  );
}
