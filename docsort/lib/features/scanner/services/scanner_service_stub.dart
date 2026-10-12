/// Fallback used by Flutter Web and other platforms without the mobile camera
/// scanner. The UI routes users to the normal file uploader on these targets.
class ScannerService {
  Future<List<String>?> scanDocument() async => null;
}
