"""验证设置窗口的假引擎联动：勾上时密钥区应置灰。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
sys.path.insert(0, str(PROJ))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import Config  # noqa: E402
from app.ui.settings import SettingsDialog  # noqa: E402

OUT = PROJ / ".venv" / "shots"
OUT.mkdir(parents=True, exist_ok=True)

checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name)


def main() -> int:
    app = QApplication(sys.argv)
    cfg = Config.load()
    dlg = SettingsDialog(cfg)
    dlg.show()
    app.processEvents()

    dlg.chk_mock.setChecked(True)
    app.processEvents()
    check("勾选假引擎后 AppKey 置灰", not dlg.ed_appkey.isEnabled())
    check("勾选假引擎后 Secret 置灰", not dlg.ed_aksecret.isEnabled())
    check("勾选假引擎后测试按钮置灰", not dlg.btn_test.isEnabled())
    check("提示文案出现", "离线假引擎" in dlg.lb_test.text())
    dlg.grab().save(str(OUT / "settings_mock_on.png"))

    dlg.chk_mock.setChecked(False)
    app.processEvents()
    check("取消勾选后 AppKey 恢复", dlg.ed_appkey.isEnabled())
    check("取消勾选后测试按钮恢复", dlg.btn_test.isEnabled())
    check("提示文案清空", dlg.lb_test.text() == "")
    dlg.grab().save(str(OUT / "settings_mock_off.png"))

    dlg.close()
    failed = [n for n, ok in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
