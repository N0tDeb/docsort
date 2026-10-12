# DocSort Academic Evaluation Guide

This guide defines a reproducible evaluation procedure for the final-year project. It intentionally separates **measured evidence** from model confidence scores and demo impressions. Do not report a percentage until it has been produced from a labelled dataset or a timed benchmark run.

## 1. Evaluation questions

DocSort should be evaluated on five independent questions:

1. **Document classification** — Did the system assign the correct document type?
2. **Structured field extraction** — Did it recover the correct labelled values?
3. **OCR transcription quality** — How different is OCR text from a human transcription?
4. **Human correction burden** — How often did reviewers change the initial system output?
5. **Runtime performance** — How long did document processing and search take in the stated test environment?

OCR confidence is **not** classification accuracy, extraction accuracy, or verification status.

## 2. Recommended dataset

For a final-year evaluation, use a labelled sample large enough to cover the supported categories. A practical target is **50–100 documents**, distributed as evenly as reasonably possible across categories such as:

- Invoice
- Receipt
- Resume
- Contract
- Certificate
- Application Form
- Identity Document
- Report

Record the exact category counts in the report. If the dataset is smaller or imbalanced, say so rather than presenting the result as broadly representative.

Use documents you are permitted to evaluate. Remove or anonymize unnecessary personal information. Do not commit private evaluation documents, OCR text, JWTs, or raw evaluation records containing sensitive information to the public repository.

If prompts, mapping rules, or extraction logic are tuned using some documents, keep a separate evaluation set where possible. Do not repeatedly tune against the same records and then describe that score as an unbiased test result.

## 3. Evidence record format

The machine-readable contract is:

`docsort-backend/evaluation/evaluation_record.schema.json`

Use one JSON object per line (`.jsonl`). Each record has three conceptually different snapshots:

```json
{
  "id": "dataset-document-id",
  "ground_truth": {
    "doc_type": "Invoice",
    "raw_text": "Human transcription when OCR evaluation is required",
    "fields": {
      "Invoice Number": "INV-001",
      "Vendor Name": "Example Vendor"
    }
  },
  "prediction": {
    "doc_type": "Invoice",
    "raw_text": "Initial OCR output captured before human review",
    "fields": [
      {"label": "Invoice Number", "value": "INV-001"},
      {"label": "Vendor Name", "value": "Example Vendor"}
    ]
  },
  "reviewed": {
    "doc_type": "Invoice",
    "fields": {
      "Invoice Number": "INV-001",
      "Vendor Name": "Example Vendor"
    }
  },
  "timings": {
    "processing_ms": 0,
    "duplicate_reused": false
  }
}
```

The values above illustrate the **record shape only**. They are not DocSort evaluation results.

### Snapshot meanings

- `ground_truth`: independent human-labelled expected result.
- `prediction`: initial DocSort output captured **before** the reviewer changes anything.
- `reviewed`: the final value after the normal human-review workflow. This measures correction burden; it is not automatically the same as independent ground truth.
- `timings.processing_ms`: real processing duration from the upload-job `progress.processing_ms` field.
- `timings.duplicate_reused`: copy the upload-job `progress.duplicate_reused` flag when present. Duplicate reuse skips OCR/AI and is therefore excluded from model-quality and full-processing-latency metrics; its latency is reported separately.

Do not replace a missing measurement with zero. Omit evidence that was not collected.

## 4. Metric definitions

### Classification accuracy

`correct predicted document types / labelled documents`

Comparison is case-insensitive and whitespace-normalized. No synonym mapping is silently applied, so the dataset should use one consistent label vocabulary.

### Field extraction

Fields are compared by normalized label and exact normalized value.

The evaluator reports:

- **Precision** = correct extracted fields / predicted fields
- **Recall** = correct extracted fields / ground-truth fields
- **F1** = harmonic mean of precision and recall
- **Strict document match rate** = documents whose complete predicted field map exactly equals ground truth

This is intentionally stricter than comparing only fields that happened to be predicted.

### OCR quality

When `ground_truth.raw_text` and `prediction.raw_text` are supplied, the evaluator reports:

