"""
数据源适配器基类

每个数据源（公开数据集 / 电商爬虫）实现一个适配器:
- list_products: 拉取商品列表（榜单/分页）
- refresh_detail: 拉取单个商品最新指标（可选）

适配器只负责抓取与字段归一化，不关心调度与写入。
字段名映射在配置中声明: field_map 把源字段名映射到 Product 内部字段。
"""

from __future__ import annotations

import abc
from typing import Iterable

from .models import Product

# 源字段名 -> Product 内部字段名（to_kafka 输出的 key）
DEFAULT_FIELD_MAP: dict[str, str] = {
    "product_id": "product_id",
    "title": "title",
    "category": "category",
    "price": "price",
    "original_price": "original_price",
    "sales": "sales",
    "review_count": "review_count",
    "review_score": "review_score",
    "spu_id": "spu_id",
    "sku_id": "sku_id",
    "listed_at": "listed_at",
}


class DataSourceError(RuntimeError):
    """数据源抓取失败（如网络/解析错误），用于任务侧重试调度"""


class DataSourceAdapter(abc.ABC):
    """数据源适配器抽象基类"""

    name: str = ""

    def __init__(self, config: dict | None = None) -> None:
        self.config: dict = config or {}
        self.field_map = {**DEFAULT_FIELD_MAP, **self.config.get("field_map", {})}

    def _map(self, raw: dict) -> dict:
        """按 field_map 将源字段重命名，供 Product.from_raw 直接消费"""
        out: dict = {}
        for src_key, target_key in self.field_map.items():
            if src_key in raw and raw[src_key] is not None:
                out[target_key] = raw[src_key]
        return out

    @abc.abstractmethod
    def list_products(self, **kwargs) -> Iterable[Product]:
        """拉取商品列表"""

    def refresh_detail(self, product_id: str) -> Product | None:
        """刷新单个商品（默认不做）"""
        return None


def normalize_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_price(value) -> float:
    """价格清洗: '¥1,299.00' / '1299' -> 1299.0"""
    if value is None:
        return 0.0
    s = str(value).replace(",", "").replace("¥", "").replace("￥", "").strip()
    return normalize_float(s) or 0.0