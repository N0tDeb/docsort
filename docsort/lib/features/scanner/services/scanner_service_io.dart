import 'package:cunning_document_scanner/cunning_document_scanner.dart';
import 'package:flutter/services.dart';

/// Android/iOS camera scanner implementation.
class ScannerService {
  Future<List<String>?> scanDocument() async {
    try {
      return await CunningDocumentScanner.getPictures();
    } on PlatformException {
      return null;
    } catch (_) {
      return null;
    }
  }
}