- **Character Error Rate (CER)** = character edit distance / ground-truth characters
- **Word Error Rate (WER)** = word edit distance / ground-truth words

Human transcription quality therefore affects these measurements and should be checked carefully.

### Human correction rate

The evaluator compares `prediction` with `reviewed` and reports:

- percentage of reviewed documents changed at least once,
- document-type correction rate,
- extracted-field slot correction rate.

This measures reviewer workload. It does **not** prove the reviewed value is objectively correct; use `ground_truth` for independent correctness.

### Processing latency

The upload pipeline records elapsed processing time in:

`upload_jobs.progress.processing_ms`

The evaluator reports sample count, mean, median, p95, minimum, and maximum. Records marked `timings.duplicate_reused = true` are automatically excluded from classification, extraction, OCR, review-correction, and full-processing-latency metrics because they did not exercise a fresh OCR/AI prediction. Their latency is summarized separately as `duplicate_reuse_latency_ms`.

### Search response time

Use the supplied benchmark tool with a fixed query set. Report sample count, mean, median, p95, minimum, and maximum. State dataset size, server/device environment, whether the first request was warmed up, and whether the database was local or remote.

## 5. Running dataset evaluation

From `docsort-backend`:

```bash
python evaluation/evaluate_dataset.py evaluation/data/evaluation.jsonl \
  --output evaluation/results/metrics.json
```

The evaluator prints aggregate JSON and optionally writes it to the requested output path. It never invents a score for a metric with no eligible evidence; such values are returned as `null` with an evaluated count of zero.

## 6. Running the search benchmark

Create a text file with one fixed query per line. Use queries chosen **before** timing so results are not selected for speed.

Set a JWT for a dedicated non-production evaluation account:

```bash
export DOCSORT_EVAL_TOKEN="<test-user-jwt>"
```

Then run:

```bash
python evaluation/benchmark_search.py \
  --base-url http://127.0.0.1:8000 \
  --queries evaluation/data/search_queries.txt \
  --iterations 5 \
  --warmup 1 \
  --output evaluation/results/search_latency.json
```

The token is read only from the environment and is never written to the benchmark output.

## 7. Suggested experimental procedure

1. Freeze the DocSort code/configuration used for evaluation.
2. Record software version, machine specifications, database location, Tesseract version, and AI model configuration.
3. Prepare and label the evaluation set before inspecting aggregate scores.
4. Upload each document using the same language/type-hint policy.
5. Capture the initial `prediction` before manual correction.
6. Capture `progress.processing_ms` from the completed upload job.
7. Perform normal human review and record the final `reviewed` snapshot.
8. Run `evaluate_dataset.py` over all collected records.
9. Run the search benchmark against a fixed populated database and fixed query list.
10. Include raw sample counts with every reported rate and discuss limitations.

## 8. Reporting template

Use a table like this in the final report **after measurements exist**:

| Metric | Result | Samples | Notes |
|---|---:|---:|---|
| Classification accuracy | TBD | TBD | Label distribution reported separately |
| Field precision | TBD | TBD fields | Exact normalized value match |
| Field recall | TBD | TBD fields | Exact normalized value match |
| Field F1 | TBD | TBD fields | — |
| Strict field document match | TBD | TBD docs | All fields must match |
| OCR CER | TBD | TBD docs | Requires human transcription |
| OCR WER | TBD | TBD docs | Requires human transcription |
| Documents needing correction | TBD | TBD reviewed docs | Prediction vs reviewed |
| Processing median / p95 | TBD | TBD jobs | Full processing only unless stated |
| Search median / p95 | TBD | TBD requests | Fixed queries and environment |

`TBD` is intentional until a real experiment has been run.

## 9. Interpretation cautions

- OCR confidence is the normalized mean of valid Tesseract word confidences; even a high value is not ground-truth OCR accuracy.
- Auto-sort confidence is a routing score, not classification accuracy.
- A correct document type does not imply all fields are correct.
- Human correction rate measures workload, not independent correctness.
- A small private dataset does not establish production-scale performance.
- API/search latency depends strongly on network and database placement.
- Generative-AI outputs can vary; record the model/configuration and repeat the evaluation when reproducibility matters.
