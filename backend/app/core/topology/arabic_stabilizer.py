import logging
from typing import List, Any

logger = logging.getLogger(__name__)

class ArabicReadingFlowStabilizer:
    """
    Stabilizes reading order for Arabic layout rows.
    If the Arabic character ratio in a row exceeds 30%, it applies RTL sorting
    (descending by x coordinate) to preserve natural RTL reading order.
    """
    def __init__(self, arabic_threshold: float = 0.30):
        self.arabic_threshold = arabic_threshold

    def is_arabic_text(self, text: str) -> bool:
        """True if the character ratio of Arabic script is above threshold."""
        if not text:
            return False
        # Arabic unicode range: \u0600 - \u06FF
        arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
        return (arabic_chars / len(text)) >= self.arabic_threshold

    def stabilize_row_tokens(self, tokens: List[Any]) -> List[Any]:
        """
        Sorts tokens within a single row based on script direction.
        If row has >= 30% Arabic tokens or characters, sort RTL (descending by x1/x2 coordinate).
        Otherwise sort LTR (ascending by x1 coordinate).
        """
        if not tokens:
            return []

        arabic_tokens_count = 0
        total_text = ""
        for t in tokens:
            text = getattr(t, "text", getattr(t, "ocr_raw_text", ""))
            total_text += text
            if self.is_arabic_text(text):
                arabic_tokens_count += 1

        is_rtl = False
        if tokens:
            token_ratio = arabic_tokens_count / len(tokens)
            if token_ratio >= self.arabic_threshold or self.is_arabic_text(total_text):
                is_rtl = True

        if is_rtl:
            # Sort descending by x center coordinate (RTL)
            sorted_tokens = sorted(tokens, key=lambda t: (t.bbox.x2 + t.bbox.x1) / 2.0, reverse=True)
            logger.debug(f"Arabic RTL sorting applied to row of {len(tokens)} tokens.")
        else:
            # Sort ascending by x center coordinate (LTR)
            sorted_tokens = sorted(tokens, key=lambda t: (t.bbox.x2 + t.bbox.x1) / 2.0)
            logger.debug(f"Default LTR sorting applied to row of {len(tokens)} tokens.")

        return sorted_tokens
