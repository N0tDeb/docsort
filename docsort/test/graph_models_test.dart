import 'package:docsort/features/graph/domain/graph_models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('People Map models', () {
    test('preserves normalized OCR confidence as a double', () {
      final document = CitizenDocument.fromJson({
        'document_id': 'doc-1',
        'type': 'Identity Document',
        'value': 'ID-123',
        'confidence': 0.93,
        'is_tampered': false,
        'filename': 'identity.pdf',
      });

      expect(document.confidence, closeTo(0.93, 0.0001));
    });

    test('uses potential-match wording for duplicate identity edges', () {
      final edge = GraphEdge.fromJson({
        'id': 'edge-1',
        'from_citizen': 'person-1',
        'to_citizen': 'person-2',
        'edge_type': 'duplicate_of',
        'confidence': 0.9,
      });

      expect(edge.label, 'potential match');
      expect(edge.isDashed, isTrue);
    });

    test('empty graph contains no fabricated people or edges', () {
      final graph = IdentityGraph.empty();

      expect(graph.nodes, isEmpty);
      expect(graph.edges, isEmpty);
    });
  });
}
