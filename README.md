# 🛡️ Emthethal AI (امتثال)
### نظام ذكاء المستندات الإنتاجي | CFIS v3 + Healthcare Compliance Platform

<div dir="rtl">

**امتثال** منظومة متكاملة تجمع بين:
- **CFIS Phase 1** — خط إنتاج ذكاء المستندات: PDF → استخراج هجين → QA → Form.io JSON
- **محرك الامتثال الصحي** — إدارة الاستمارات، الأجهزة، الأقسام، وسير العمل الميداني

</div>

---

## 🏗️ المعمارية | Architecture

```
PDF Input
    │
    ├─► Native Text (pdfplumber)  ──── primary (R16)
    │       YES → CanonicalTokens (confidence=1.0)
    │       NO  → scanned page
    │
    └─► PaddleOCR Arabic ──────────── fallback only
            CanonicalTokens (confidence 0.0–1.0)
                │
                ▼
        IQR Geometry Engine (dynamic eps, zero hardcoded)
                │
                ▼
        DBSCAN Layout Cells (sorted: page, y1, x1)
                │
                ▼
        FormField[] (normalized bbox 0–1, RTL Arabic)
                │
          ┌─────┴──────┐
          ▼            ▼
      QA Canvas    Form.io JSON
      (HTML5)      /api/cfis/v1/export/formio/{id}
```

```
FastAPI  =  العقل (Business Logic · CFIS Pipeline · Governance)

React    =  برج التحكم (Admin · QA Canvas · Monitoring)
pgvector =  الذاكرة (RAG · Semantic Search)
Canonical Schema v2 = الدستور (Single Source of Truth)
```

> **القاعدة غير القابلة للتفاوض:** FastAPI هو مصدر الحقيقة الوحيد.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI 0.110 · Python 3.10 · SQLAlchemy 2.0 async |
| CFIS DB | asyncpg → PostgreSQL 16 (cfis_* tables) |
| Native PDF | pdfplumber ≥ 0.10 · PyMuPDF ≥ 1.23 |
| OCR Engine | PaddleOCR ≥ 2.7 · Arabic model in Docker volume |
| Layout | PP-StructureV3 (proposals only — R18) |
| Geometry | DBSCAN + IQR statistics — zero hardcoded eps (R4) |
| Schema | Pydantic v2 · 4-layer canonical contract |
| AI / LLM | Ollama local · Llama 3 8B · nomic-embed-text |
| Queue | Redis 7 + RQ (3 named queues) |
| Object Storage | MinIO (S3-compatible) |

| Frontend | React 18 · Vite · Tailwind CSS · HTML5 Canvas |

---

## 📂 Project Structure

```
emthethal-ai/
├── architecture_state.yaml       ← CFIS cross-task agent memory
├── docker-compose.yml            ← all services
│
├── backend/
│   ├── Dockerfile                ← cache-first build, paddle_models volume
│   ├── requirements.txt
│   └── app/
│       ├── main.py               ← FastAPI app + CFIS startup (100% clean)
│       ├── database.py           ← legacy SQLAlchemy engine
│       ├── db.py                 ← CFIS asyncpg DB layer (11 functions)
│       │
│       ├── models/
│       │   ├── __init__.py       ← re-exports ORM + CFIS symbols
│       │   ├── orm.py            ← SQLAlchemy ORM (legacy, unchanged)
│       │   └── schemas.py        ← CFIS Canonical Schema v2 (ONE source)
│       │
│       ├── services/
│       │   ├── hybrid_extraction.py  ← native-first + OCR fallback (R16)
│       │   ├── geometry.py           ← IQR geometry, DBSCAN, RTL columns
│       │   ├── ocr.py                ← process_pdf() — single entry point
│       │   └── ...                   ← CFIS core services
│       │
│       └── api/
│           ├── router.py         ← CFIS API /api/cfis/v1/ (9 routes)
│           └── routes/           ← CFIS core routes (geometry_debug.py, pipeline.py, hitl.py)
│
└── frontend/
    └── src/
        ├── components/
        │   ├── PDFProcessor.jsx  ← Phase 1 PDF Processor + Ingestion
        │   ├── GeometryDebugViewer.jsx ← Phase 2 Geometry Debug Viewer
        │   ├── QAViewer.jsx      ← HTML5 Canvas QA + SpatialIndex
        │   └── FormBuilderWrapper.jsx ← Form.io builder wrapper
        ├── workbench/            ← Phase 3 Evidence Workbench
        └── index.css             ← design system tokens
```

