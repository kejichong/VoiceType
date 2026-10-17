"""直接验证已保存的阿里云凭据：能否换到 AccessToken。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJ = Path(r"D:\WorkBuddyWorkSpace\语音转换应用程序")
sys.path.insert(0, str(PROJ))

from app.config import Config  # noqa: E402
from app.engine.aliyun import create_token  # noqa: E402

OUT = PROJ / ".venv" / "token_check.txt"
lines: list[str] = []


def log(msg: str) -> None:
    print(msg)
    lines.append(msg)


def mask(s: str) -> str:
    if not s:
        return "(空)"
    return s[:4] + "*" * (len(s) - 6) + s[-2:] if len(s) > 8 else "*" * len(s)


def main() -> int:
    cfg = Config.load()
    appkey = cfg.secret("appkey")
    akid = cfg.secret("access_key_id")
    secret = cfg.secret("access_key_secret")
    region = str(cfg.get("engine.region", "cn-shanghai"))

    log(f"engine.type = {cfg.get('engine.type')}")
    log(f"AppKey      = {mask(appkey)}  len={len(appkey)}")
    log(f"AccessKeyID = {mask(akid)}  len={len(akid)}")
    log(f"Secret      = {mask(secret)}  len={len(secret)}")
    log(f"region      = {region}")

    if not (appkey and akid and secret):
        log("\n结论：三项未填全")
        OUT.write_text("\n".join(lines), encoding="utf-8")
        return 1

    log("\n正在向阿里云换取 AccessToken…")
    try:
        token = create_token(akid, secret, region)
        log(f"成功：token = {token[:8]}…（长度 {len(token)}）")
        log("\n结论：AccessKey 有效，凭据没问题")
        rc = 0
    except Exception as exc:
        log(f"失败：{type(exc).__name__}: {exc}")
        log("\n结论：AccessKey 换取 token 失败，看上面的错误信息")
        rc = 2

    OUT.write_text("\n".join(lines), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
