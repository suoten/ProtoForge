"""ProtoForge entry point for `python -m protoforge`.

This module allows running ProtoForge directly via:
    python -m protoforge           # Start server (demo mode)
    python -m protoforge run       # Start server
    python -m protoforge demo      # Start in demo mode
    python -m protoforge version   # Show version
"""

from protoforge.cli import main

if __name__ == "__main__":
    main()
