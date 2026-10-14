"""
公开数据源适配器（方案 C：公开数据）

接入公开开放的电商/榜单数据接口或公开数据集:
- api_url: 返回商品列表的开放接口（GET），JSON 数组或 {list_key: [...]}
- file_path: 本地公开数据集文件（.csv / .jsonl）

正适合的典型来源: 公开热销榜接口、开放数据集、可公开访问的榜单 REST API。
字段映射通过 field_map 配置。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

import requests

from ..base import DataSourceAdapter
from ..models import Product


class PublicSourceAdapter(DataSourceAdapter):
    name = "public"

    def list_products(self, **kwargs) -> Iterable[Product]:
        if self.config.get("api_url"):
            yield from self._from_api()
        elif self.config.get("file_path"):
            yield from self._from_file(self.config["file_path"])
        else:
            raise ValueError("public 适配器需要配置 api_url 或 file_path")

    def refresh_detail(self, product_id: str) -> Product | None:
        detail_url = self.config.get("detail_url")
        if not detail_url:
            return None
        url = detail_url.format(product_id=product_id)
        try:
            resp = requests.get(url, timeout=self.config.get("timeout", 30))
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise RuntimeError(f"公开数据详情请求失败: {e}") from e
        return self._to_product(self._platform(), payload)

    # ---- API ----

    def _from_api(self) -> Iterable[Product]:
        try:
            resp = requests.get(self.config["api_url"], timeout=self.config.get("timeout", 30))
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise RuntimeError(f"公开数据 API 请求失败: {e}") from e
        items = payload if isinstance(payload, list) else payload.get(self.config.get("list_key", "items"), [])
        for item in items:
            yield self._to_product(self._platform(), item)

    # ---- 文件 ----

    def _from_file(self, path: str) -> Iterable[Product]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        if p.suffix.lower() == ".csv":
            with p.open("r", encoding="utf-8-sig") as fp:
                for row in csv.DictReader(fp):
                    yield self._to_product(self._platform(), row)
        elif p.suffix.lower() == ".jsonl":
            with p.open("r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    yield self._to_product(self._platform(), json.loads(line))
        else:
            raise ValueError(f"公开数据集暂不支持该格式: {p.suffix}")

    # ---- 归一化 ----

    def _platform(self) -> str:
        return self.config.get("platform", "public")

    def _to_product(self, platform: str, raw: dict) -> Product:
        mapped = self._map(raw)
        mapped.setdefault("category", "unknown")
        return Product.from_raw(platform, mapped)