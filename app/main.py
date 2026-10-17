"""程序入口：单实例、托盘、热键、状态编排。

状态迁移只允许在主线程或工作线程通过 StateMachine 完成，
UI 更新一律通过 Qt 信号回到主线程——这是避免竞态的关键。
"""
from __future__ import annotations

import ctypes
import queue
import sys
import threading
import traceback
import winsound
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import injector, postprocess, win32util
from .audio import AudioError, Recorder
from .config import Config
from .engine import EngineError, create_engine
from .hotkey import HotkeyError, HotkeyManager
from .log import get_logger, setup_logging
from .state import State, StateMachine
from .ui.floatbtn import FloatingButton
from .ui.overlay import Overlay
from .ui.settings import SettingsDialog
from .ui.tray import Tray

# Local\ 作用域是当前登录会话，同一会话双开才拦
MUTEX_NAME = "Local\\VoiceType_SingleInstance_v1"
# 第二个实例通过这个命名事件把"用户又点了一次图标"告诉已运行的实例
WAKE_EVENT_NAME = "Local\\VoiceType_Wake_v1"
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
MIN_SESSION_BYTES = 16000 * 2 * 0.3  # 少于 0.3 秒当误触丢弃


def beep(freq: int, ms: int = 55) -> None:
    """按键反馈音。

    打开麦克风和连 WebSocket 需要几百毫秒，这段时间用户看不到任何变化，
    会以为没生效而重复按键（实测的确发生了）。声音是最快的确认信号。
    """
    try:
        winsound.Beep(freq, ms)
    except Exception:
        pass

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.SetEvent.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


def acquire_single_instance() -> bool:
    """双开会抢热键并贴两遍文字，必须拦在启动阶段。

    两个坑：kernel32 必须用 use_last_error=True 加载，否则 get_last_error()
    读不到 183；CreateMutexW 必须声明 restype，否则 HANDLE 在 64 位下被截断。
    任一处漏了，这个锁都会静默失效。
    """
    handle = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True  # 创建失败就放行，不至于让程序起不来
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def signal_existing_instance() -> bool:
    """让已在运行的实例把设置窗口亮出来。

    没有这一步，用户第二次双击 exe 会看到"什么都没发生"——因为进程被单实例锁
    静默挡回去了。这是"双击打不开"的真正原因。
    """
    ev = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, WAKE_EVENT_NAME)
    if not ev:
        return False
    try:
        return bool(_kernel32.SetEvent(ev))
    finally:
        _kernel32.CloseHandle(ev)


