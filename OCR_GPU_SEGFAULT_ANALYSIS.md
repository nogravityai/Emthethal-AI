# 🛑 OCR Engine Architecture & Segmentation Fault Resolutions

This document provides a comprehensive technical reference for the integration, execution, and troubleshooting of **PaddleOCR** within the Emthethal-AI containerized environment. It details the root causes of the segmentation faults on both CPU and GPU, the architectural solutions applied, and critical constraints that must be preserved by future developers or AI agents.

---

## 🏗️ 1. Architecture & Model Persistence

### A. Shared Docker Volume (`paddle_models`)
To prevent models from being downloaded repeatedly on container rebuilds, the project implements a shared Docker named volume named `paddle_models`.
* **Host Mapping:** The volume is declared in the root [docker-compose.yml](file:///wsl$/Ubuntu/home/hya/emthethal-ai/docker-compose.yml).
* **Mount Point:** Mounted inside containers at `/root/.paddleocr`.
* **Shared Across Services:** 
  - `cfis_api` (FastAPI backend)
  - `emthethal_backend` (Legacy backend)
  - `emthethal_rq_worker` (Background job queue processor)
  - `model_init` (One-time download container)

### B. One-Time Model Bootstrapping (`model_init`)
The `model_init` service initializes, verifies, and downloads the Arabic model files into the shared volume `/root/.paddleocr` before any API services start.
* It writes a marker file at `/root/.paddleocr/.arabic_model_ready` upon successful completion.
* Subsequent runs bypass downloading if the marker exists, accelerating container startup.

---

## 🛑 2. Resolved Segmentation Faults (SIGSEGV)

The system previously encountered critical `exit code 139` (Segmentation fault) failures during PaddleOCR initialization. These were root-caused and resolved as follows:

### Cause 1: Version Mismatch (`paddleocr==3.5.0` vs `paddlepaddle==2.6.2`)
* **Problem:** A cached layer pulled `paddleocr 3.5.0` (which relies on `PaddleX 3.x`). PaddleX attempted to invoke `config.set_optimization_level(3)` on the `AnalysisConfig` object. This method does not exist in the C++ binaries of `paddlepaddle 2.6.2`, causing AttributeErrors and memory layout incompatibilities leading to C++ segfaults.
* **Resolution:** Re-pinned the package version in `requirements.txt` to **`paddleocr==2.7.3`** and rebuilt the entire compose stack from scratch (`docker-compose up -d --build`).

### Cause 2: MKL-DNN Memory Allocation Crash (`enable_mkldnn=True`)
* **Problem:** On certain host CPUs (specifically inside Docker under WSL2), Intel's Math Kernel Library for Deep Neural Networks (MKL-DNN) causes segmentation faults during internal thread/memory initialization inside the compiled PaddlePaddle C++ backend.
* **Resolution:** MKL-DNN must be explicitly disabled inside the `PaddleOCR` constructor:
  ```python
  enable_mkldnn=False
  ```

### Cause 3: Orientation Classifier Memory Allocation (`use_angle_cls=True`)
* **Problem:** Loading the textline orientation classifier (`use_angle_cls=True` or `use_textline_orientation=True`) downloads and instantiates the `ch_ppocr_mobile_v2.0_cls_infer` / `PP-LCNet_x1_0_doc_ori` C++ predictor. The compiled binary version of PaddlePaddle-GPU/CPU 2.6.2 conflicts with GLIBC thread allocation in Debian-slim base images, resulting in immediate segmentation faults during variable creation.
* **Resolution:** Orientation and angle classification are disabled system-wide.
  ```python
  use_angle_cls=False
  use_textline_orientation=False
  ```

### Cause 4: Shared Binary Symbol Allocation Order (`free(): invalid pointer`)
* **Problem:** When python imports `paddle` before other scientific C-extensions like `numpy` or `Pillow` (PIL), the system allocator resolves symbols differently. Under certain allocations, this mismatch triggers double-frees or invalid pointer errors upon object cleanup.
* **Resolution:** Always import `numpy` and `PIL.Image` **before** importing `paddle` or `paddleocr` inside any initialization script or runner.

---

## 🛠️ 3. Critical Code Invariants for Future Agents

When modifying the OCR engines or running tests, you **MUST** respect the following rules:

### I. OCR Initialization Parameters
Always configure the `PaddleOCR` instance with:
```python
ocr = PaddleOCR(
    lang='ar', # or 'arabic' depending on setup
    use_angle_cls=False,
    use_gpu=False, # Force CPU to bypass binary GLIBC/Slim conflicts
    enable_mkldnn=False,
    # Local path specifications when loaded within containers:
    det_model_dir='/root/.paddleocr/whl/det/ml/Multilingual_PP-OCRv3_det_infer',
    rec_model_dir='/root/.paddleocr/whl/rec/arabic/arabic_PP-OCRv4_rec_infer',
    cls_model_dir='/root/.paddleocr/whl/cls/ch_ppocr_mobile_v2.0_cls_infer'
)
```

### II. Import Order & Monkey-Patch Invariant
If importing `paddle` in any diagnostic script or engine, structure the imports and patches exactly as follows:
```python
import sys
import numpy as np
from PIL import Image

# 1. Apply C++ Optimizer level patch to prevent paddle/paddlex attribute crashes
import paddle
try:
    paddle.base.libpaddle.AnalysisConfig.set_optimization_level = lambda self, level: None
except AttributeError:
    pass

# 2. Import PaddleOCR after libraries and patches
from paddleocr import PaddleOCR
```

### III. YAML Safe Block Commands
In [docker-compose.yml](file:///wsl$/Ubuntu/home/hya/emthethal-ai/docker-compose.yml), if writing Python commands inside the `command` attribute that contain colons (`:`), always use the YAML folded block scalar indicator (`>`) to prevent syntax parsing errors:
```yaml
    command: >
      python3 -c "import os... config.set_optimization_level = lambda self, level: None..."
```
