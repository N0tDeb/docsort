double clampConfidence(Object? raw, {double fallback = 0.0}) {
  final value = raw is num ? raw.toDouble() : fallback;
  if (!value.isFinite) {
    final safeFallback = fallback.isFinite ? fallback : 0.0;
    return safeFallback.clamp(0.0, 1.0).toDouble();
  }
  return value.clamp(0.0, 1.0).toDouble();
}
