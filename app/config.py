"""配置管理：读写、默认值、密钥加密（Windows DPAPI）。

配置放 %APPDATA%\\VoiceType\\config.json，密钥用当前用户的 DPAPI 加密，
拷到别的机器上解密不出来。
"""
from __future__ import annotations

import base64
import copy
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any

APP_NAME = "VoiceType"
_ENC_PREFIX = "enc:"

DEFAULT_CONFIG: dict[str, Any] = {
    "hotkey": {
        # 组合键写法：modifiers + key，见 hotkey.parse_hotkey 支持的键名
        "binding": "Ctrl+Alt+Space",
        "enabled": True,
    },
    "engine": {
        "type": "aliyun",
        "appkey": "",
        "access_key_id": "",
        "access_key_secret": "",
        "region": "cn-shanghai",
        "vocabulary_id": "",
        "sample_rate": 16000,
        "enable_punctuation": True,
        "enable_itn": True,
    },
    "injection": {
        "method": "paste",
        "delay_sec": 0.35,
        "keep_clipboard": False,
    },
    "audio": {
        "device": None,
        "preroll_sec": 0.5,
    },
    "postprocess": {
        "remove_fillers": True,
        "fix_punctuation": True,
        "extra_fillers": [],
    },
    "ui": {
        "position": "bottom-center",
        "offset_bottom": 72,
        "opacity": 0.94,
        # 按键提示音：按下/松开各一声，解决"按了没反应"的错觉
        "sound_cue": True,
        # 悬浮球：点一下就能开始/停止。好按的两键组合键全被系统占了，
        # 这是"不用记组合键"的兜底入口。
        "float_button": True,
        # 悬浮球位置 [x, y]；None 表示用右下角默认位置
        "float_pos": None,
    },
    "startup": {
        "auto_start": False,
        "silent": True,
    },
}


# ---------------- DPAPI ----------------
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
_kernel32.LocalFree.restype = wintypes.HLOCAL


def _to_blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf


def _from_blob(blob: _DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(blob.pbData, wintypes.HLOCAL))


def dpapi_encrypt(text: str) -> str:
    if not text:
        return ""
    in_blob, _keep = _to_blob(text.encode("utf-8"))
    out_blob = _DATA_BLOB()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise OSError(f"CryptProtectData failed: {ctypes.get_last_error()}")
    raw = _from_blob(out_blob)
    return _ENC_PREFIX + base64.b64encode(raw).decode("ascii")


def dpapi_decrypt(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(_ENC_PREFIX):
        return value
    raw = base64.b64decode(value[len(_ENC_PREFIX):])
    in_blob, _keep = _to_blob(raw)
    out_blob = _DATA_BLOB()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        return ""
    return _from_blob(out_blob).decode("utf-8", "replace")


# ---------------- 配置读写 ----------------
def config_dir() -> Path:
    override = os.environ.get("VOICETYPE_HOME")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def _deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


SECRET_FIELDS = ("appkey", "access_key_id", "access_key_secret")


class Config:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = _deep_merge(DEFAULT_CONFIG, data or {})

    @classmethod
    def load(cls) -> "Config":
        p = config_path()
        if not p.exists():
            cfg = cls()
            cfg.save()
            return cfg
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
        return cls(raw)

    def save(self) -> None:
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = config_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, config_path())

    # 点号访问
    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, path: str, value: Any) -> None:
        parts = path.split(".")
        cur = self.data
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    # 密钥：读时解密，写时加密
    def secret(self, key: str) -> str:
        return dpapi_decrypt(self.get(f"engine.{key}", "") or "")

    def set_secret(self, key: str, value: str) -> None:
        self.set(f"engine.{key}", dpapi_encrypt(value) if value else "")

    def is_engine_configured(self) -> bool:
        return all(self.secret(k) for k in SECRET_FIELDS)