class Controller(QObject):
    sig_state = Signal(str, str)
    sig_level = Signal(float)
    sig_error = Signal(str)
    sig_notice = Signal(str)
    # 热键回调运行在 RegisterHotKey 的消息线程里，不能直接碰 Qt 控件。
    # 用信号跨线程投递（跨线程的 Auto 连接会自动变成 QueuedConnection），
    # 它会立刻唤醒主线程事件循环——比原先进队列等 50ms 轮询快得多，
    # 而"按下就出现"的体感差别主要就来自这几十毫秒。
    sig_hotkey = Signal()

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.log = get_logger()
        self.cfg = cfg
        self.sm = StateMachine(on_change=lambda p, c: self.sig_state.emit(c.value, c.value))
        self.overlay = Overlay(
            offset_bottom=int(cfg.get("ui.offset_bottom", 72)),
            opacity=float(cfg.get("ui.opacity", 0.94)),
        )
        self.tray: Tray | None = None
        self.fbtn: FloatingButton | None = None
        self.hotkey: HotkeyManager | None = None
        self.recorder: Recorder | None = None
        self.engine = None
        self._target_hwnd = 0
        self._pending_hwnd = 0
        self._pending_from_button = False
        # 持续跟踪"上一个不是我们自己窗口的前台窗口"。
        # 点悬浮球时不能靠"按下这一刻的前台窗口"——那一刻很可能已经是我们自己了，
        # 文字会贴进悬浮球里。这个值是悬浮球路径决定贴到哪里的依据。
        self._last_foreground = 0
        self._session_bytes = 0
        self._hotkey_q: queue.Queue[str] = queue.Queue()
        self._wake_event = 0
        self._settings_dlg: SettingsDialog | None = None
        self._hotkey_ok = True
        self._max_level = 0.0
        self._starting = False

        self.sig_state.connect(self._on_state_changed)
        self.sig_level.connect(self.overlay.set_level)
        self.sig_level.connect(self._track_level)
        self.sig_error.connect(self._on_error)
        self.sig_notice.connect(self._on_notice)
        self.sig_hotkey.connect(self.toggle)

        # 50ms 轮询只用来处理"重复启动唤醒"、托盘菜单点击和前台窗口跟踪。
        # 热键不进这条通道——它走信号，因为这条路上有最多 50ms 的延迟，
        # 正好卡在用户对"按下有没有反应"最敏感的区间。
        self._poll = QTimer(self)
        self._poll.setInterval(50)
        self._poll.timeout.connect(self._drain_hotkey)
        self._poll.start()

    # ---------------- 启动 ----------------
    def start(self) -> None:
        self.tray = Tray(
            on_toggle=lambda: self._hotkey_q.put("toggle"),
            on_settings=self.open_settings,
            on_quit=self.shutdown,
            on_reload=self.reload_config,
            on_toggle_float=self._set_float_visible,
            float_visible=bool(self.cfg.get("ui.float_button", True)),
        )
        self.tray.show()
        self._sync_float_button()
        self._install_hotkey()
        # 自动重置事件：第二个实例 SetEvent 后，这里的 WaitForSingleObject 立刻返回
        self._wake_event = _kernel32.CreateEventW(None, False, False, WAKE_EVENT_NAME)

        if not self._engine_ready():
            self._announce_ready("首次使用，需要先填阿里云密钥")
            QTimer.singleShot(300, lambda: self.open_settings(guide=True))
        else:
            self._announce_ready()

    def _engine_ready(self) -> bool:
        """密钥是否齐了。离线假引擎不算——它本来就不联网，不需要密钥。"""
        if str(self.cfg.get("engine.type", "aliyun")) == "mock":
            return True
        return bool(self.cfg.is_engine_configured())

    def _announce_ready(self, extra: str = "") -> None:
        """启动必须给出可见反馈。

        托盘图标在 Win11 上默认被折叠进 ^ 里，用户双击后如果什么都不弹，
        就会以为程序没打开。悬浮窗 + 气泡是这里唯一的"我起来了"信号。
        """
        # 热键没注册上时，错误提示已经弹过了，别用"已就绪"把它盖掉
        if not self._hotkey_ok:
            return
        binding = str(self.cfg.get("hotkey.binding", "Ctrl+Alt+Space"))
        is_mock = str(self.cfg.get("engine.type")) == "mock"
        # 启动就亮明当前引擎，避免"以为在用云端、其实在跑假引擎"
        head = "离线假引擎" if is_mock else "已就绪"
        self.overlay.notice(extra or f"{head} · {binding}", 3200)
        if self.tray is not None:
            self.tray.notify(
                "语音输入已启动",
                extra or (f"当前离线假引擎，只会输出测试文字"
                          if is_mock else f"按 {binding} 开始说话，再按一次结束"),
                4000,
            )

    def _install_hotkey(self) -> None:
        if self.hotkey is not None:
            self.hotkey.stop()
            self.hotkey = None
        binding = str(self.cfg.get("hotkey.binding", "Ctrl+Alt+Space"))

        def on_press() -> None:
            # 这里跑在热键线程上，只能发信号，不能直接调 toggle()
            try:
                self.sig_hotkey.emit()
            except RuntimeError:
                pass  # 程序正在退出，对象已销毁

        mgr = HotkeyManager(on_press)
        try:
            mgr.start(binding)
            self.hotkey = mgr
            self._hotkey_ok = True
            self.log.info("热键已注册：%s", binding)
        except HotkeyError as exc:
            self._hotkey_ok = False
            self.log.error("热键注册失败：%s", exc)
            self.sig_error.emit(str(exc))

    # ---------------- 悬浮球 ----------------
    def _sync_float_button(self) -> None:
        """按配置显示或隐藏悬浮球，并把状态同步到托盘菜单的勾选框。"""
        on = bool(self.cfg.get("ui.float_button", True))
        if self.tray is not None:
            self.tray.set_float_visible(on)
        if not on:
            if self.fbtn is not None:
                self.fbtn.hide()
            return
        if self.fbtn is None:
            self.fbtn = FloatingButton(
                on_settings=self.open_settings,
                on_hide=self._hide_float_button,
                on_quit=self.shutdown,
            )
            # 点球等同于按快捷键，走同一条 toggle 路径，
            # 但告诉它"这次是从球上发起的"，好让目标窗口用跟踪值而不是即时值
            self.fbtn.sig_clicked.connect(lambda: self.toggle(from_button=True))
            self.fbtn.sig_moved.connect(self._save_float_pos)
            self._place_float_button()
        self.fbtn.set_state(self.sm.state.value)
        self.fbtn.show()

    def _place_float_button(self) -> None:
        btn = self.fbtn
        if btn is None:
            return
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        if geo is None:
            btn.move(200, 200)
            return
        s = btn.width()
        pos = self.cfg.get("ui.float_pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
        else:
            # 画布四周各留 10px 透明给阴影和光晕，贴边要按"看得见的球"算：
            # 直接拿 s 去减会让球离屏幕边缘多出 10px 的视觉空隙。
            x, y = geo.right() - s - 13, geo.bottom() - s - 66
        # 换了显示器或改了分辨率以后，上次的位置可能已经跑到屏幕外了
        x = max(geo.left(), min(x, geo.right() - s))
        y = max(geo.top(), min(y, geo.bottom() - s))
        btn.move(x, y)

    def _save_float_pos(self, x: int, y: int) -> None:
        self.cfg.set("ui.float_pos", [x, y])
        try:
            self.cfg.save()
        except OSError:
            pass

    def _hide_float_button(self) -> None:
        """球右键菜单里的「隐藏这个球」。"""
        self.cfg.set("ui.float_button", False)
        try:
            self.cfg.save()
        except OSError:
            pass
        self._sync_float_button()
        self.overlay.notice("悬浮球已隐藏（右键托盘图标可再打开）", 2600)

    def _set_float_visible(self, visible: bool) -> None:
        """托盘菜单里那个「显示悬浮球」勾选框 —— 球平时半透明，找不着时靠它叫回来。"""
        self.cfg.set("ui.float_button", visible)
        try:
            self.cfg.save()
        except OSError:
            pass
        self._sync_float_button()
        self.overlay.notice(
            "悬浮球已显示" if visible else "悬浮球已隐藏（右键托盘可再打开）", 2000
        )

    def _reset_float_state(self) -> None:
        if self.fbtn is not None:
            self.fbtn.set_state("idle")

    # ---------------- 热键与状态 ----------------
    def _drain_hotkey(self) -> None:
        while True:
            try:
                action = self._hotkey_q.get_nowait()
            except queue.Empty:
                break
            if action == "toggle":
                self.toggle()
        # 用户又双击了一次 exe：单实例锁挡住了新进程，这里负责把界面亮出来
        if self._wake_event and _kernel32.WaitForSingleObject(self._wake_event, 0) == 0:
            self.log.info("收到重复启动信号，打开设置窗口")
            self.open_settings()
        self._track_foreground()

    def _own_hwnds(self) -> set[int]:
        """我们自己那几个窗口的句柄。

        注意 winId() 会强制创建原生窗口，但悬浮窗和悬浮球都早就显示出来了，
        这里只是取回已有句柄，没有副作用。
        """
        ids = {int(self.overlay.winId())}
        if self.fbtn is not None:
            ids.add(int(self.fbtn.winId()))
        return ids

    def _track_foreground(self) -> None:
        """记住"上一个不是我们自己的前台窗口"。

        这是给悬浮球用的：点球的那一刻，前台窗口有可能短暂地变成球自己，
        这时再取 get_foreground_window() 就拿不到用户真正在用的编辑器了。
        所以平时就持续记录，把我们自己排除掉。
        """
        try:
            hwnd = win32util.get_foreground_window()
        except Exception:
            return
        if not hwnd:
            return
        try:
            if hwnd in self._own_hwnds():
                return
        except Exception:
            pass
        self._last_foreground = hwnd

    def toggle(self, from_button: bool = False) -> None:
        state = self.sm.state
        if state == State.IDLE:
            self._start_session(from_button)
        elif state == State.RECORDING:
            self._stop_session()
        else:
            self.log.info("当前状态 %s，忽略此次按键", state.value)

    def _start_session(self, from_button: bool = False) -> None:
        # _starting 会一直持有到 _open_devices 结束。因为下面把开设备的重活
        # 推迟了 40ms，这期间状态机还是 IDLE，如果不禁重入，用户连按两次
        # 就会起两个会话。
        if self._starting:
            return
        self._starting = True
        self._pending_from_button = from_button
        self._begin_session()

    def _resolve_target(self) -> int:
        """文字该贴到哪个窗口。

        热键路径：按下那一刻的前台窗口就是目标，直接取，最准也最快。

        悬浮球路径：点球的那一瞬间前台有可能已经变成球自己了，再取
        get_foreground_window() 拿到的就是球，文字会贴进空气里 —— 这是整个
        悬浮球功能最致命的失败模式。所以优先用平时持续跟踪的 _last_foreground，
        跟踪值失效时才退回即时取值。
        """
        own = self._own_hwnds()
        if not self._pending_from_button:
            return win32util.get_foreground_window()
        hwnd = self._last_foreground
        if hwnd and win32util.is_window(hwnd) and hwnd not in own:
            return hwnd
        now = win32util.get_foreground_window()
        return 0 if now in own else now

    def _begin_session(self) -> None:
        # 密钥没配时不要把人晾在一句报错上——直接弹引导窗，告诉他去哪拿、拿哪个。
        # 这既是"发给别人能用"的前提，也比 save 之后才知道填没填对要省事。
        if not self._engine_ready():
            self.overlay.set_state("error", "")
            self.overlay.repaint()
            self.open_settings(guide=True)
            self.overlay.set_state("idle", "")
            return

        # 目标窗口必须在按下这一刻取。推迟 40ms 后再取，用户可能已经切了窗口。
        hwnd = self._resolve_target()
        self._pending_hwnd = hwnd

        # 顺序很重要：先画框，再响提示音。
        # winsound.Beep 是同步阻塞的，响 45ms 就堵 45ms。它要是排在绘制前面，
        # 就等于把"框出现"硬生生往后推 45ms——用户会看到声音先到、画面后到。
        self.overlay.set_state("recording", "")
        # repaint() 是同步绘制，绕开事件队列——这是"按下就立刻出现"的关键
        self.overlay.repaint()
        if bool(self.cfg.get("ui.sound_cue", True)):
            beep(880, 45)

        # 光 repaint 还不够：它只是把这一帧交给了系统，DWM 要到下一个垂直同步
        # 才真正推到屏幕上。而紧接着的 create_engine/recorder.open 会在主线程
        # 同步阻塞几百毫秒，把这段等待整个堵死。所以让出 40ms 事件循环，
        # 保证"框已可见"这件事先落地，再去干重活。
        QTimer.singleShot(40, self._open_devices)

    def _open_devices(self) -> None:
        """真正打开引擎和麦克风。会阻塞主线程，所以必须在框已经显示之后。"""
        hwnd = self._pending_hwnd
        try:
            try:
                engine = create_engine(
                    self.cfg,
                    on_partial=lambda t: self.sig_state.emit("recording_partial", t),
                    on_error=lambda m: self.log.warning("引擎错误：%s", m),
                )
                engine.start()
            except EngineError as exc:
                self.sig_error.emit(str(exc))
                return

            if self.recorder is None:
                self.recorder = Recorder(
                    on_chunk=self._on_audio_chunk,
                    on_level=self.sig_level.emit,
                )
            try:
                self.recorder.open(self.cfg.get("audio.device"))
            except AudioError as exc:
                engine.cancel()
                self.sig_error.emit(str(exc))
                return

            if not self.sm.try_transition(State.RECORDING):
                engine.cancel()
                self.overlay.set_state("idle", "")  # 别把"录音中"留在屏幕上
                return
            self.engine = engine
            self._target_hwnd = hwnd
            self._session_bytes = 0
            self._max_level = 0.0
            self.recorder.start_session()
            self.log.info("开始录音，目标窗口=%s", hwnd)
        finally:
            self._starting = False

    def _on_audio_chunk(self, pcm: bytes) -> None:
        self._session_bytes += len(pcm)
        eng = self.engine
        if eng is not None:
            try:
                eng.send(pcm)
            except Exception:
                pass

    def _track_level(self, level: float) -> None:
        # 只记峰值：判断"识别为空"到底是没说话，还是麦克风没收到声音
        if level > self._max_level:
            self._max_level = level

    def _stop_session(self) -> None:
        if bool(self.cfg.get("ui.sound_cue", True)):
            beep(560, 45)
        if self.recorder is not None:
            self.recorder.end_session()
        engine, self.engine = self.engine, None
        if engine is None:
            self.sm.force(State.IDLE)
            return
        if self._session_bytes < MIN_SESSION_BYTES:
            engine.cancel()
            self.sm.force(State.IDLE)
            self.log.info("录音过短，丢弃")
            self.sig_error.emit("按太快了：按一次开始，说完再按一次结束")
            return
        if not self.sm.try_transition(State.TRANSCRIBING):
            engine.cancel()
            return
        threading.Thread(
            target=self._finish_worker, args=(engine, self._target_hwnd), daemon=True
        ).start()

    def _finish_worker(self, engine, target_hwnd: int) -> None:
        """识别 + 后处理 + 注入，全部在工作线程，避免阻塞界面。"""
        try:
            raw = engine.finish()
        except EngineError as exc:
            self.sig_error.emit(str(exc))
            self.sm.force(State.IDLE)
            return
        except Exception as exc:
            self.log.error("识别异常：%s\n%s", exc, traceback.format_exc())
            self.sig_error.emit(f"识别失败：{exc}")
            self.sm.force(State.IDLE)
            return

        if not raw.strip():
            stats = getattr(engine, "last_stats", {}) or {}
            self.log.info(
                "识别结果为空（音频 %.1f 秒，峰值电平 %.3f，已发 %s 字节，"
                "收到 %s 条服务端消息，%s 个句末）",
                self._session_bytes / 32000.0, self._max_level,
                stats.get("sent_bytes", "?"), stats.get("messages", "?"),
                stats.get("sentence_end", "?"),
            )
            if self._max_level < 0.02:
                self.sig_error.emit("这次没听到声音，按下后请马上说话")
            else:
                self.sig_error.emit("没听清，再说一次")
            self.sm.force(State.IDLE)
            return

        text = postprocess.process(
            raw,
            remove_filler=bool(self.cfg.get("postprocess.remove_fillers", True)),
            extra_fillers=list(self.cfg.get("postprocess.extra_fillers", []) or []),
        )
        self.log.info("识别完成：%s", text)

        if not self.sm.try_transition(State.INJECTING):
            return
        try:
            result = injector.inject_text(
                text,
                target_hwnd,
                delay=float(self.cfg.get("injection.delay_sec", 0.35)),
                keep_clipboard=bool(self.cfg.get("injection.keep_clipboard", False)),
            )
        except Exception as exc:
            self.log.error("注入异常：%s", exc)
            self.sig_error.emit(f"写入失败：{exc}")
            self.sm.force(State.IDLE)
            return

        if result.ok:
            self.log.info("注入成功，剪贴板还原=%s，快照=%s",
                          result.clipboard_restored, result.snapshot_summary)
            self.sig_state.emit("injecting", f"{len(text)} 字")
        else:
            self.log.warning("注入失败：%s", result.reason)
            self.sig_error.emit(f"没写进去：{result.reason}")
        self.sm.force(State.IDLE)

    # ---------------- UI 回调 ----------------
    def _on_state_changed(self, _prev: str, cur: str) -> None:
        if cur == "recording_partial":
            return
        label = {
            State.IDLE.value: "", State.RECORDING.value: "录音中",
            State.TRANSCRIBING.value: "识别中", State.INJECTING.value: "写入中",
            State.ERROR.value: "出错了",
        }.get(cur, "")
        if self.tray is not None:
            self.tray.set_state(cur, label)
        if self.fbtn is not None:
            self.fbtn.set_state(cur)
        if cur == State.IDLE.value:
            self.overlay.set_state("idle", "")
        elif cur == State.INJECTING.value:
            self.overlay.flash("已写入", "injecting")
        else:
            self.overlay.set_state(cur, "")

    def _on_error(self, msg: str) -> None:
        self.log.error("提示错误：%s", msg)
        self.overlay.flash(msg[:28], "error", 2600)
        if self.fbtn is not None:
            self.fbtn.set_state("error")
            QTimer.singleShot(2600, self._reset_float_state)
        if self.tray is not None:
            self.tray.notify("语音输入", msg)

    def _on_notice(self, msg: str) -> None:
        if self.tray is not None:
            self.tray.setToolTip(f"语音输入 · {msg}")
            self.tray.notify("语音输入", msg)

    # ---------------- 设置 ----------------
    def open_settings(self, guide: bool = False) -> None:
        # 设置窗口已开着（exec 的嵌套事件循环里仍会跑 QTimer），
        # 再次触发时不要开第二个窗口，把它拎到前台就好。
        if self._settings_dlg is not None:
            dlg = self._settings_dlg
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return

        before = str(self.cfg.get("hotkey.binding", ""))
        dlg = SettingsDialog(self.cfg, guide=guide)
        self._settings_dlg = dlg
        try:
            if dlg.exec():
                after = str(self.cfg.get("hotkey.binding", ""))
                if before != after:
                    self._install_hotkey()
                if self.recorder is not None:
                    self.recorder.close()
                    self.recorder = None
                self._sync_float_button()   # 悬浮球可能被开关，位置也可能被重置
                self.overlay.notice("设置已保存", 1800)
        finally:
            self._settings_dlg = None

    def reload_config(self) -> None:
        self.cfg = Config.load()
        self._install_hotkey()
        self._sync_float_button()
        self.sig_notice.emit("配置已重新加载")

    def shutdown(self) -> None:
        self.log.info("退出")
        if self.hotkey is not None:
            self.hotkey.stop()
        if self.recorder is not None:
            self.recorder.close()
        if self.engine is not None:
            try:
                self.engine.cancel()
            except Exception:
                pass
        if self._wake_event:
            _kernel32.CloseHandle(self._wake_event)
            self._wake_event = 0
        QApplication.quit()


def main() -> int:
    setup_logging()
    log = get_logger()

    if not acquire_single_instance():
        # 关键：不能静默退出。用户双击图标就是想看见界面，
        # 所以把"再点一次"翻译成"把已有窗口亮出来"。
        if signal_existing_instance():
            log.info("已有实例在运行，已通知它显示窗口")
        else:
            log.warning("已有实例在运行，唤醒信号发送失败")
        return 0

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("VoiceType")
    app.setApplicationDisplayName("语音输入")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("系统托盘不可用")

    cfg = Config.load()
    ctl = Controller(cfg)
    ctl.start()
    log.info("启动完成")
    return app.exec()
