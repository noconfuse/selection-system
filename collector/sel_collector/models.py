"""
统一商品数据模型（PRD 4.1 数据规范）

所有数据源（公开数据/电商爬虫）采集的数据统一转换为本模型后写入管道。
字段语义覆盖：商品、价格、销量、评价。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Product:
    """商品标准化记录（选品系统的统一数据口径）"""
    platform: str            # 数据源标识: 平台名 / 公开榜单名
    product_id: str          # 商品唯一 ID（数据源内）
    title: str               # 商品标题
    category: str            # 类目（best-effort，缺省 unknown）
    price: float             # 当前售价(元)
    original_price: float | None = None   # 划线价/原价
    sales: int = 0           # 累计销量
    review_count: int = 0    # 评价数
    review_score: float | None = None     # 平均评分(0-5)
    spu_id: str | None = None
    sku_id: str | None = None
    listed_at: str | None = None          # 上架时间(ISO8601)
    collected_at: str = field(default_factory=utc_now)

    def to_kafka(self) -> dict:
        """序列化为管道消息（JSON）"""
        return {
            "platform": self.platform,
            "product_id": self.product_id,
            "title": self.title,
            "category": self.category,
            "price": self.price,
            "original_price": self.original_price,
            "sales": self.sales,
            "review_count": self.review_count,
            "review_score": self.review_score,
            "spu_id": self.spu_id,
            "sku_id": self.sku_id,
            "listed_at": self.listed_at,
            "collected_at": self.collected_at,
        }

    @classmethod
    def from_kafka(cls, payload: dict) -> "Product":
        return cls(
            platform=payload["platform"],
            product_id=str(payload["product_id"]),
            title=payload.get("title", ""),
            category=payload.get("category", "unknown"),
            price=float(payload.get("price", 0) or 0),
            original_price=_opt_float(payload.get("original_price")),
            sales=int(payload.get("sales", 0) or 0),
            review_count=int(payload.get("review_count", 0) or 0),
            review_score=_opt_float(payload.get("review_score")),
            spu_id=str(payload["spu_id"]) if payload.get("spu_id") else None,
            sku_id=str(payload["sku_id"]) if payload.get("sku_id") else None,
            listed_at=payload.get("listed_at"),
            collected_at=payload.get("collected_at", utc_now()),
        )

    @classmethod
    def from_raw(cls, platform: str, raw: dict) -> "Product":
        """从数据源原始行字段创建（字段名经 field_map 映射后传入）"""
        return cls.from_kafka({**raw, "platform": platform})


def _opt_float(v) -> float | None:
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None