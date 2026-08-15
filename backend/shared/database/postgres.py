"""
Purpose: Backward-compatible PostgreSQL entrypoints.
Service ownership: Shared module.
"""

from __future__ import annotations

from shared.database.session import close_database as close_postgres
from shared.database.session import get_db_session as get_session
from shared.database.session import init_database as init_postgres

__all__ = ["close_postgres", "get_session", "init_postgres"]
