"""平台/数据源适配器注册表: 按配置声明加载可用数据源"""

from __future__ import annotations

from ..base import DataSourceAdapter
from .public_source import PublicSourceAdapter
from .crawler import CrawlerAdapter
from .own_data import OwnDataAdapter

_ADAPTERS: dict[str, type[DataSourceAdapter]] = {
    PublicSourceAdapter.name: PublicSourceAdapter,
    CrawlerAdapter.name: CrawlerAdapter,
    OwnDataAdapter.name: OwnDataAdapter,
}


def register(adapter_cls: type[DataSourceAdapter]) -> None:
    """注册新数据源适配器"""
    _ADAPTERS[adapter_cls.name] = adapter_cls


def build_adapter(name: str, config: dict | None = None) -> DataSourceAdapter:
    if name not in _ADAPTERS:
        raise ValueError(f"未注册数据源: {name}, 可用: {sorted(_ADAPTERS)}")
    return _ADAPTERS[name](config)


def available_sources() -> list[str]:
    return sorted(_ADAPTERS)