import 'dart:io';

import 'package:flutter/material.dart';

class ScanPreviewImage extends StatelessWidget {
  final String imagePath;

  const ScanPreviewImage({super.key, required this.imagePath});

  @override
  Widget build(BuildContext context) {
    return Image.file(
      File(imagePath),
      fit: BoxFit.cover,
      width: double.infinity,
    );
  }
}
