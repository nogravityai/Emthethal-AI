# 🚀 Emthethal AI — Handover Prompt: Semantic Zones Frontend Integration (CFIS Core v5.2)

## 📍 Current Status
We are in the process of porting the backend's new **CFIS Core v5.2 Semantic Zones** capabilities to the frontend **Evidence Workbench** interface, allowing users to view, draw, resize, rename, and delete zones.

The backend implementation (models, routes, dynamic generation in `TopologyStage`, and registry operations) is fully ready and passes all regression test suites (11/11 tests in the v5.2 suite and 6/6 tests in the standard suite).

The frontend components (`workbenchStore.js`, `LeftPanel.jsx`, `DocumentViewer.jsx`, and `RightPanel.jsx`) have been modified to support:
1. Drawing and selecting rose-colored `#F43F5E` zones on the canvas.
2. Editing labels/types and deleting zones under the **HITL Editor** tab in the Right Panel.
3. Proper relationship focus dimming for zones.

*Note: The user discarded the latest modifications to the four frontend files (`DocumentViewer.jsx`, `LeftPanel.jsx`, `RightPanel.jsx`, `workbenchStore.js`) and wants you to re-apply the correct logic cleanly.*

---

## ⚠️ Identified Technical Issues & Fixes

During integration, we discovered why some layers (such as OCR and geometry) do not show up when uploading scanned PDFs:

1. **OCR Engine Missing on Port 8000**:
   - The frontend dev proxy in `vite.config.js` points to `http://localhost:8000` (which is the legacy `emthethal_backend` container).
   - This container does **not** have the `paddleocr` libraries installed. When a scanned PDF is uploaded, it forces an OCR fallback but logs: `OCR engine unavailable — page 0 skipped`, resulting in 0 OCR tokens, 0 alignments, and 0 resolved fields.
   - **Fix**: The proxy in `vite.config.js` should target `http://localhost:8001` (the new `cfis_api` container, which has `paddleocr` fully installed and functional).

2. **`cfis_api` Database Configuration Bug**:
   - In `docker-compose.yml`, the environment variable `DATABASE_URL` fallback for the `api` service (port 8001) is set to `postgresql://cfis:cfis@db:5432/cfis`.
   - SQLAlchemy's `create_async_engine` fails on startup with `sqlalchemy.exc.InvalidRequestError: The asyncio extension requires an async driver to be used. The loaded 'psycopg2' is not async.`
   - **Fix**: Change it to use `postgresql+asyncpg://user:password@db:5432/emthethal_ai`.

3. **`model_init` PaddleOCR Language Parameter Bug**:
   - The startup script in `docker-compose.yml` for `cfis_model_init` executes `PaddleOCR(lang='arabic')`.
   - PaddleOCR fails with `ValueError: No models are available for the language 'arabic' and OCR version None.`.
   - **Fix**: Change the parameter to `lang='ar'`.

---

## 🛠️ Next Steps

1. **Update `docker-compose.yml`**:
   - Correct the `DATABASE_URL` environment variable for `api`.
   - Correct the `lang='arabic'` to `lang='ar'` in the `model_init` startup command.
   - Run `docker compose down && docker compose up -d` to restart services.

2. **Update `vite.config.js`**:
   - Update target from `http://localhost:8000` to `http://localhost:8001`.

3. **Re-implement Frontend Zones**:
   - **Store (`workbenchStore.js`)**: Add `zones` layer metadata color, default layer status, and `drawingMode` state.
   - **Left Panel (`LeftPanel.jsx`)**: Include the `zones` layer in the layer tree.
   - **Document Viewer (`DocumentViewer.jsx`)**: Render absolute-positioned zone polygons, mouse handlers for drawing new zones (dispatching `CREATE_ZONE` operation), and exempt the zones layer from low-confidence dimming in `cognitive` mode.
   - **Right Panel (`RightPanel.jsx`)**: Implement details display for `isZone` in the inspector, and provide fields to update labels/types and delete zones under `hitl`.

4. **Verify**:
   - Run `npm run build` inside `frontend/` to make sure it compiles.
   - Copy built files to `/backend/frontend/dist/`.
   - Run the python test suites inside `emthethal_backend` to verify regression safety.