import 'package:flutter/material.dart';
import 'app_colors.dart';

/// Central type scale. It intentionally uses Flutter's platform-default font so
/// builds do not depend on runtime font downloads and render consistently in
/// offline/demo environments.
class AppTextStyles {
  static const TextStyle displayMd = TextStyle(
    fontSize: 32, fontWeight: FontWeight.w700, color: AppColors.textPrimary,
  );

  static const TextStyle headlineSm = TextStyle(
    fontSize: 24, fontWeight: FontWeight.w700, color: AppColors.textPrimary,
  );

  static const TextStyle h2 = TextStyle(
    fontSize: 20, fontWeight: FontWeight.w600, color: AppColors.textPrimary,
  );

  static const TextStyle bodyLg = TextStyle(
    fontSize: 16, fontWeight: FontWeight.w400, color: AppColors.textPrimary,
  );

  static const TextStyle bodyMd = TextStyle(
    fontSize: 14, fontWeight: FontWeight.w400, color: AppColors.textPrimary,
  );

  static const TextStyle bodySm = TextStyle(
    fontSize: 12, fontWeight: FontWeight.w400, color: AppColors.textSecondary,
  );

  static const TextStyle labelMd = TextStyle(
    fontSize: 11, fontWeight: FontWeight.w600, letterSpacing: 0.5,
    color: AppColors.textSecondary,
  );

  static const TextStyle stat = TextStyle(
    fontSize: 36, fontWeight: FontWeight.w700, color: AppColors.primary,
  );
}
