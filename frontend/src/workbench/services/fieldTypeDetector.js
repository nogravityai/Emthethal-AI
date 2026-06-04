/**
 * CFIS v5.2 — Field Type Detector
 *
 * Rule-based intelligent field type detection for instant UI feedback.
 * Mirrors backend: app/services/schema/field_type_classifier.py
 * Both implementations MUST produce identical results for the same inputs.
 *
 * Used in:
 *  - RightPanel (zone inspector: child field cards)
 *  - BottomPanel (zone schema view)
 *  - DocumentViewer (highlight fields inside selected zone)
 */

// ── Patterns ─────────────────────────────────────────────────────────────────
const DATE_RE    = /\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}/;
const EMAIL_RE   = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/;
const PHONE_RE   = /^[\+]?[\d\s\-\(\)]{8,15}$/;
const NUMBER_RE  = /^\d+([.,]\d+)?$/;

// ── Keyword Sets ─────────────────────────────────────────────────────────────
const CHECKBOX_CHARS  = new Set(['☑', '☐', '□', '✓', '✗']);
const CHECKBOX_TEXTS  = new Set(['[x]', '[X]', '[v]', '[V]', '[ ]']);

const DATE_HINTS      = ['تاريخ', 'date', 'يوم', 'شهر', 'سنة', 'birth', 'ميلاد', 'التاريخ'];
const NAME_HINTS      = ['اسم', 'الاسم', 'المريض', 'الطبيب', 'المراجع', 'name', 'patient', 'doctor'];
const HEADER_HINTS    = ['القسم', 'قسم', 'section', 'معلومات', 'information', 'بيانات', 'data'];
const PHONE_HINTS     = ['هاتف', 'جوال', 'phone', 'mobile', 'tel', 'رقم الهاتف'];
const EMAIL_HINTS     = ['بريد', 'email', 'إيميل', 'ايميل'];
const SIG_HINTS       = ['توقيع', 'signature', 'ختم', 'stamp', 'الإمضاء'];
const DROPDOWN_HINTS  = ['اختر', 'select', 'choose', 'قائمة', 'dropdown'];

/**
 * Classify the field type from OCR text + nearby label.
 *
 * @param {string} text         - The raw field value / OCR text
 * @param {string} nearbyLabel  - Nearby label token (Arabic RTL: label is to the right)
 * @returns {string}            - FieldType value (see FIELD_TYPE_LABELS)
 */
export function detectFieldType(text = '', nearbyLabel = '') {
  const t = (text || '').trim();
  const combined = `${t} ${nearbyLabel}`.toLowerCase();

  if (!t && !nearbyLabel) return 'unknown';

  // 1. Checkbox — highest priority (visual indicators)
  if ([...CHECKBOX_CHARS].some(ch => t.includes(ch))) return 'checkbox';
  if ([...CHECKBOX_TEXTS].some(tx => t.includes(tx))) return 'checkbox';

  // 2. Date — value or label match
  if (DATE_RE.test(t)) return 'date';
  if (DATE_HINTS.some(h => combined.includes(h))) return 'date';

  // 3. Email
  if (EMAIL_RE.test(t)) return 'email';
  if (EMAIL_HINTS.some(h => combined.includes(h))) return 'email';

  // 4. Phone
  if (t && PHONE_RE.test(t) && t.replace(/\D/g, '').length >= 7) return 'phone';
  if (PHONE_HINTS.some(h => combined.includes(h))) return 'phone';

  // 5. Signature
  if (SIG_HINTS.some(h => combined.includes(h))) return 'signature';

  // 6. Dropdown / Select
  if (DROPDOWN_HINTS.some(h => combined.includes(h))) return 'dropdown';

  // 7. Name
  if (NAME_HINTS.some(h => combined.includes(h))) return 'name';

  // 8. Section Header (short text)
  if (t.split(' ').length <= 5 && HEADER_HINTS.some(h => combined.includes(h))) return 'header';

  // 9. Pure number
  if (t && NUMBER_RE.test(t)) return 'number';

  return 'text';
}


