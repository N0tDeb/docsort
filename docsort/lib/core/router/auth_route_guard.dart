/// Pure redirect decision used by the app router. Keeping this logic independent
/// from widgets makes the role/session routing contract easy to test deterministically.
String? authRedirectFor({
  required bool isLoggedIn,
  required bool isAdmin,
  required String location,
}) {
  final goingToAuth = location == '/login' || location == '/register';

  if (!isLoggedIn && !goingToAuth) return '/login';

  if (isLoggedIn && goingToAuth) {
    return isAdmin ? '/admin' : '/home';
  }

  if (isLoggedIn && isAdmin && location == '/home') return '/admin';

  final adminOnlyRoute =
      location == '/admin' ||
      location.startsWith('/admin/') ||
      location == '/graph' ||
      location.startsWith('/graph/');
  if (isLoggedIn && !isAdmin && adminOnlyRoute) return '/home';

  return null;
}
