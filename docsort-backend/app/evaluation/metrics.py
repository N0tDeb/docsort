from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence
import re


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: Any) -> str:
    """Normalize text for reproducible exact-match evaluation.

    Evaluation deliberately performs only conservative normalization: trim,
    collapse whitespace, and case-fold. It does not silently rewrite dates,
    currencies, names, or identifiers because that could inflate scores.
    """
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value).strip()).casefold()


def _fields_to_map(fields: Any) -> dict[str, str]:
    if fields is None:
        return {}

    if isinstance(fields, Mapping):
        return {
            normalize_text(label): normalize_text(value)
            for label, value in fields.items()
            if normalize_text(label)
        }

    result: dict[str, str] = {}
    if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes, bytearray)):
        for item in fields:
            if not isinstance(item, Mapping):
                continue
            label = normalize_text(item.get("label"))
            if not label:
                continue
            result[label] = normalize_text(item.get("value"))
    return result


def _rate(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 6)


def _edit_distance(reference: Sequence[Any], hypothesis: Sequence[Any]) -> int:
    """Levenshtein distance using O(min(n, m)) memory."""
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for i, ref_item in enumerate(reference, start=1):
        current = [i]
        for j, hyp_item in enumerate(hypothesis, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (ref_item != hyp_item)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)


def summarize_latency(values_ms: Iterable[float]) -> dict[str, Any]:
    values = [float(v) for v in values_ms if v is not None and float(v) >= 0]
    if not values:
        return {
            "samples": 0,
            "mean_ms": None,
            "median_ms": None,
            "p95_ms": None,
            "min_ms": None,
            "max_ms": None,
        }
    return {
        "samples": len(values),
        "mean_ms": round(mean(values), 3),
        "median_ms": round(median(values), 3),
        "p95_ms": _percentile(values, 0.95),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
    }


