"""阿里云智能语音交互 · 实时语音识别（WebSocket）。

协议要点：
1. Token 由 CreateToken 接口换取（RPC 签名），有效期 24 小时，这里做内存缓存；
2. WebSocket 连上后先发 StartTranscription，收到 TranscriptionStarted 才可送音频；
3. 音频按 100ms 一包（3200 字节）送二进制帧；
4. SentenceEnd 的 output 是该句完整文本，需要按序累加；
5. 结束时发 StopTranscription，等 TranscriptionCompleted。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import queue
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

try:
    import websocket
except ImportError:  # pragma: no cover
    websocket = None

from .base import AsrEngine, EngineError

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_LOCK = threading.Lock()
_CONNECT_TIMEOUT = 8.0
_START_TIMEOUT = 8.0
_FINISH_TIMEOUT = 10.0


def _percent_encode(value: str) -> str:
    return (
        urllib.parse.quote(str(value), safe="~")
        .replace("+", "%20")
        .replace("*", "%2A")
        .replace("%7E", "~")
    )


def _opener_no_proxy() -> urllib.request.OpenerDirector:
    """强制不走系统代理。国内访问阿里云走代理反而会失败。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def create_token(ak_id: str, ak_secret: str, region: str = "cn-shanghai") -> str:
    params = {
        "AccessKeyId": ak_id,
        "Action": "CreateToken",
        "Format": "JSON",
        "RegionId": region,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": str(uuid.uuid4()),
        "SignatureVersion": "1.0",
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2019-02-28",
    }
    canonical = "&".join(f"{_percent_encode(k)}={_percent_encode(params[k])}" for k in sorted(params))
    to_sign = f"GET&%2F&{_percent_encode(canonical)}"
    digest = hmac.new((ak_secret + "&").encode(), to_sign.encode(), hashlib.sha1).digest()
    signature = base64.b64encode(digest).decode()
    url = (
        f"https://nls-meta.{region}.aliyuncs.com/?{canonical}"
        f"&Signature={_percent_encode(signature)}"
    )
    try:
        with _opener_no_proxy().open(url, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise EngineError(f"获取访问令牌失败：{exc}") from exc
    token = (payload or {}).get("Token") or {}
    if not token.get("Id"):
        raise EngineError(f"获取访问令牌失败：{payload}")
    return str(token["Id"])


def get_token(ak_id: str, ak_secret: str, region: str) -> str:
    cache_key = f"{ak_id}:{region}"
    with _TOKEN_LOCK:
        hit = _TOKEN_CACHE.get(cache_key)
        if hit and hit[1] > time.time() + 300:
            return hit[0]
    token = create_token(ak_id, ak_secret, region)
    with _TOKEN_LOCK:
        _TOKEN_CACHE[cache_key] = (token, time.time() + 23 * 3600)
    return token


def clear_token_cache() -> None:
    with _TOKEN_LOCK:
        _TOKEN_CACHE.clear()


def _text_of(payload: dict) -> str:
    """取识别文本。

    阿里云各事件的字段名不统一：SentenceEnd 用 result，
    TranscriptionResultChanged 用 text，老版本文档写的是 output。
    只认其中一个就会永远拿到空字符串。
    """
    for key in ("result", "text", "output"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class AliyunEngine(AsrEngine):
    name = "阿里云实时语音识别"

    def __init__(
        self,
        appkey: str,
        ak_id: str,
        ak_secret: str,
        region: str = "cn-shanghai",
        vocabulary_id: str = "",
        sample_rate: int = 16000,
        enable_punctuation: bool = True,
        enable_itn: bool = True,
        on_partial=None,
        on_error=None,
    ) -> None:
        super().__init__(on_partial, on_error)
        if websocket is None:
            raise EngineError("缺少 websocket-client 依赖")
        self._appkey = appkey
        self._ak_id = ak_id
        self._ak_secret = ak_secret
        self._region = region
        self._vocab = vocabulary_id
        self._sr = sample_rate
        self._punct = enable_punctuation
        self._itn = enable_itn
        # 阿里云要求 32 位十六进制：uuid4().hex 正好 32 位纯 hex。
        # 用 str(uuid4()) 会带连字符变 36 位，网关直接回 Invalid message id。
        self._task_id = uuid.uuid4().hex

        # 上限 400 块 = 40 秒音频。网络变慢时不无限堆内存，满了丢最旧的。
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=400)
        self._ws = None
        self._worker: threading.Thread | None = None
        self._reader: threading.Thread | None = None
        self._started = threading.Event()
        self._completed = threading.Event()
        self._abort = threading.Event()
        self._lock = threading.Lock()
        self._sentences: list[str] = []
        self._last_partial = ""
        self._error: str | None = None
        # 诊断用：发送字节数、收到的服务端消息数、句末数
        self._sent_bytes = 0
        self._messages = 0
        self._sentence_end = 0
        self.last_stats: dict[str, int] = {}

    # ---------------- 对外 ----------------
    def start(self) -> None:
        self._abort.clear()
        self._completed.clear()
        self._started.clear()
        self._error = None
        self._sentences.clear()
        self._last_partial = ""
        self._task_id = uuid.uuid4().hex  # 每次会话一个新 task_id，全程不变
        self._worker = threading.Thread(target=self._pump, name="asr", daemon=True)
        self._worker.start()

    def send(self, pcm: bytes) -> None:
        if not pcm or self._abort.is_set():
            return
        self._sent_bytes += len(pcm)
        try:
            self._queue.put_nowait(pcm)
        except queue.Full:
            # 队列满说明网络跟不上，丢掉最旧的一帧，保证延迟不无限累积
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(pcm)
            except (queue.Empty, queue.Full):
                pass

    def finish(self) -> str:
        try:
            self._queue.put(None, timeout=3.0)  # 哨兵：队列发完即发 StopTranscription
        except queue.Full:
            try:
                while True:
                    self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
        deadline = time.time() + _FINISH_TIMEOUT
        while time.time() < deadline:
            if self._completed.is_set():
                break
            if self._error:
                break
            time.sleep(0.03)
        text = "".join(self._sentences).strip()
        if not text and self._last_partial:
            text = self._last_partial.strip()
        self.last_stats = {
            "sent_bytes": self._sent_bytes,
            "messages": self._messages,
            "sentence_end": self._sentence_end,
        }
        self._cleanup()
        if self._error:
            raise EngineError(self._error)
        return text

    def cancel(self) -> None:
        self._abort.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._cleanup()

    # ---------------- 内部 ----------------
    def _pump(self) -> None:
        """连接 → 握手 → 补发音频 → 收尾，全部在这一个线程里顺序执行。"""
        try:
            token = get_token(self._ak_id, self._ak_secret, self._region)
            url = f"wss://nls-gateway-{self._region}.aliyuncs.com/ws/v1?token={token}"
            ws = websocket.create_connection(url, timeout=_CONNECT_TIMEOUT)
            self._ws = ws
            ws.send(json.dumps(self._start_command(), ensure_ascii=False))

            self._reader = threading.Thread(target=self._read_loop, name="asr-recv", daemon=True)
            self._reader.start()

            if not self._started.wait(_START_TIMEOUT):
                if not self._error:
                    self._error = "识别服务握手超时"
                return

            while True:
                item = self._queue.get()
                if item is None:
                    break
                if self._abort.is_set():
                    break
                try:
                    ws.send_binary(item)
                except Exception as exc:
                    self._error = f"音频发送失败：{exc}"
                    return

            if not self._abort.is_set():
                try:
                    # 每条指令都要带全 5 个字段，缺一个网关就拒
                    ws.send(json.dumps({
                        "header": {
                            "appkey": self._appkey,
                            "message_id": uuid.uuid4().hex,
                            "task_id": self._task_id,
                            "namespace": "SpeechTranscriber",
                            "name": "StopTranscription",
                        }
                    }, ensure_ascii=False))
                except Exception:
                    pass
        except EngineError as exc:
            self._error = str(exc)
            self._emit_error(str(exc))
        except Exception as exc:
            self._error = f"识别服务连接失败：{exc}"
            self._emit_error(self._error)

    def _start_command(self) -> dict:
        payload = {
            "format": "pcm",
            "sample_rate": self._sr,
            "enable_intermediate_result": True,
            "enable_punctuation_prediction": self._punct,
            "enable_inverse_text_normalization": self._itn,
            "enable_voice_detection": False,
        }
        if self._vocab:
            payload["vocabulary_id"] = self._vocab
        return {
            "header": {
                "appkey": self._appkey,
                "message_id": uuid.uuid4().hex,
                "task_id": self._task_id,
                "namespace": "SpeechTranscriber",
                # 新版协议要求 name；老式 task:"transcription" 会被网关判为
                # "Missing message name!"。
                "name": "StartTranscription",
            },
            "payload": payload,
        }

    def _read_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        while not self._abort.is_set():
            try:
                raw = ws.recv()
            except Exception:
                break
            if not raw:
                break
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            header = msg.get("header") or {}
            name = header.get("name", "")
            payload = msg.get("payload") or {}
            self._messages += 1

            if name == "TranscriptionStarted":
                self._started.set()
            elif name == "TranscriptionResultChanged":
                self._last_partial = _text_of(payload)
                preview = "".join(self._sentences) + self._last_partial
                self._emit_partial(preview.strip())
            elif name == "SentenceEnd":
                text = _text_of(payload)
                self._sentence_end += 1
                if text:
                    self._sentences.append(text)
                self._last_partial = ""
                self._emit_partial("".join(self._sentences).strip())
            elif name == "TranscriptionCompleted":
                self._completed.set()
                break
            elif name in ("TaskFailed", "StopTranscriptionFailed"):
                self._error = str(header.get("status_text") or name)
                self._emit_error(self._error)
                self._completed.set()
                break
        self._completed.set()

    def _cleanup(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if self._worker and self._worker.is_alive() and threading.current_thread() is not self._worker:
            self._worker.join(timeout=1.0)
        self._worker = None