/**
 * Find all fusion fields whose center lies inside a zone's bbox.
 * Also enriches each field with a detected type and nearby label.
 *
 * @param {Object} zone         - Zone object with .bbox [x1, y1, x2, y2]
 * @param {Array}  ocrTokens    - Array of OCR tokens with .bbox and .text
 * @param {Array}  fusionFields - Array of resolved fields with .bbox
 * @returns {Array}             - Enriched field objects for zone inspector
 */
export function detectFieldsInZone(zone, ocrTokens = [], fusionFields = []) {
  if (!zone?.bbox) return [];

  const [zx1, zy1, zx2, zy2] = zone.bbox;

  return fusionFields
    .filter(f => {
      if (!f.bbox) return false;
      const [fx1, fy1, fx2, fy2] = f.bbox;
      const cx = (fx1 + fx2) / 2;
      const cy = (fy1 + fy2) / 2;
      return cx >= zx1 && cx <= zx2 && cy >= zy1 && cy <= zy2;
    })
    .map(f => {
      const [fx1, fy1, fx2, fy2] = f.bbox || [0, 0, 0, 0];
      const fcy = (fy1 + fy2) / 2;

      // Arabic RTL: label is to the right of the value
      const nearbyTokens = ocrTokens
        .filter(t => {
          if (!t.bbox) return false;
          const [, ty1, , ty2] = t.bbox;
          const tcy = (ty1 + ty2) / 2;
          return Math.abs(tcy - fcy) <= 20 && t.bbox[0] > fx2;
        })
        .sort((a, b) => a.bbox[0] - b.bbox[0]); // closest first

      const nearbyLabel = nearbyTokens.slice(0, 2).map(t => t.text).join(' ');

      return {
        field_id:      f.id || f.field_id || '',
        label:         nearbyLabel || f.field_type || 'Field',
        value:         f.value ?? f.text ?? '',
        detected_type: detectFieldType(String(f.value ?? ''), nearbyLabel),
        bbox:          f.bbox,
        confidence:    f.confidence ?? f.confidence_score ?? 0,
        ocr_tokens:    f.ocr_tokens || [],
      };
    });
}


// ── Display Metadata ──────────────────────────────────────────────────────────

/** Icon per field type */
export const FIELD_TYPE_ICONS = {
  date:       '📅',
  checkbox:   '☑',
  radio:      '🔘',
  dropdown:   '⬇',
  text:       '📝',
  name:       '👤',
  number:     '#',
  phone:      '📞',
  email:      '✉',
  signature:  '✍',
  header:     '🏷',
  form_title: '📋',
  table:      '📊',
  unknown:    '❓',
};

/** Arabic labels per field type */
export const FIELD_TYPE_LABELS = {
  date:       'تاريخ',
  checkbox:   'مربع اختيار',
  radio:      'اختيار وحيد',
  dropdown:   'قائمة منسدلة',
  text:       'نص حر',
  name:       'اسم',
  number:     'رقم',
  phone:      'هاتف',
  email:      'بريد إلكتروني',
  signature:  'توقيع',
  header:     'عنوان قسم',
  form_title: 'اسم الاستمارة',
  table:      'جدول',
  unknown:    'غير محدد',
};

/** All available field types for dropdown selects */
export const ALL_FIELD_TYPES = Object.keys(FIELD_TYPE_LABELS);

/** Color per field type for UI chips */
export const FIELD_TYPE_COLORS = {
  date:       '#0EA5E9',  // sky blue
  checkbox:   '#10B981',  // emerald
  radio:      '#A78BFA',  // violet
  dropdown:   '#F59E0B',  // amber
  text:       '#64748B',  // slate
  name:       '#3B82F6',  // blue
  number:     '#EC4899',  // pink
  phone:      '#06B6D4',  // cyan
  email:      '#8B5CF6',  // purple
  signature:  '#F97316',  // orange
  header:     '#EF4444',  // red
  form_title: '#F43F5E',  // rose
  table:      '#FBBF24',  // yellow
  unknown:    '#374151',  // gray
};
