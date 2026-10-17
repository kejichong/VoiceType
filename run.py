"""PyInstaller 入口（包内相对导入需要以包的方式启动）。"""
from __future__ import annotations

import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
