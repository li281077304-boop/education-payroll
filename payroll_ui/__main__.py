from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from pathlib import Path

from .server import PayrollHttpServer
from .service import PayrollService


def default_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EducationPayroll"
    return Path.home() / "Library" / "Application Support" / "EducationPayroll"


def main() -> None:
    parser = argparse.ArgumentParser(description="工资核算助手 V0.1（本地运行）")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir(), help="本地核算记录保存位置")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    static = Path(__file__).with_name("static")
    server = PayrollHttpServer(("127.0.0.1", args.port), PayrollService(args.data_dir), static)
    url = f"http://127.0.0.1:{server.server_port}/"
    if not args.no_browser:
        threading.Timer(0.15, lambda: webbrowser.open(url)).start()
    print(f"工资核算助手已启动：{url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
