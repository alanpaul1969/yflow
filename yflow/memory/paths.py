"""
Path resolution for yflow memory.

Follows XDG Base Directory spec:
- XDG_DATA_HOME (default ~/.local/share) for data files
- XDG_CONFIG_HOME (default ~/.config) for config
- Override via env vars: YFLOW_MEMORY_DIR
"""

from __future__ import annotations

import os
from pathlib import Path


def default_memory_dir() -> Path:
    """Return the default memory storage directory.

    Resolution order:
    1. $YFLOW_MEMORY_DIR (explicit override)
    2. $XDG_DATA_HOME/yflow/memory (XDG default)
    3. ~/.local/share/yflow/memory (XDG fallback)
    """
    explicit = os.environ.get("YFLOW_MEMORY_DIR")
    if explicit:
        return Path(explicit).expanduser()

    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data).expanduser() / "yflow" / "memory"

    return Path.home() / ".local" / "share" / "yflow" / "memory"
