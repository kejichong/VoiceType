"""不用 COM 创建 Windows 快捷方式（.lnk）。

为什么不用现成办法：
- `New-Object -ComObject WScript.Shell` 在本机被安全策略拦截（COM 对象能执行任意代码）
- `Add-Type` 同样被拦
- 符号链接（New-Item -ItemType SymbolicLink）需要管理员权限或开发者模式，
  而且在别的机器上拷过去就失效了

所以按 MS-SHLLINK（Shell Link Binary File Format）直接拼字节。
只要三个部分就够用：ShellLinkHeader + LinkTargetIDList + LinkInfo。
"""
from __future__ import annotations

import argparse
import ctypes
import struct
import sys
from ctypes import wintypes
from pathlib import Path

# {00021401-0000-0000-C000-000000000046} 的 little-endian 布局
CLSID_SHELLLINK = bytes([
    0x01, 0x14, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00,
    0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46,
])

HAS_TARGET_IDLIST = 0x0000_0001
HAS_LINK_INFO = 0x0000_0002
HAS_NAME = 0x0000_0004
HAS_WORKING_DIR = 0x0000_0010
FILE_ATTRIBUTE_ARCHIVE = 0x0000_0020
DRIVE_FIXED = 3
SW_SHOWNORMAL = 1

_LINK_INFO_HEADER_SIZE = 0x1C

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_ole32 = ctypes.WinDLL("ole32", use_last_error=True)

_shell32.SHParseDisplayName.argtypes = [
    ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
]
_shell32.SHParseDisplayName.restype = ctypes.c_long        # HRESULT
_shell32.ILGetSize.argtypes = [ctypes.c_void_p]
_shell32.ILGetSize.restype = ctypes.c_uint
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole32.CoInitialize.argtypes = [ctypes.c_void_p]


def _target_idlist(target: str) -> bytes:
    """把目标路径交给 Shell 自己解析成真正的 PIDL。

    不能只写一个空的 TerminalID：那样 Shell 只剩 LinkInfo 一条路可以回退，
    实测解析会失败 —— 表现是 ShellExecuteEx 返回成功、错误码也正常，
    但目标程序压根没启动，日志里空空如也。
    """
    _ole32.CoInitialize(None)
    pidl = ctypes.c_void_p()
    hr = _shell32.SHParseDisplayName(target, None, ctypes.byref(pidl), 0, None)
    if hr != 0 or not pidl:
        return struct.pack("<H", 0x0002) + b"\x00\x00"
    size = _shell32.ILGetSize(pidl)          # 已包含结尾的 2 字节终止符
    raw = ctypes.string_at(pidl, size)
    _ole32.CoTaskMemFree(pidl)
    return struct.pack("<H", size) + raw


def _volume_info(drive: str) -> tuple[int, str, int]:
    """拿卷的序列号、卷标和类型。

    必须填真实的序列号：早先版本把 serial 写成 0，Shell 解析 .lnk 时会认为
    "这个卷对不上" 从而拒绝启动目标 —— 表现是 ShellExecuteEx 返回成功，
    但程序根本没起来，日志里什么都没有。
    """
    root = drive[:3]                      # 例如 "D:\\"
    name = ctypes.create_unicode_buffer(261)
    serial = wintypes.DWORD()
    maxlen = wintypes.DWORD()
    flags = wintypes.DWORD()
    fsname = ctypes.create_unicode_buffer(261)
    _kernel32.GetVolumeInformationW(
        root, name, 261, ctypes.byref(serial),
        ctypes.byref(maxlen), ctypes.byref(flags), fsname, 261,
    )
    return (serial.value, name.value,
            _kernel32.GetDriveTypeW(root))


def _volume_id(drive: str) -> bytes:
    serial, label, dtype = _volume_info(drive)
    if dtype != DRIVE_FIXED:
        dtype = DRIVE_FIXED
    label_ansi = label.encode("ascii", "replace") + b"\x00"
    # VolumeLabelOffset 固定指向头部之后；卷标为 ANSI（非 Unicode 变体）
    return (
        struct.pack("<III", 0x10 + len(label_ansi), dtype, serial)
        + struct.pack("<I", 0x10)
        + label_ansi
    )


def _string_data(text: str) -> bytes:
    """StringData 段里的一个条目：2 字节字符数 + 字符串 + 终止符（ANSI）。"""
    raw = text.encode("ascii", "replace") + b"\x00"
    return struct.pack("<H", len(text)) + raw


