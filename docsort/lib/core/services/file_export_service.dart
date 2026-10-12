import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

final fileExportServiceProvider = Provider<FileExportService>(
  (_) => FileExportService(),
);

class FileExportService {
  Future<void> download({
    required Dio dio,
    required String path,
    required String fallbackFileName,
    Map<String, dynamic>? queryParameters,
  }) async {
    final response = await dio.get<List<int>>(
      path,
      queryParameters: queryParameters,
      options: Options(responseType: ResponseType.bytes),
    );

    final raw = response.data;
    if (raw == null) {
      throw StateError('The server returned an empty export.');
    }

    final bytes = raw is Uint8List
        ? raw
        : Uint8List.fromList(List<int>.from(raw));

    final filename = _filenameFromHeaders(response.headers, fallbackFileName);

    await FilePicker.platform.saveFile(
      dialogTitle: 'Save file',
      fileName: filename,
      bytes: bytes,
    );
  }

  String _filenameFromHeaders(Headers headers, String fallback) {
    final value = headers.value('content-disposition');
    if (value == null || value.isEmpty) return fallback;

    final encoded = RegExp(
      "filename\\*=UTF-8''([^;]+)",
      caseSensitive: false,
    ).firstMatch(value);

    if (encoded != null) {
      try {
        return Uri.decodeComponent(encoded.group(1)!.trim());
      } catch (_) {}
    }

    final plain = RegExp(
      r'filename="?([^";]+)"?',
      caseSensitive: false,
    ).firstMatch(value);

    return plain?.group(1)?.trim() ?? fallback;
  }
}
