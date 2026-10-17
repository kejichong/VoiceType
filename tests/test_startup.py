"""验证开机自启的注册表读写（写完立刻清掉，不留痕迹）。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
sys.path.insert(0, str(PROJ))

import winreg  # noqa: E402

from app import startup  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name)


def main() -> int:
    before = startup.is_enabled()
    print(f"初始状态: {'已开启' if before else '未开启'}")

    try:
        startup.set_enabled(True)
        check("写入后 is_enabled 为真", startup.is_enabled())

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, startup.RUN_KEY) as k:
            val, typ = winreg.QueryValueEx(k, startup.VALUE_NAME)
        print(f"注册表值: {val}")
        check("值为 REG_SZ", typ == winreg.REG_SZ)
        check("命令带引号且指向 run.py 或 exe",
              val.startswith('"') and (val.endswith('"') or '.py"' in val.lower()
                                       or val.lower().endswith('voicetype.exe"')))

        startup.set_enabled(False)
        check("删除后 is_enabled 为假", not startup.is_enabled())

        # 再次删除不应抛异常（幂等）
        startup.set_enabled(False)
        check("重复关闭幂等", not startup.is_enabled())

        msg = startup.sync_with_config(True)
        print("sync(True) ->", msg)
        check("sync 返回成功文案", msg.startswith("已设置"))
        msg = startup.sync_with_config(False)
        print("sync(False) ->", msg)
        check("sync 返回取消文案", msg.startswith("已取消"))
    finally:
        # 无论如何还原到原始状态，绝不给用户留垃圾启动项
        startup.set_enabled(before)
        print(f"已还原为: {'开启' if before else '关闭'}")

    failed = [n for n, ok in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
