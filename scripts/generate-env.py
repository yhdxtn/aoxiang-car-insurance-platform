#!/usr/bin/env python3
"""Generate a private initial .env without printing secrets or overwriting one."""
import argparse
import base64
import os
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".env")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit("目标环境文件已存在，已停止以保护原密钥。请编辑现有文件。")
    data = (root / ".env.example").read_text(encoding="utf-8")
    database_password = secrets.token_urlsafe(24)
    values = {
        "MYSQL_PASSWORD": database_password, "DB_PASSWORD": database_password,
        "MYSQL_ROOT_PASSWORD": secrets.token_urlsafe(32),
        "DATA_ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
        "BOOTSTRAP_ADMIN_PASSWORD": secrets.token_urlsafe(24),
        "TK_GATEWAY_TOKEN": secrets.token_urlsafe(48),
        "TK_LEDGER_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
    }
    content = "\n".join(
        key + "=" + values[key] if "=" in line and (key := line.split("=", 1)[0]) in values else line
        for line in data.splitlines()
    ) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
        file.write(content)
    print("已生成独立随机密钥和数据库/管理员初始密码：" + str(output))
    print("请填写微信AppID/AppSecret、泰康账号/承保地区及真实域名，再启动正式环境。")
    print("初始管理员用户名为 admin；密码在文件的 BOOTSTRAP_ADMIN_PASSWORD 项。")


if __name__ == "__main__":
    main()

