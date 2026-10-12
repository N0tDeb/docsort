# DocSort — Final-Year Project Pitch

## One-line description

**DocSort is an intelligent document processing and management system that combines OCR, generative AI, automatic classification, human verification, search, and analytics in one workflow.**

## 1. The problem

Organizations receive documents in many formats: invoices, receipts, resumes, contracts, certificates, application forms, identity documents, and reports. Manual data entry and filing are slow, inconsistent, difficult to search, and hard to audit.

## 2. The solution

DocSort turns a scanned or uploaded PDF/image into a structured, searchable record:

1. The source file is stored securely.
2. OCR extracts text.
3. Generative AI proposes the document type and structured fields.
4. Auto-sort places the document into a relevant folder such as Finance, Human Resources, Legal, Applications, or Reports.
5. A human reviews and corrects the AI result before the record is marked **Verified**.
6. Verified records can be searched, exported, analyzed, and shared with time-limited secure links.

## 3. Why the project is technically interesting

DocSort combines multiple IT and computer-science areas in one coherent system:

- Flutter mobile/cross-platform frontend
- FastAPI backend and REST APIs
- PostgreSQL/Supabase persistence and object storage
- Tesseract OCR
- Generative-AI structured extraction
- SHA-256 integrity and duplicate detection
- Authentication and role/department authorization
- Human-in-the-loop verification
- Search, analytics, export, and secure sharing
- Automated backend regression tests

## 4. Human-in-the-loop design

DocSort does not present AI output as automatically correct. New documents enter **Needs Review**. A reviewer can correct the document type and extracted fields; only then is the record marked **Verified**. OCR confidence, anomaly flags, and review status are shown as separate concepts.

## 5. Suggested live demo

1. Upload an **Invoice**.
2. Show the five processing stages: integrity/duplicate check, secure storage, OCR + AI extraction, anomaly check, and classification/filing.
3. Show the proposed invoice fields and **Needs Review** status.
4. Correct one field or the document type and save the review.
5. Show the record as **Verified** in the cabinet.
6. Search for the vendor or invoice number.
7. Open Analytics to show the document reflected in the organization metrics.
8. Upload the same file again to demonstrate owner-scoped duplicate reuse.
9. Optionally create a secure time-limited share link or show the experimental People Map with a person-centric document.

## 6. What not to overclaim

- OCR confidence is not the same as classification accuracy.
- A potential identity match is not proof of fraud.
- The current project is a final-year prototype, not a large-scale enterprise SaaS platform.
- The People & Document Map is experimental and optional; the core contribution is the intelligent document workflow.

## 7. Evaluation story

DocSort includes a reproducible evaluation framework (`docs/EVALUATION.md` and `docsort-backend/evaluation/`). It can measure classification accuracy, field precision/recall/F1, strict field-document matching, OCR character/word error rates, human correction rates, recorded processing latency, and search latency. Results remain **TBD** until a labelled dataset and timed benchmark are actually run; do not invent percentages for the presentation.
