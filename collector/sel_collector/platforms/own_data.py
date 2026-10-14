"""
自有数据适配器（方案 C：自有平台/店铺数据）

支持两种接入方式（在 config 中二选一）:
- file_path: 数据文件（.csv / .json / .jsonl），适合一次性导入历史数据
- api_url: 自有后端接口，返回商品列表（适合持续增量同步）

字段映射通过 field_map 配置（见 base.py DEFAULT_FIELD_MAP）。
体积较大的文件支持按行流式读取。
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Iterable

import requests

from ..base import DataSourceAdapter
from ..models import Product


class OwnDataAdapter(DataSourceAdapter):
    name = "own"

    def list_products(self, **kwargs) -> Iterable[Product]:
        if self.config.get("api_url"):
            yield from self._from_api()
        elif self.config.get("file_path"):
            yield from self._from_file(self.config["file_path"])
        else:
            raise ValueError("own 适配器需要配置 file_path 或 api_url")

    def refresh_detail(self, product_id: str) -> Product | None:
        return None  # 自有数据按列表同步即可，不做单点刷新

    # ---- 文件导入 ----

    def _from_file(self, path: str) -> Iterable[Product]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        with p.open("r", encoding="utf-8-sig") as fp:
            if p.suffix.lower() == ".csv":
                yield from self._rows_to_products(csv.DictReader(fp))
            elif p.suffix.lower() in (".json", ".jsonl"):
                for line in fp:
                    row = json.loads(line)
                    if isinstance(row, list):  # 允许一行一个数组
                        for item in row:
                            yield self._to_product(self._platform(), item)
                    else:
                        yield self._to_product(self._platform(), row)
            else:
                raise ValueError(f"不支持的文件类型: {p.suffix}")

    def _rows_to_products(self, rows) -> Iterable[Product]:
        for row in rows:
            yield self._to_product(self._platform(), row)

    # ---- API 同步 ----

    def _from_api(self) -> Iterable[Product]:
        try:
            resp = requests.get(self.config["api_url"], timeout=self.config.get("timeout", 30))
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise RuntimeError(f"自有数据 API 请求失败: {e}") from e
        items = payload if isinstance(payload, list) else payload.get(self.config.get("list_key", "items"), [])
        for item in items:
            yield self._to_product(self._platform(), item)

    # ---- 归一化 ----

    def _platform(self) -> str:
        return self.config.get("platform", self.config.get("name", "own"))

    def _to_product(self, platform: str, raw: dict) -> Product:
        mapped = self._map(raw)
        mapped.setdefault("category", "unknown")
        return Product.from_raw(platform, mapped)