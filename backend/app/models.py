# app/models.py — redirect shim
# Python package resolution: app/models/ (directory) takes precedence over this file.
# This file is kept as a safety net. All actual content now lives in app/models/orm.py.
# Re-importing here for any edge cases where the file is imported directly.
from app.models.orm import *  # noqa: F401,F403
from app.models.orm import Base  # noqa: F401 — ensure Base is explicitly available