def evaluate_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate a versioned DocSort JSONL dataset.

    Each record may contain `ground_truth`, `prediction`, `reviewed`, and
    `timings`. Missing evidence simply leaves that metric unevaluated; it is
    never converted into a fabricated zero score.
    """
    classification_total = 0
    classification_correct = 0
    confusion: dict[str, Counter[str]] = defaultdict(Counter)

    gt_field_total = 0
    predicted_field_total = 0
    correct_fields = 0
    strict_field_docs = 0
    field_docs = 0

    reviewed_docs = 0
    corrected_docs = 0
    reviewed_field_slots = 0
    corrected_field_slots = 0
    reviewed_classifications = 0
    corrected_classifications = 0

    ocr_docs = 0
    char_distance = 0
    char_reference_length = 0
    word_distance = 0
    word_reference_length = 0

    processing_latencies: list[float] = []
    duplicate_latencies: list[float] = []
    duplicate_reused_excluded = 0

    for record in records:
        ground_truth = record.get("ground_truth") or {}
        prediction = record.get("prediction") or {}
        reviewed = record.get("reviewed") or {}
        timings = record.get("timings") or {}
        duplicate_reused = bool(timings.get("duplicate_reused"))

        processing_ms = timings.get("processing_ms")
        numeric_processing_ms = None
        if processing_ms is not None:
            try:
                numeric_processing_ms = float(processing_ms)
            except (TypeError, ValueError):
                numeric_processing_ms = None

        if duplicate_reused:
            # Exact duplicate reuse does not exercise OCR/AI/classification and
            # therefore must not inflate model-quality metrics or full-pipeline
            # latency. Report its latency separately instead.
            duplicate_reused_excluded += 1
            if numeric_processing_ms is not None and numeric_processing_ms >= 0:
                duplicate_latencies.append(numeric_processing_ms)
            continue

        expected_type = normalize_text(ground_truth.get("doc_type"))
        predicted_type = normalize_text(prediction.get("doc_type"))
        if expected_type:
            classification_total += 1
            predicted_label = predicted_type or "<missing>"
            confusion[expected_type][predicted_label] += 1
            if predicted_type == expected_type:
                classification_correct += 1

        expected_fields = _fields_to_map(ground_truth.get("fields"))
        predicted_fields = _fields_to_map(prediction.get("fields"))
        if expected_fields:
            field_docs += 1
            gt_field_total += len(expected_fields)
            predicted_field_total += len(predicted_fields)
            correct_fields += sum(
                1
                for label, expected_value in expected_fields.items()
                if label in predicted_fields and predicted_fields[label] == expected_value
            )
            if predicted_fields == expected_fields:
                strict_field_docs += 1

        if reviewed:
            reviewed_docs += 1
            reviewed_type = normalize_text(reviewed.get("doc_type"))
            prediction_type_for_review = normalize_text(prediction.get("doc_type"))
            type_changed = False
            if reviewed_type:
                reviewed_classifications += 1
                type_changed = reviewed_type != prediction_type_for_review
                if type_changed:
                    corrected_classifications += 1

            reviewed_fields = _fields_to_map(reviewed.get("fields"))
            predicted_review_fields = _fields_to_map(prediction.get("fields"))
            labels = set(reviewed_fields) | set(predicted_review_fields)
            field_changes = sum(
                1
                for label in labels
                if reviewed_fields.get(label, "") != predicted_review_fields.get(label, "")
            )
            reviewed_field_slots += len(labels)
            corrected_field_slots += field_changes
            if type_changed or field_changes:
                corrected_docs += 1

        reference_text = ground_truth.get("raw_text")
        predicted_text = prediction.get("raw_text")
        if reference_text is not None and predicted_text is not None:
            normalized_reference = normalize_text(reference_text)
            normalized_prediction = normalize_text(predicted_text)
            if normalized_reference:
                ocr_docs += 1
                char_distance += _edit_distance(normalized_reference, normalized_prediction)
                char_reference_length += len(normalized_reference)
                reference_words = normalized_reference.split()
                predicted_words = normalized_prediction.split()
                word_distance += _edit_distance(reference_words, predicted_words)
                word_reference_length += len(reference_words)

        if numeric_processing_ms is not None and numeric_processing_ms >= 0:
            processing_latencies.append(numeric_processing_ms)

    field_precision = _rate(correct_fields, predicted_field_total)
    field_recall = _rate(correct_fields, gt_field_total)
    if field_precision is None or field_recall is None or (field_precision + field_recall) == 0:
        field_f1 = None if field_precision is None or field_recall is None else 0.0
    else:
        field_f1 = round(2 * field_precision * field_recall / (field_precision + field_recall), 6)

    confusion_serialized = {
        expected: dict(sorted(predicted_counts.items()))
        for expected, predicted_counts in sorted(confusion.items())
    }

    return {
        "dataset": {
            "records": len(records),
            "duplicate_reused_excluded": duplicate_reused_excluded,
        },
        "classification": {
            "evaluated": classification_total,
            "correct": classification_correct,
            "accuracy": _rate(classification_correct, classification_total),
            "confusion_matrix": confusion_serialized,
        },
        "field_extraction": {
            "documents_evaluated": field_docs,
            "ground_truth_fields": gt_field_total,
            "predicted_fields": predicted_field_total,
            "correct_fields": correct_fields,
            "precision": field_precision,
            "recall": field_recall,
            "f1": field_f1,
            "strict_document_match_rate": _rate(strict_field_docs, field_docs),
        },
        "human_review": {
            "documents_reviewed": reviewed_docs,
            "documents_changed": corrected_docs,
            "document_correction_rate": _rate(corrected_docs, reviewed_docs),
            "classification_reviews": reviewed_classifications,
            "classification_changes": corrected_classifications,
            "classification_correction_rate": _rate(
                corrected_classifications, reviewed_classifications
            ),
            "field_slots_reviewed": reviewed_field_slots,
            "field_slots_changed": corrected_field_slots,
            "field_correction_rate": _rate(corrected_field_slots, reviewed_field_slots),
        },
        "ocr": {
            "documents_evaluated": ocr_docs,
            "character_error_rate": _rate(char_distance, char_reference_length),
            "word_error_rate": _rate(word_distance, word_reference_length),
        },
        "processing_latency_ms": summarize_latency(processing_latencies),
        "duplicate_reuse_latency_ms": summarize_latency(duplicate_latencies),
    }
