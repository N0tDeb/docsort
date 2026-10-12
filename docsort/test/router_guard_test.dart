import 'package:docsort/core/router/auth_route_guard.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('authentication route guard', () {
    test('unauthenticated users are sent to login from protected routes', () {
      expect(
        authRedirectFor(isLoggedIn: false, isAdmin: false, location: '/cabinet'),
        '/login',
      );
    });

    test('unauthenticated users may stay on login and registration', () {
      expect(
        authRedirectFor(isLoggedIn: false, isAdmin: false, location: '/login'),
        isNull,
      );
      expect(
        authRedirectFor(isLoggedIn: false, isAdmin: false, location: '/register'),
        isNull,
      );
    });

    test('router callers use URI path so auth-page query parameters stay valid', () {
      final location = Uri.parse('/login?next=%2Fcabinet').path;
      expect(
        authRedirectFor(isLoggedIn: false, isAdmin: false, location: location),
        isNull,
      );
    });

    test('authenticated users leave auth pages for their landing page', () {
      expect(
        authRedirectFor(isLoggedIn: true, isAdmin: false, location: '/login'),
        '/home',
      );
      expect(
        authRedirectFor(isLoggedIn: true, isAdmin: true, location: '/register'),
        '/admin',
      );
    });

    test('admins cannot be redirected back to the ordinary home dashboard', () {
      expect(
        authRedirectFor(isLoggedIn: true, isAdmin: true, location: '/home'),
        '/admin',
      );
    });

    test('authenticated users keep only routes allowed by their role', () {
      expect(
        authRedirectFor(isLoggedIn: true, isAdmin: false, location: '/search'),
        isNull,
      );
      expect(
        authRedirectFor(isLoggedIn: true, isAdmin: false, location: '/admin'),
        '/home',
      );
      expect(
        authRedirectFor(isLoggedIn: true, isAdmin: false, location: '/graph'),
        '/home',
      );
      expect(
        authRedirectFor(isLoggedIn: true, isAdmin: true, location: '/admin'),
        isNull,
      );
      expect(
        authRedirectFor(isLoggedIn: true, isAdmin: true, location: '/graph'),
        isNull,
      );
    });
  });
}
