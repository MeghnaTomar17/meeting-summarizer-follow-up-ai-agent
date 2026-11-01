"""Narrow import isolation for tests of the Meeting Service's ``app`` package."""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
_SERVICE_ROOTS = {
    (BACKEND_ROOT / service).resolve()
    for service in (
        "gateway-service",
        "meeting-service",
        "ai-service",
        "search-service",
        "worker-service",
    )
}


def prepare_meeting_service_imports() -> None:
    """Ensure future ``app`` imports resolve to Meeting Service only.

    Clear only that colliding package and remove only competing service roots;
    shared backend modules and unrelated import state are left untouched.
    """

    for entry in tuple(sys.path):
        try:
            resolved = Path(entry or ".").resolve()
        except (OSError, RuntimeError):
            continue
        if resolved in _SERVICE_ROOTS and resolved != MEETING_ROOT.resolve():
            sys.path.remove(entry)

    meeting_root = str(MEETING_ROOT)
    backend_root = str(BACKEND_ROOT)
    sys.path[:] = [entry for entry in sys.path if entry not in (meeting_root, backend_root)]
    sys.path.insert(0, backend_root)
    sys.path.insert(0, meeting_root)

    for module_name in tuple(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]