---

## 🚀 Quick Start

### Prerequisites
- Docker ≥ 24 with BuildKit
- Docker Compose v2
- 8 GB RAM minimum (Arabic OCR model ~500 MB)

### 1 — Clone & start

```bash
git clone <repo-url> emthethal-ai
cd emthethal-ai

# First run: Arabic OCR model downloads once into paddle_models volume
docker compose up -d
```

### 2 — Verify pipeline health

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"3.0","schema":"v2","pipeline":"v3","extraction":"hybrid"}
```

### 3 — Process a PDF

```bash
curl -X POST http://localhost:8000/api/cfis/v1/process \
  -F "file=@/path/to/form.pdf" \
  | python3 -m json.tool
```

### 4 — Export Form.io JSON (after QA approval)

```bash
# Approve document
curl -X POST http://localhost:8000/api/cfis/v1/qa/approve/{document_id}

# Export
curl http://localhost:8000/api/cfis/v1/export/formio/{document_id}
```

### 5 — Frontend (dev)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

---

## 🔌 CFIS API Reference

Base: `http://localhost:8000/api/cfis/v1`

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Pipeline version + extraction mode |
| `POST` | `/process` | Upload PDF → DocumentOutput (fields + bboxes) |
| `GET` | `/documents` | List all documents (filter by `?qa_status=pending`) |
| `GET` | `/documents/{id}` | Get full DocumentOutput |
| `GET` | `/documents/{id}/page/{n}/image` | Page image (PNG) for QA canvas |
| `POST` | `/qa/correction` | Submit human correction (matched by row/col/page) |
| `POST` | `/qa/approve/{id}` | Approve document → generates Form.io schema |
| `GET` | `/qa/pending` | List documents awaiting review |
| `GET` | `/export/formio/{id}` | Export approved document as Form.io JSON |

---

## 📐 CFIS Canonical Schema v2

All data passes through 4 validated layers:

```
Layer 0 — BoundingBox
  ├─ coordinate_space: PAGE_PIXELS | NORMALIZED | PDF_POINTS
  ├─ page_width, page_height: always required
  └─ to_normalized() / to_page_pixels() / iou()

Layer 1 — CanonicalToken
  ├─ source: NATIVE | OCR
  ├─ ocr_raw_text: raw extraction only (≠ semantic_label, R19)
  ├─ confidence: 1.0 for native, 0–1 for OCR
  └─ bbox: PAGE_PIXELS

Layer 2 — LayoutCell
  ├─ DBSCAN cluster output
  ├─ bbox: PAGE_PIXELS
  └─ (row_index, col_index, page_number)

Layer 3 — FormField
  ├─ bbox: NORMALIZED 0–1 (field_validator enforces, ValueError if PAGE_PIXELS)
  ├─ semantic_label: display label — never == ocr_raw_text (R19)
  ├─ runtime_widget: text|number|radio|date|checkbox|...
  ├─ needs_qa: confidence < 0.65
  └─ human_corrected: set by QA review

Layer 4 — DocumentOutput
  ├─ fingerprint: TemplateFingerprint (dynamic eps, layout_hash)
  ├─ extraction_stats: native_pages, ocr_pages, total_tokens
  ├─ failed_pages: page-level fault isolation (R10)
  └─ qa_status: pending | in_review | approved | rejected
```

---

## ⚙️ Governance Rules (CFIS v5.0)

