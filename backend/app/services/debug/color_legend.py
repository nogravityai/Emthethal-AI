from enum import Enum
from typing import Tuple

class DebugSemanticColor(Enum):
    """
    Deterministic semantic colors for pipeline debugging and regression diffing.
    Values are standard BGR tuples for OpenCV.
    """
    ACCEPTED = (40, 200, 40)        # Green
    REJECTED = (40, 40, 220)        # Red
    ORPHAN = (0, 140, 255)          # Orange
    ANCHOR = (255, 0, 255)          # Magenta
    REGION = (200, 200, 40)         # Cyan
    TOKEN = (100, 100, 100)         # Gray
    WARNING = (0, 255, 255)         # Yellow

    def as_hex(self) -> str:
        """Return as hex string for frontend JSON overlays."""
        b, g, r = self.value
        return f"#{r:02x}{g:02x}{b:02x}"
