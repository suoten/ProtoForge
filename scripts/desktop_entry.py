"""ProtoForge 桌面版冻结入口（PyInstaller）。

双击 exe = 无参数 → 桌面模式（起服务 + 自动开界面 + 托盘）；
`ProtoForge.exe doctor` / `run` / `install-service` 等参数原样透传给 CLI。
"""

import sys

from protoforge.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("desktop")
    sys.exit(main())
