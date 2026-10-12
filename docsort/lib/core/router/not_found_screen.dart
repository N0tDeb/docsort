import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/auth/presentation/providers/auth_provider.dart';
import '../theme/app_colors.dart';
import '../theme/app_text_styles.dart';

class NotFoundScreen extends ConsumerWidget {
  const NotFoundScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authProvider);
    final destination = authState.status == AuthStatus.authenticated
        ? (authState.isAdmin ? '/admin' : '/home')
        : '/login';

    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 520),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.travel_explore_rounded,
                    size: 72,
                    color: AppColors.primary,
                  ),
                  const SizedBox(height: 20),
                  Text(
                    'Page not found',
                    style: AppTextStyles.displayMd,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'The requested DocSort page does not exist or is no longer available.',
                    style: AppTextStyles.bodyLg.copyWith(
                      color: AppColors.textSecondary,
                    ),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton.icon(
                    onPressed: () => context.go(destination),
                    icon: const Icon(Icons.home_rounded),
                    label: const Text('Return to DocSort'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