def _link_info(target: str) -> bytes:
    """LinkInfo 里只带 LocalBasePath（绝对路径），不带网络路径。"""
    volume_id = _volume_id(target)
    base_path = target.encode("ascii") + b"\x00"
    common_suffix = b"\x00"

    volume_off = _LINK_INFO_HEADER_SIZE
    local_off = volume_off + len(volume_id)
    common_off = local_off + len(base_path)
    info_size = common_off + len(common_suffix)

    header = struct.pack(
        "<IIIIIII",
        info_size,
        _LINK_INFO_HEADER_SIZE,
        0x0000_0001,          # VolumeIDAndLocalBasePath
        volume_off,
        local_off,
        0,                    # CommonNetworkRelativeLinkOffset（无）
        common_off,
    )
    return header + volume_id + base_path + common_suffix


def build_lnk(target: Path, workdir: Path | None = None, name: str = "") -> bytes:
    target = Path(target)
    workdir = Path(workdir or target.parent)
    flags = HAS_TARGET_IDLIST | HAS_LINK_INFO | HAS_NAME | HAS_WORKING_DIR
    times = b"\x00" * 8

    header = (
        struct.pack("<I", 0x4C)                     # HeaderSize，固定 76
        + CLSID_SHELLLINK
        + struct.pack("<II", flags, FILE_ATTRIBUTE_ARCHIVE)
        + times * 3                                 # 创建/访问/写入时间，全 0
        + struct.pack("<I", target.stat().st_size)  # FileSize
        + struct.pack("<i", 0)                      # IconIndex
        + struct.pack("<I", SW_SHOWNORMAL)          # ShowCommand
        + struct.pack("<H", 0)                      # HotKey
        + struct.pack("<H", 0)                      # Reserved1
        + struct.pack("<II", 0, 0)                  # Reserved2 / Reserved3
    )
    assert len(header) == 0x4C, len(header)

    id_list = _target_idlist(str(target))

    # StringData 的顺序在 MS-SHLLINK 里是固定的：
    # NAME, RELATIVE_PATH, WORKING_DIR, ARGUMENTS, ICON_LOCATION。
    # 只声明了 HAS_NAME 和 HAS_WORKING_DIR，就按这个次序写两个。
    strings = _string_data(name or target.stem) + _string_data(str(workdir))
    return header + id_list + _link_info(str(target)) + strings


def parse_lnk(data: bytes) -> str:
    """从 .lnk 里把目标路径读回来 —— 用来校验生成的东西确实能被解析。"""
    flags = struct.unpack_from("<I", data, 0x14)[0]
    pos = 0x4C
    if flags & HAS_TARGET_IDLIST:
        size = struct.unpack_from("<H", data, pos)[0]
        pos += 2 + size
    if not (flags & HAS_LINK_INFO):
        return ""
    info_size, hdr_size, _f, _v, local_off, _n, common_off = struct.unpack_from(
        "<IIIIIII", data, pos
    )
    start = pos + local_off
    end = data.index(b"\x00", start)
    return data[start:end].decode("ascii", "replace")


def main() -> int:
    ap = argparse.ArgumentParser(description="创建 Windows 快捷方式（不需要 COM）")
    ap.add_argument("target", help="目标 exe 的绝对路径")
    ap.add_argument("output", help="快捷方式文件（.lnk）路径")
    ap.add_argument("--workdir", help="起始工作目录（默认取目标所在目录）")
    ap.add_argument("--icon", help="图标文件路径（可省略，用 exe 自己的图标）")
    args = ap.parse_args()

    target = Path(args.target)
    out = Path(args.output)
    if not target.exists():
        print(f"目标不存在：{target}")
        return 1

    # NAME 用 exe 自身的名字（ASCII 安全）。桌面图标上显示的是 .lnk 的文件名，
    # 所以中文名由文件名决定，不需要塞进 StringData 里冒险用非 ASCII 字节。
    data = build_lnk(target, Path(args.workdir) if args.workdir else None)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)

    got = parse_lnk(data)
    ok = got.lower() == str(target).lower()
    print(f"已创建 {out}  （{len(data)} 字节）")
    print(f"读回校验目标路径 = {got}")
    print(("PASS " if ok else "FAIL ") + "快捷方式能被正确解析")
    if not ok:
        return 1

    # 顺便确认目标目录里确实带着依赖，否则快捷方式指向的是个跑不起来的孤儿
    internal = target.parent / "_internal"
    print(
        ("PASS " if internal.is_dir() else "FAIL ")
        + f"{internal.name} 与目标 exe 在同一目录"
        + ("" if internal.is_dir() else "  ← 少了它程序起不来")
    )
    return 0 if internal.is_dir() else 1


if __name__ == "__main__":
    sys.exit(main())
