"""命令行入口: python -m sel_collector run --config config.yaml"""

from __future__ import annotations

import argparse
import logging
import sys
import threading

import yaml

from .platforms import available_sources, build_adapter
from .scheduler import DataSourceLoop
from .sinks import build_sink


def _load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


def run(config_path: str, once: bool = False) -> int:
    cfg = _load_config(config_path)
    sources = cfg.get("sources") or cfg.get("collector", {}).get("sources")
    if not sources:
        print("未配置任何数据源: sources 为空", file=sys.stderr)
        return 2

    failed = False
    global_cfg = cfg.get("collector", {}) if cfg.get("collector") else cfg
    threads: list[threading.Thread] = []
    for entry in sources:
        name = entry["source"]
        adapter = build_adapter(name, entry.get("config"))
        sink = build_sink(
            entry.get("sink", global_cfg.get("sink", "console")),
            entry.get("sink_config") or global_cfg.get("sink_config"),
        )
        loop = DataSourceLoop(
            adapter,
            sink,
            interval_sec=int(entry.get("interval_sec", 300)),
            max_retries=int(entry.get("max_retries", 3)),
        )
        if once:
            try:
                count = loop.run_once()
                print(f"[{name}] 本轮写入 {count} 条")
            except Exception as e:  # noqa: BLE001 单源失败不中断其他源
                print(f"[{name}] 本轮采集失败: {e}", file=sys.stderr)
                failed = True
        else:
            print(f"[{name}] 开始循环采集, 每 {entry.get('interval_sec', 300)}s 一轮")
            t = threading.Thread(target=loop.run_forever, name=f"source-{name}", daemon=True)
            threads.append(t)
            t.start()
    for t in threads:
        t.join()  # run_forever 内为无限循环，靠外部信号/SIGINT 终止
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sel_collector")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="启动采集")
    run_p.add_argument("--config", default="config.yaml", help="配置文件路径")
    run_p.add_argument("--once", action="store_true", help="仅执行一轮后退出（验证用）")
    run_p.add_argument("--list-sources", action="store_true", help="列出可用数据源")
    run_p.add_argument("--verbose", action="store_true", help="输出调试日志")

    args = parser.parse_args(argv)
    if args.list_sources:
        print("可用数据源:", ", ".join(available_sources()))
        return 0
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    return run(args.config, args.once)


if __name__ == "__main__":
    raise SystemExit(main())