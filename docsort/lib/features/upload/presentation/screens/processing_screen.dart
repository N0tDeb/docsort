import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_text_styles.dart';
import '../../../../core/network/dio_client.dart';
import '../providers/upload_provider.dart';
import '../providers/review_cache_provider.dart';

import '../../../home/presentation/providers/home_provider.dart';
import '../../../cabinet/presentation/providers/cabinet_provider.dart';

class ProcessingScreen extends ConsumerStatefulWidget {
  final String? jobId;

  const ProcessingScreen({super.key, this.jobId});

  @override
  ConsumerState<ProcessingScreen> createState() => _ProcessingScreenState();
}

class _ProcessingScreenState extends ConsumerState<ProcessingScreen>
    with TickerProviderStateMixin {
  Timer? _timer;
  late AnimationController _pulseController;
  int _pollCount = 0;

  final List<String> _steps = [
    'Integrity & Duplicate Check',
    'Secure File Storage',
    'OCR & AI Extraction',
    'Anomaly Check',
    'Classification & Filing',
  ];

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..repeat(reverse: true);

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;

      final routeJobId = widget.jobId?.trim();
      final current = ref.read(uploadProvider);

      if (current.jobId == null &&
          routeJobId != null &&
          routeJobId.isNotEmpty) {
        ref.read(uploadProvider.notifier).resumeJob(routeJobId);
      }

      if (ref.read(uploadProvider).jobId != null) {
        _scheduleNextPoll();
      }
    });
  }

  // Adaptive polling: fast initially, then normal after three polls.
  void _scheduleNextPoll() {
    final delay = _pollCount < 3
        ? const Duration(milliseconds: 800)
        : const Duration(seconds: 2);

    _timer = Timer(delay, () async {
      _pollCount++;
      await ref.read(uploadProvider.notifier).pollStatus();
      if (mounted) _scheduleNextPoll();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(uploadProvider);

    // Navigate when done
    ref.listen<UploadState>(uploadProvider, (prev, next) async {
      if (next.status == UploadStatus.done && next.documentId != null) {
        _timer?.cancel();
        ref.invalidate(homeProvider);
        ref.invalidate(cabinetListProvider);

        // Pre-fetch the document and store it in cache so ReviewScreen
        // can read it instantly without making a second API call.
        try {
          final dio = ref.read(dioProvider);
          final res = await dio.get('/cabinet/documents/${next.documentId}');
          ref
              .read(reviewDocCacheProvider.notifier)
              .setDoc(Map<String, dynamic>.from(res.data as Map));
        } catch (_) {
          // Cache miss is fine Ã¢â‚¬â€ ReviewScreen will fall back to network.
        }

        if (!context.mounted) return;
        final msg = (next.errorMessage ?? '').toLowerCase();
        final isDup = msg.contains('duplicate');
        if (isDup) {
          context.go('/review/${next.documentId}?dup=true');
        } else {
          context.go('/review/${next.documentId}');
        }
      }
      if (next.status == UploadStatus.error) {
        _timer?.cancel();
      }
    });

    final progress = state.progress;
    final currentStep = state.currentStep;
    final routeJobId = widget.jobId?.trim();
    final hasJob =
        state.jobId != null || (routeJobId != null && routeJobId.isNotEmpty);

    if (!hasJob && state.status == UploadStatus.idle) {
      return Scaffold(
        backgroundColor: AppColors.background,
        body: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(28),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.info_outline_rounded, size: 72),
                  const SizedBox(height: 20),
                  Text(
                    'No processing job found',
                    style: AppTextStyles.displayMd,
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'This processing session cannot be resumed. Start a new upload.',
                    textAlign: TextAlign.center,
                    style: AppTextStyles.bodyMd.copyWith(
                      color: AppColors.textSecondary,
                    ),
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton(
                    onPressed: () => context.go('/upload'),
                    child: const Text('Back to Upload'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    if (state.status == UploadStatus.error) {
      return Scaffold(
        backgroundColor: AppColors.background,
        body: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(28),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.error_outline_rounded,
                    size: 72,
                    color: AppColors.error,
                  ),
                  const SizedBox(height: 20),
                  Text('Processing failed', style: AppTextStyles.displayMd),
                  const SizedBox(height: 12),
                  Text(
                    state.errorMessage ??
                        'DocSort could not process this document.',
                    textAlign: TextAlign.center,
                    style: AppTextStyles.bodyMd.copyWith(
                      color: AppColors.textSecondary,
                    ),
                  ),
                  const SizedBox(height: 24),
                  if (state.sourceFilePath != null)
                    ElevatedButton.icon(
                      onPressed: () async {
                        final ok = await ref
                            .read(uploadProvider.notifier)
                            .uploadDocument(state.sourceFilePath!);
                        if (ok && mounted) {
                          _pollCount = 0;
                          _scheduleNextPoll();
                        }
                      },
                      icon: const Icon(Icons.refresh_rounded),
                      label: const Text('Retry Processing'),
                    ),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: () {
                      ref.read(uploadProvider.notifier).reset();
                      context.go('/upload');
                    },
                    child: const Text('Back to Upload'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 40),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header
              Text('Analyzing Document', style: AppTextStyles.displayMd),
              const SizedBox(height: 8),
              Text(
                'DocSort is processing your scan. This takes a few seconds.',
                style: AppTextStyles.bodyLg.copyWith(
                  color: AppColors.textSecondary,
                ),
              ),
              const SizedBox(height: 40),

              // Overall progress bar
              Row(
                children: [
                  Expanded(
                    child: TweenAnimationBuilder<double>(
                      tween: Tween(begin: 0.0, end: progress),
                      duration: const Duration(milliseconds: 600),
                      curve: Curves.easeOut,
                      builder: (context, value, _) {
                        return ClipRRect(
                          borderRadius: BorderRadius.circular(8),
                          child: LinearProgressIndicator(
                            value: value,
                            minHeight: 8,
                            backgroundColor: AppColors.outlineVariant
                                .withValues(alpha: 0.3),
                            valueColor: AlwaysStoppedAnimation<Color>(
                              AppColors.primary,
                            ),
                          ),
                        );
                      },
                    ),
                  ),
                  const SizedBox(width: 12),
                  Text(
                    '${(progress * 100).toInt()}%',
                    style: AppTextStyles.bodyMd.copyWith(
                      color: AppColors.primary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 40),

              // Step list
              Expanded(
                child: ListView.builder(
                  itemCount: _steps.length,
                  itemBuilder: (ctx, i) {
                    final stepNumber = i + 1;
                    final isDone =
                        currentStep > stepNumber ||
                        state.status == UploadStatus.done;
                    final isActive = currentStep == stepNumber;

                    return _StepTile(
                      label: _steps[i],
                      isDone: isDone,
                      isActive: isActive,
                      pulseController: _pulseController,
                    );
                  },
                ),
              ),

              // Cancel button
              Center(
                child: TextButton(
                  onPressed: () {
                    ref.read(uploadProvider.notifier).reset();
                    context.go('/upload');
                  },
                  child: Text(
                    'Cancel',
                    style: AppTextStyles.bodyMd.copyWith(
                      color: AppColors.textSecondary,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StepTile extends StatelessWidget {
  final String label;
  final bool isDone;
  final bool isActive;
  final AnimationController pulseController;

  const _StepTile({
    required this.label,
    required this.isDone,
    required this.isActive,
    required this.pulseController,
  });

  @override
  Widget build(BuildContext context) {
    final Widget icon;

    if (isDone) {
      icon = const Icon(
        Icons.check_circle_rounded,
        color: AppColors.success,
        size: 26,
      );
    } else if (isActive) {
      icon = AnimatedBuilder(
        animation: pulseController,
        builder: (_, _) => Container(
          width: 26,
          height: 26,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: AppColors.primary.withValues(
              alpha: 0.2 + 0.5 * pulseController.value,
            ),
          ),
          child: Center(
            child: Container(
              width: 12,
              height: 12,
              decoration: const BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.primary,
              ),
            ),
          ),
        ),
      );
    } else {
      icon = Container(
        width: 26,
        height: 26,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(color: AppColors.outlineVariant, width: 1.5),
        ),
      );
    }

    return AnimatedContainer(
      duration: const Duration(milliseconds: 400),
      margin: const EdgeInsets.only(bottom: 20),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        color: isActive
            ? AppColors.primary.withValues(alpha: 0.06)
            : isDone
            ? AppColors.success.withValues(alpha: 0.04)
            : AppColors.surfaceLowest,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: isActive
              ? AppColors.primary.withValues(alpha: 0.3)
              : isDone
              ? AppColors.success.withValues(alpha: 0.3)
              : AppColors.outlineVariant.withValues(alpha: 0.2),
        ),
      ),
      child: Row(
        children: [
          icon,
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              label,
              style: AppTextStyles.bodyMd.copyWith(
                color: isDone
                    ? AppColors.success
                    : isActive
                    ? AppColors.primary
                    : AppColors.textSecondary,
                fontWeight: isActive || isDone
                    ? FontWeight.w600
                    : FontWeight.w400,
              ),
            ),
          ),
          if (isActive)
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation<Color>(AppColors.primary),
              ),
            ),
        ],
      ),
    );
  }
}
