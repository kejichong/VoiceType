"""设置窗口：填密钥、改热键、选麦克风。

密钥写盘前用 DPAPI 加密，配置文件被拷走也解不出来。
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..audio import Recorder
from ..config import Config
from ..hotkey import HotkeyError, parse_hotkey
from ..startup import sync_with_config

# 首次使用的分步指引。要发给别人用，光甩一句"密钥未配置"对方是不知道该怎么办的，
# 必须把"去哪个网址、点哪里、拿哪个值"写死在这里。
_GUIDE_TEXT = (
    "<b>第一次使用，需要三个值才能识别（都有免费额度）：</b>"
    "<ol style='margin-top:6px; margin-left:-6px; line-height:165%;'>"
    "<li>打开 <a href='https://nls-portal.console.aliyun.com/'>阿里云智能语音交互控制台</a>，"
    "用支付宝或淘宝扫码登录，点「立即开通」</li>"
    "<li>左侧「项目管理」→ 创建项目 → 项目里的 <b>AppKey</b> 就是第一个值</li>"
    "<li>点右上角头像 → <b>AccessKey 管理</b> → 拿到 "
    "<b>AccessKey ID</b> 和 <b>AccessKey Secret</b></li>"
    "<li>三个都填好，点下面的「测试连接」，显示成功后再按保存</li>"
    "</ol>"
)
_HL_EDIT = (
    "QLineEdit{border:1.5px solid #E8A33D; border-radius:4px;"
    " padding:5px; background:#FFFDF7;}"
)


class SettingsDialog(QDialog):
    sig_test_result = Signal(bool, str)

    def __init__(self, cfg: Config, parent=None, guide: bool = False) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._guide = guide
        self.setWindowTitle("语音输入 · 首次使用设置" if guide else "语音输入 · 设置")
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self.sig_test_result.connect(self._on_test_result)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_engine_tab(), "识别服务")
        tabs.addTab(self._build_general_tab(), "通用")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        if guide:
            # 等窗口真正可见再设焦点，构造期间设会被布局过程盖掉
            QTimer.singleShot(0, self._focus_first_blank)

    # ---------------- 识别服务 ----------------
    def _build_engine_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        hint = QLabel(
            "在阿里云智能语音交互控制台创建项目后，可获得 AppKey。\n"
            "AccessKey 建议使用只有语音服务权限的子账号密钥。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#5F5E5A; font-size:12px;")
        if self._guide:
            hint.setText(_GUIDE_TEXT)
            hint.setTextFormat(Qt.RichText)
            hint.setOpenExternalLinks(True)
            hint.setStyleSheet("color:#1F1F1D; font-size:12px;")
        form.addRow(hint)

        self.ed_appkey = QLineEdit(self.cfg.secret("appkey"))
        self.ed_appkey.setPlaceholderText("例如 a1b2c3d4e5")
        form.addRow("AppKey", self.ed_appkey)

        self.ed_akid = QLineEdit(self.cfg.secret("access_key_id"))
        self.ed_akid.setPlaceholderText("LTAI...")
        form.addRow("AccessKey ID", self.ed_akid)

        self.ed_aksecret = QLineEdit(self.cfg.secret("access_key_secret"))
        self.ed_aksecret.setEchoMode(QLineEdit.Password)
        self.ed_aksecret.setPlaceholderText("填写后本地加密保存")
        form.addRow("AccessKey Secret", self.ed_aksecret)

        self.cb_region = QComboBox()
        for rid, label in (("cn-shanghai", "华东2（上海）"), ("cn-beijing", "华北2（北京）"),
                           ("cn-shenzhen", "华南1（深圳）")):
            self.cb_region.addItem(label, rid)
        idx = self.cb_region.findData(self.cfg.get("engine.region", "cn-shanghai"))
        self.cb_region.setCurrentIndex(max(0, idx))
        form.addRow("服务地域", self.cb_region)

        self.ed_vocab = QLineEdit(str(self.cfg.get("engine.vocabulary_id", "") or ""))
        self.ed_vocab.setPlaceholderText("可选：热词表 ID，填了能显著提高专业术语准确率")
        form.addRow("热词表 ID", self.ed_vocab)

        row = QHBoxLayout()
        self.btn_test = QPushButton("测试连接")
        self.btn_test.clicked.connect(self._test)
        self.lb_test = QLabel("")
        self.lb_test.setStyleSheet("font-size:12px;")
        row.addWidget(self.btn_test)
        row.addWidget(self.lb_test, 1)
        form.addRow("", self._wrap(row))

        self.chk_mock = QCheckBox("使用离线假引擎（不联网，仅用于验证热键和贴字）")
        self.chk_mock.setChecked(str(self.cfg.get("engine.type", "aliyun")) == "mock")
        form.addRow("", self.chk_mock)

        # 勾着假引擎就把云端配置置灰：否则用户填完密钥以为生效了，
        # 实际还在跑写死的测试文字，排查起来非常费劲。
        self.chk_mock.toggled.connect(self._on_mock_toggled)
        self._on_mock_toggled(self.chk_mock.isChecked())

        if self._guide:
            # 把要填的三个框描边，别让用户在一堆输入框里猜哪个是必填
            for w in (self.ed_appkey, self.ed_akid, self.ed_aksecret):
                w.setStyleSheet(_HL_EDIT)
        return page

    def _focus_first_blank(self) -> None:
        """光标直接落到第一个还空着的框，省一次点击。"""
        for w in (self.ed_appkey, self.ed_akid, self.ed_aksecret):
            if not w.text().strip():
                w.setFocus()
                return
        self.btn_test.setFocus()

    def _on_mock_toggled(self, checked: bool) -> None:
        for w in (self.ed_appkey, self.ed_akid, self.ed_aksecret,
                  self.cb_region, self.ed_vocab, self.btn_test):
            w.setEnabled(not checked)
        if checked:
            self.lb_test.setText("当前为离线假引擎，不会真正识别语音")
            self.lb_test.setStyleSheet("font-size:12px;color:#854F0B;")
        elif self.lb_test.text().startswith("当前为离线假引擎"):
            self.lb_test.setText("")

    # ---------------- 通用 ----------------
    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.kse_hotkey = QKeySequenceEdit(QKeySequence(str(self.cfg.get("hotkey.binding", "Ctrl+Alt+Space"))))
        self.kse_hotkey.setMaximumSequenceLength(1)
        self.lb_hotkey = QLabel("")
        self.lb_hotkey.setStyleSheet("font-size:12px;color:#5F5E5A;")
        form.addRow("快捷键", self.kse_hotkey)
        form.addRow("", self.lb_hotkey)

        self.cb_device = QComboBox()
        self.cb_device.addItem("系统默认麦克风", None)
        for idx, name in Recorder.list_devices():
            self.cb_device.addItem(f"{name}", idx)
        form.addRow("麦克风", self.cb_device)

        self.cb_delay = QComboBox()
        for ms in (250, 350, 500, 700):
            self.cb_delay.addItem(f"{ms} 毫秒", ms / 1000.0)
        cur_delay = float(self.cfg.get("injection.delay_sec", 0.35))
        i = self.cb_delay.findData(cur_delay)
        self.cb_delay.setCurrentIndex(i if i >= 0 else 1)
        form.addRow("粘贴等待", self.cb_delay)
        tip = QLabel("程序较慢（如大型 IDE）时可调大，否则偶尔会粘不上")
        tip.setStyleSheet("font-size:12px;color:#5F5E5A;")
        form.addRow("", tip)

        self.chk_filler = QCheckBox("自动去掉「嗯、呃、那个」等口头语")
        self.chk_filler.setChecked(bool(self.cfg.get("postprocess.remove_fillers", True)))
        form.addRow("", self.chk_filler)

        self.chk_beep = QCheckBox("按键提示音（按下、松开各响一声）")
        self.chk_beep.setChecked(bool(self.cfg.get("ui.sound_cue", True)))
        form.addRow("", self.chk_beep)

        self.chk_float = QCheckBox("显示悬浮球（点一下开始/停止，可以拖到任意位置）")
        self.chk_float.setChecked(bool(self.cfg.get("ui.float_button", True)))
        tip_float = QLabel(
            "好按的两键组合键基本都被系统和输入法占了，三键又费劲。"
            "悬浮球是不用记组合键的入口，点它不会抢走你正在打字的地方"
        )
        tip_float.setWordWrap(True)
        tip_float.setStyleSheet("font-size:12px;color:#5F5E5A;")
        form.addRow("", self.chk_float)
        form.addRow("", tip_float)

        self.chk_auto = QCheckBox("开机自动启动")
        self.chk_auto.setChecked(bool(self.cfg.get("startup.auto_start", False)))
        form.addRow("", self.chk_auto)

        self.kse_hotkey.keySequenceChanged.connect(self._validate_hotkey)
        self._validate_hotkey()
        return page

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _validate_hotkey(self) -> None:
        seq = self.kse_hotkey.keySequence().toString()
        try:
            parse_hotkey(seq)
            self.lb_hotkey.setText("")
            self.lb_hotkey.setStyleSheet("font-size:12px;color:#0F6E56;")
        except HotkeyError as exc:
            self.lb_hotkey.setText(str(exc))
            self.lb_hotkey.setStyleSheet("font-size:12px;color:#A32D2D;")

    # ---------------- 测试 ----------------
    def _test(self) -> None:
        appkey = self.ed_appkey.text().strip()
        akid = self.ed_akid.text().strip()
        secret = self.ed_aksecret.text().strip()
        if not (appkey and akid and secret):
            self._on_test_result(False, "三项都要填")
            return
        self.btn_test.setEnabled(False)
        self.lb_test.setText("正在连接…")
        self.lb_test.setStyleSheet("font-size:12px;color:#5F5E5A;")
        region = self.cb_region.currentData()

        def worker() -> None:
            try:
                from ..engine.aliyun import create_token

                token = create_token(akid, secret, region)
                self.sig_test_result.emit(True, f"连接正常（令牌 {token[:6]}…）")
            except Exception as exc:
                self.sig_test_result.emit(False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_result(self, ok: bool, msg: str) -> None:
        self.btn_test.setEnabled(True)
        self.lb_test.setText(msg)
        self.lb_test.setStyleSheet(
            "font-size:12px;color:#0F6E56;" if ok else "font-size:12px;color:#A32D2D;"
        )

    # ---------------- 保存 ----------------
    def _save(self) -> None:
        seq = self.kse_hotkey.keySequence().toString() or "Ctrl+Alt+Space"
        try:
            parse_hotkey(seq)
        except HotkeyError as exc:
            QMessageBox.warning(self, "快捷键无效", str(exc))
            return

        self.cfg.set("hotkey.binding", seq)
        self.cfg.set("engine.type", "mock" if self.chk_mock.isChecked() else "aliyun")
        self.cfg.set_secret("appkey", self.ed_appkey.text().strip())
        self.cfg.set_secret("access_key_id", self.ed_akid.text().strip())
        self.cfg.set_secret("access_key_secret", self.ed_aksecret.text().strip())
        self.cfg.set("engine.region", self.cb_region.currentData())
        self.cfg.set("engine.vocabulary_id", self.ed_vocab.text().strip())

        dev = self.cb_device.currentData()
        self.cfg.set("audio.device", dev)
        self.cfg.set("injection.delay_sec", self.cb_delay.currentData())
        self.cfg.set("postprocess.remove_fillers", self.chk_filler.isChecked())
        self.cfg.set("ui.sound_cue", self.chk_beep.isChecked())
        self.cfg.set("ui.float_button", self.chk_float.isChecked())

        # 开机自启要真写注册表，只存配置不算数
        want_auto = self.chk_auto.isChecked()
        self.cfg.set("startup.auto_start", want_auto)
        note = sync_with_config(want_auto)

        self.cfg.save()
        if note.startswith("开机自启设置失败"):
            QMessageBox.warning(self, "开机自启", note + "\n\n其余设置已保存。")
        self.accept()
