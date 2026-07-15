"""Root-level pytest configuration and shared fixtures.

This file ensures pytest discovers shared fixtures from the tests/ directory
and provides project-wide test configuration.
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path for test discovery
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Import shared fixtures from tests/conftest.py
from tests.conftest import *  # noqa: F401, F403