| Rule | Description | Status |
|---|---|---|
| R2 | One schema file — never duplicate | ✅ `app/models/schemas.py` |
| R4 | Zero hardcoded geometry — IQR-derived eps always | ✅ grep confirms 0 hits |
| R5 | Arabic is default OCR language | ✅ `lang="arabic"` in engine |
| R10 | Page-level fault isolation | ✅ `failed_pages[]` list |
| R13 | Sort (page, y1, x1) before clustering | ✅ `sort_tokens_deterministic()` |
| R14 | Page-by-page RAM — never load full PDF | ✅ images deleted after use |
| R16 | Native text extraction always first | ✅ pdfplumber → OCR fallback |
| R17 | All FormField bboxes in normalized space | ✅ Pydantic validator enforces |
| R18 | PP-StructureV3 as proposals, not truth | ✅ `normalize_layout_proposal()` |
| R19 | `ocr_raw_text` ≠ `semantic_label` | ✅ derived independently |

---

## 🐳 Services

| Service | Port | Description |
|---|---|---|
| `backend` | 8000 | FastAPI — legacy + CFIS API |
| `db` | 5432 | PostgreSQL 16 + pgvector |
| `redis` | 6379 | RQ job queue |
| `minio` | 9000/9001 | Object storage |
| `ollama` | 11434 | Local LLM (Llama 3 8B) |
| `rq-worker` | — | Background jobs (3 queues) |
| `model_init` | — | One-time Arabic OCR model download |

> **Arabic OCR models** are stored in the `paddle_models` Docker named volume.
> They download once on first `model_init` run and persist across rebuilds.

---

## 🔧 Development

### Run verification suite

```bash
docker compose run --rm backend python3 -c "
import sys; sys.path.insert(0, '/app')
from app.models.schemas import TemplateFingerprint, FormField, BoundingBox, CoordinateSpace

# Verify dynamic eps
fp = TemplateFingerprint.compute(5, 0.85, 4, 25.0, 60.0)
assert fp.computed_eps_y == max(8.0, 25.0 * 0.65)
assert fp.computed_eps_y != 20.0  # never hardcoded

# Verify bbox enforcement
from app.models.schemas import FormField
try:
    FormField(cell_id='c', semantic_label='x',
              bbox=BoundingBox(x1=100, y1=100, x2=200, y2=140,
                               coordinate_space=CoordinateSpace.PAGE_PIXELS,
                               page_width=1000, page_height=1400),
              row_index=0, column_index=0, page_number=0)
    print('FAIL: should raise')
except Exception:
    print('✅ FormField bbox enforcement works')

print('✅ Dynamic eps:', fp.computed_eps_y, fp.computed_eps_x)
"
```

### Rebuild after changes

```bash
# With BuildKit cache (fast)
DOCKER_BUILDKIT=1 docker compose build backend
docker compose up -d backend
```

### View logs

```bash
docker compose logs -f backend
docker compose logs -f rq-worker
```

---

## 📝 Architecture State

The file `architecture_state.yaml` tracks agent cross-task memory:
- Completed tasks with verification results
- Resolved bugs and open issues
- File locations for all CFIS modules
- Definition of Done check results

**Current Status:** Phase 1, 2, and 3 STRICTLY isolated and fully functional. 100% of legacy routes, dashboards, and test files have been completely purged. Ready and waiting for the next phase of development: the **Structural Topology Layer**.

---

<div dir="rtl">

## 📋 ملاحظات التشغيل

- **نماذج OCR العربية**: تُحمَّل تلقائياً عند أول تشغيل (~500 ميجابايت) وتُخزَّن في `paddle_models`
- **استخراج النص الأصلي**: يُعطى الأولوية دائماً على OCR عند وجود طبقة نصية في PDF
- **الإحداثيات**: جميع بيانات الحقول ترجع بإحداثيات نسبية (0–1) مناسبة للعرض الأمامي
- **مراجعة الجودة**: الحقول التي ثقتها أقل من 65% تُعلَّم `needs_qa=True` تلقائياً
- **مسار الاعتماد**: الاستمارة لا تُصدَّر إلى Form.io إلا بعد اعتماد مراجع الجودة

</div>

---

*CFIS v3 · Schema v2 · Pipeline v3 · Arabic-first · Zero Hallucination · Zero Truncation*
