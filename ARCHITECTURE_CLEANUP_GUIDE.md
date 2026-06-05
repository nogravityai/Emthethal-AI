# 🧹 دليل تنظيف وتقليل تعقيد المعمارية (Architecture Cleanup Guide)

يوضح هذا الملف خريطة تطور واجهات وتطبيقات **Emthethal AI (CFIS)** والمراحل الثلاث التي مر بها المشروع. كما يضع خطة عمل واضحة لكيفية إزالة الأكواد القديمة (Legacy) وفك الارتباط في حال اتخاذ قرار بالاستغناء عن المراحل السابقة والاكتفاء بنظام **Evidence Workbench**.

---

## 🗺️ خريطة الواجهات ومساراتها (Frontend to Backend Mapping)

يحتوي النظام حالياً على 3 واجهات رئيسية تعكس ثلاث مراحل للتطوير، وكل واجهة متصلة بمسارات مختلفة في الباك اند:

### 1. معالج PDF (المرحلة 1 - Phase 1)
* **المسؤولية:** رفع الـ PDF، استخراج النصوص، وتكويد استمارة Form.io بدائية.
* **ملف الواجهة:** `frontend/src/components/PDFProcessor.jsx`
* **مسار الـ API:** `/api/cfis/v1/process`
* **كود الباك اند (الراوتر):** `backend/app/api/router.py` (معرف كـ `cfis_router`).

### 2. Geometry Debug (المرحلة 2B - Phase 2B)
* **المسؤولية:** عرض تحليلات هندسة المستند (الخطوط، الجداول، المربعات) كطبقات مرئية للمهندسين.
* **ملف الواجهة:** `frontend/src/components/GeometryDebugViewer.jsx`
* **مسار الـ API:** `/api/cfis/v1/debug/geometry`
* **كود الباك اند (الراوتر):** `backend/app/api/routes/geometry_debug.py`

### 3. 🧬 Evidence Workbench (المرحلة 3 - Phase 3)
* **المسؤولية:** النظام الشامل والأخير الذي يعتمد عليه المشروع. يدمج الهندسة المكانية مع البيانات الدلالية، ويسمح بالتدخل البشري (HITL) عبر واجهة بصرية دقيقة.
* **ملف الواجهة:** `frontend/src/workbench/EvidenceWorkbench.jsx`
* **مسارات الـ API:** 
  * `/api/cfis/v3/pipeline/`
  * `/api/cfis/v3/hitl/`
* **كود الباك اند (الراوتر):** 
  * `backend/app/api/routes/pipeline.py`
  * `backend/app/api/routes/hitl.py`

*(ملاحظة: Evidence Workbench يمتلك بنية Pipeline مستقلة ولا يستدعي الراوترات الخاصة بالمرحلتين 1 و 2).*

---

## 🗑️ خطة العمل: ماذا نفعل لإزالة المراحل السابقة؟

إذا قررنا الاستغناء عن "معالج PDF" و "Geometry Debug" لتخفيف تعقيد الكود، فهذه هي الخطوات التقنية الآمنة للتنظيف:

### أولاً: تنظيف الواجهة الأمامية (Frontend)
1. **حذف الملفات:** حذف الملفين التاليين بالكامل:
   * `frontend/src/components/PDFProcessor.jsx`
   * `frontend/src/components/GeometryDebugViewer.jsx`
2. **تعديل التطبيق الأساسي:** فتح ملف `frontend/src/App.jsx`:
   * إزالة الـ `Imports` الخاصة بالملفات المحذوفة.
   * إزالة أزرار التنقل الخاصة بهما من الـ Sidebar (من مصفوفة `NAV`).
   * تنظيف جمل الـ `if` أو الـ `switch` التي كانت تعرض هذه الواجهات.

### ثانياً: تنظيف مسارات الباك اند (Backend Routers)
1. **تعديل الدخول الرئيسي:** فتح ملف `backend/app/main.py`:
   * إزالة السطر الذي يقوم باستيراد `cfis_router`.
   * إزالة السطر: `app.include_router(cfis_router)`.
   * إزالة السطر الذي يقوم باستيراد `geometry_debug_router`.
   * إزالة السطر: `app.include_router(geometry_debug_router)`.
2. **حذف ملفات الراوترز:** حذف الملفين التاليين من مجلد `backend/app/api/`:
   * `backend/app/api/router.py`
   * `backend/app/api/routes/geometry_debug.py`

### ثالثاً: تنظيف خدمات الباك اند (Backend Services Cleanup) - خطوة متقدمة
بعد إزالة المسارات، ستصبح بعض الأكواد في مجلد `backend/app/services` يتيمة (لا يستدعيها أحد غير الكود المحذوف).
يجب إجراء بحث (Grep) عن الدوال الموجودة داخل مجلد الـ services. الدوال التي لا يتم استدعاؤها من قِبل الـ `v3 Pipeline` (`pipeline.py`, `hitl.py`, أو الـ `Stages` الحديثة) يمكن حذفها بأمان لتقليل الحجم.

### هل هناك خطر على Evidence Workbench؟
**لا يوجد أي خطر.** 
بنية الـ Workbench تعتمد بالكامل على خوارزميات محقونة داخل "مراحل مستقلة" (Stages) مثل `EvidencePatchStage` ومرحلة `AlignmentStage`. الكود القديم يعمل كطبقة تغليف (Wrapper) خارجية للـ APIs القديمة (v1)، وإزالته ستزيل فقط نقاط الوصول القديمة دون المساس بجوهر خوارزميات الذكاء الاصطناعي التي يستخدمها الإصدار الثالث.
