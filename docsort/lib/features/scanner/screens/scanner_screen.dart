import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_text_styles.dart';
import '../providers/scanner_provider.dart';

class ScannerScreen extends ConsumerStatefulWidget {
  const ScannerScreen({super.key});

  @override
  ConsumerState<ScannerScreen> createState() => _ScannerScreenState();
}

class _ScannerScreenState extends ConsumerState<ScannerScreen> with SingleTickerProviderStateMixin {
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;
  bool _isLaunching = false;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..repeat(reverse: true);

    _pulseAnimation = Tween<double>(begin: 1.0, end: 1.15).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );

    // The camera scanner plugin supports Android/iOS. Web keeps the same route
    // tree but offers the regular file uploader instead of invoking the plugin.
    if (!kIsWeb) {
      Future.delayed(const Duration(milliseconds: 200), _launchScanner);
    }
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  Future<void> _launchScanner() async {
    if (kIsWeb) {
      if (mounted) context.pushReplacement('/upload');
      return;
    }
    if (_isLaunching) return;
    setState(() => _isLaunching = true);

    final success = await ref.read(scannerProvider.notifier).startScan();

    if (mounted) {
      if (success) {
        context.pushReplacement('/scan/preview');
      } else {
        // User cancelled or error, go back
        if (context.canPop()) context.pop();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: const Text('AI Document Scanner', style: TextStyle(fontWeight: FontWeight.bold, color: AppColors.textPrimary)),
        iconTheme: const IconThemeData(color: AppColors.textPrimary),
      ),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Stack(
              alignment: Alignment.center,
              children: [
                ScaleTransition(
                  scale: _pulseAnimation,
                  child: Container(
                    width: 160,
                    height: 160,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: AppColors.primary.withValues(alpha: 0.1),
                    ),
                  ),
                ),
                ScaleTransition(
                  scale: _pulseAnimation,
                  child: Container(
                    width: 120,
                    height: 120,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: AppColors.primary.withValues(alpha: 0.2),
                    ),
                  ),
                ),
                Container(
                  width: 80,
                  height: 80,
                  decoration: const BoxDecoration(
                    shape: BoxShape.circle,
                    color: AppColors.primary,
                  ),
                  child: const Center(
                    child: Icon(Icons.document_scanner_rounded, color: Colors.white, size: 40),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 48),
            Text(kIsWeb ? 'Camera scanning is mobile-only' : 'Initializing Scanner Engine...', style: AppTextStyles.h2),
            const SizedBox(height: 12),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 40),
              child: Text(
                kIsWeb ? 'Use the file uploader to choose a PDF, PNG, JPG, or JPEG document.' : 'Please align your document within the frame in good lighting.',
                textAlign: TextAlign.center,
                style: AppTextStyles.bodyMd.copyWith(color: AppColors.textSecondary),
              ),
            ),
            const SizedBox(height: 40),
            if (!_isLaunching)
              ElevatedButton.icon(
                onPressed: _launchScanner,
                icon: const Icon(Icons.camera_alt_rounded),
                label: Text(kIsWeb ? 'Choose File' : 'Open Camera Now'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.primary,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
