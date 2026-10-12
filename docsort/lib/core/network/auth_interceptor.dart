import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../features/auth/presentation/providers/auth_provider.dart';
import 'session_store.dart';

class AuthInterceptor extends Interceptor {
  final Ref ref;
  AuthInterceptor(this.ref);

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) async {
    final token = await ref.read(sessionStoreProvider).read('auth_token');
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    // If 401 unauthorized, log out the user securely via the provider
    if (err.response?.statusCode == 401) {
      ref.read(authProvider.notifier).logout();
    }
    handler.next(err);
  }
}
