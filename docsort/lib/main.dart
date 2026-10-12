import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/router/app_router.dart';
import 'core/theme/app_colors.dart';
import 'core/widgets/app_loader.dart';
import 'features/auth/presentation/providers/auth_provider.dart';

void main() {
  runApp(
    const ProviderScope(
      child: DocSortApp(),
    ),
  );
}

class DocSortApp extends ConsumerWidget {
  const DocSortApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authProvider);

    if (authState.status == AuthStatus.restoring) {
      return const ColoredBox(
        color: AppColors.background,
        child: AppLoader(),
      );
    }

    final router = ref.watch(routerProvider);

    return MaterialApp.router(
      title: 'DocSort',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: AppColors.background,
        primaryColor: AppColors.primary,
        colorScheme: ColorScheme.light(
          primary: AppColors.primary,
          primaryContainer: AppColors.primaryContainer,
          secondary: AppColors.secondary,
          secondaryContainer: AppColors.secondaryContainer,
          surface: AppColors.surfaceLowest,
          error: AppColors.error,
          onPrimary: Colors.white,
          onSurface: AppColors.textPrimary,
        ),
      ),
      routerConfig: router,
    );
  }
}
