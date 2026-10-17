"""用已保存的凭据真实建一次识别连接（送 1 秒静音），验证 AppKey 与模型。

这一步能验证到：Token 换取 → WebSocket 握手 → AppKey 有效 → 模型已发布。
比设置里的「测试连接」多覆盖三层。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJ = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
sys.path.insert(0, str(PROJ))

from app.config import Config  # noqa: E402
from app.engine.aliyun import AliyunEngine  # noqa: E402
from app.engine.base import EngineError  # noqa: E402

OUT = PROJ / ".venv" / "asr_check.txt"
lines: list[str] = []


def log(msg: str) -> None:
    print(msg)
    lines.append(msg)


def main() -> int:
    cfg = Config.load()
    appkey = cfg.secret("appkey")
    akid = cfg.secret("access_key_id")
    secret = cfg.secret("access_key_secret")
    region = str(cfg.get("engine.region", "cn-shanghai"))

    log(f"region={region}  appkey len={len(appkey)}")

    partials: list[str] = []
    errors: list[str] = []
    eng = AliyunEngine(
        appkey=appkey, ak_id=akid, ak_secret=secret, region=region,
        on_partial=lambda t: partials.append(t),
        on_error=lambda m: errors.append(m),
    )

    log("\n1) 建立连接…")
    eng.start()

    log("2) 送入 1.0 秒静音音频…")
    chunk = b"\x00\x00" * 1600  # 3200 字节 = 100ms @16k/16bit/mono
    for _ in range(10):
        eng.send(chunk)
        time.sleep(0.12)

    log("3) 结束并等待结果…")
    t0 = time.time()
    try:
        text = eng.finish()
        cost = time.time() - t0
        log(f"   成功，用时 {cost:.1f}s，返回文本={text!r}")
        log("\n结论：AppKey 有效，模型已发布，链路完全打通。")
        log("（静音识别为空是正常的，真实说话就会有字）")
        rc = 0
    except EngineError as exc:
        log(f"   失败：{exc}")
        log("\n结论：连接被拒。常见原因：")
        log("   - AppKey 填错 / 复制时带了空格")
        log("   - 项目没有发布识别模型（项目功能配置 → 修改配置 → 确认使用）")
        log("   - 试用服务没开通，或地域选错")
        rc = 2

    if errors:
        log(f"\n引擎回调错误：{errors}")
    if partials:
        log(f"中间结果回调 {len(partials)} 次，最后一次={partials[-1]!r}")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
