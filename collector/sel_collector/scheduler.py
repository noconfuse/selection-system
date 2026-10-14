"""
调度器

每个已配置数据源一个循环:
- interval_sec: 两轮采集间隔（默认 300s，即分钟级）
- 失败重试: 单轮内失败退避重连，不中断其他数据源

调度策略（PRD 4.1）: 公开数据分钟级轮询；爬虫按目标站点限速采集。
"""

from __future__ import annotations

import logging
import time

from .base import DataSourceAdapter, DataSourceError
from .sinks import Sink

log = logging.getLogger("sel_collector.scheduler")


class DataSourceLoop:
    """单数据源采集循环"""

    def __init__(self, adapter: DataSourceAdapter, sink: Sink, interval_sec: int = 300, max_retries: int = 3) -> None:
        self.adapter = adapter
        self.sink = sink
        self.interval = interval_sec
        self.max_retries = max_retries

    def run_once(self) -> int:
        """执行一轮采集, 返回写入条数；失败重试后仍失败则抛错由外层处理"""
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                count = 0
                for product in self.adapter.list_products():
                    self.sink.write(product)
                    count += 1
                return count
            except (DataSourceError, OSError, TimeoutError) as e:
                last_err = e
                log.warning("[%s] 第 %d 次采集失败: %s", self.adapter.name, attempt, e)
                if attempt < self.max_retries:
                    time.sleep(attempt * 5)
        raise last_err

    def run_forever(self) -> None:
        try:
            while True:
                try:
                    count = self.run_once()
                    log.info("[%s] 本轮写入 %d 条", self.adapter.name, count)
                except Exception as e:  # noqa: BLE001
                    log.error("[%s] 连续失败，跳过本轮: %s", self.adapter.name, e)
                time.sleep(self.interval)
        finally:
            self.sink.close()