"""
数据出口（Sink）

采集结果统一写入这里，解耦采集与下游（Kafka / ClickHouse，见 SEL-7）。
- ConsoleSink: 本地验证用
- FileSink: JSONL 落盘，管道接入前先沉淀数据
后续实现 KafkaSink 时按相同 write 接口接入即可。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from .models import Product


class Sink(ABC):
    @abstractmethod
    def write(self, product: Product) -> None: ...

    def close(self) -> None: ...


class ConsoleSink(Sink):
    def write(self, product: Product) -> None:
        print(json.dumps(product.to_kafka(), ensure_ascii=False))


class FileSink(Sink):
    def __init__(self, path: str | Path) -> None:
        self._fp = open(path, "a", encoding="utf-8")

    def write(self, product: Product) -> None:
        self._fp.write(json.dumps(product.to_kafka(), ensure_ascii=False) + "\n")

    def close(self) -> None:
        self._fp.close()


def build_sink(kind: str, config: dict | None = None) -> Sink:
    config = config or {}
    if kind == "console":
        return ConsoleSink()
    if kind == "file":
        return FileSink(config.get("path", "products.jsonl"))
    raise ValueError(f"未知 sink 类型: {kind}")