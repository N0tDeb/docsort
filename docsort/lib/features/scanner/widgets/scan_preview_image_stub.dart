import 'package:flutter/material.dart';

/// Web/unsupported-platform fallback. The mobile scanner never produces a local
/// scan path on these platforms; keeping this widget available makes the route
/// tree compile safely everywhere.
class ScanPreviewImage extends StatelessWidget {
  final String imagePath;

  const ScanPreviewImage({super.key, required this.imagePath});

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Text(
          'Camera scan preview is available on Android and iOS. Use Upload File on this platform.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}
