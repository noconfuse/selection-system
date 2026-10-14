"""
电商市场爬虫适配器（方案 C：市场爬虫数据）

对目标电商站点列表页做 HTTP 抓取并用 CSS 选择器提取字段。
设计要点:
- 站点规则（URL、分页、selector、字段映射）全部配置化，新增站点只改配置
- 内置限速(requests_per_sec)、随机 UA、Referer，禁止多线程高压抓取
- 走 requests + BeautifulSoup，未安装时给出明确提示

合规提醒: 请仅在目标站点 robots 允许、且遵守平台服务条款与相关法规的前提下使用，
控制抓取频率，不做高频高压采集。
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Iterable
from urllib.parse import urlencode

from ..base import DataSourceAdapter, clean_price, normalize_int
from ..models import Product

log = logging.getLogger("sel_collector.crawler")


def _import_bs4():
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup
    except ImportError:
        raise ImportError("crawler 适配器需要依赖: pip install beautifulsoup4 requests")


class CrawlerAdapter(DataSourceAdapter):
    name = "crawler"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self._ua_pool = self.config.get(
            "user_agents",
            [
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            ],
        )
        self._rate = float(self.config.get("requests_per_sec", 1.0))
        self._base_url = self.config.get("list_url") or self.config.get("site")
        if not self._base_url:
            raise ValueError("crawler 适配器需要配置 list_url（列表页 URL 模板）")
        self._last_request = 0.0

    # ---- 主流程 ----

    def list_products(self, category: str | None = None, pages: int | None = None, **kwargs) -> Iterable[Product]:
        """抓取列表页并提取商品；分页由配置 page_param 控制，pages 限制页数"""
        list_cfg = self.config.get("list", {})
        max_pages = min(pages or int(list_cfg.get("pages", 1)), int(list_cfg.get("max_pages", 10)))

        BeautifulSoup = _import_bs4()
        import requests  # noqa: PLC0415

        session = requests.Session()
        for page_no in range(1, max_pages + 1):
            url = self._build_page_url(page_no)
            html = self._fetch(session, url)
            soup = BeautifulSoup(html, "html.parser")
            container = list_cfg.get("container")
            cards = soup.select(container) if container else (soup.select(list_cfg["card"]) if list_cfg.get("card") else [])
            if not cards and not list_cfg.get("card"):
                # 无 card selector 时退化: 直接把整页当作一个记录源
                raw = self._extract_from_soup(soup, list_cfg)
                if raw and raw.get(self._src("product_id")):
                    yield self._to_product(raw)
                return
            for card in cards:
                item = self._extract(card, soup, list_cfg)
                if item:
                    yield item
            if not list_cfg.get("page_param"):
                break
        session.close()

    # ---- 抓取与限速 ----

    def _build_page_url(self, page_no: int) -> str:
        page_param = self.config.get("list", {}).get("page_param")
        if not page_param:
            return self._base_url
        sep = "&" if "?" in self._base_url else "?"
        return f"{self._base_url}{sep}{urlencode({page_param: page_no})}"

    def _fetch(self, session, url: str) -> str:
        """带限速与 UA 的请求，失败时抛错（便于任务侧重试调度）"""
        elapsed = time.time() - self._last_request
        if self._rate > 0 and elapsed < 1.0 / self._rate:
            time.sleep(1.0 / self._rate - elapsed)
        self._last_request = time.time()
        resp = session.get(
            url,
            headers={
                "User-Agent": random.choice(self._ua_pool),
                "Referer": self.config.get("referer", self._base_url),
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            timeout=self.config.get("timeout", 15),
        )
        resp.raise_for_status()
        # 部分站点 Content-Type 不声明 charset，requests 会按 latin-1 误读中文编码
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text

    # ---- 字段提取 ----

    def _src(self, field: str) -> str:
        """反查: Product 内部字段对应的源字段名"""
        for src, target in self.field_map.items():
            if target == field:
                return src
        return field

    def _extract(self, card, soup, list_cfg: dict) -> Product | None:
        """从单个商品卡片提取字段。
        `@attr` 取卡片自身属性（如 `@data-id`），`css@attr` 取子元素属性，否则取文本。
        卡片内缺失的字段保持缺失（不回退整页，避免跨卡片串数据）。"""
        raw: dict = {}
        for src_field, sel in list_cfg.get("fields", {}).items():
            if sel.startswith("@"):
                raw[src_field] = (card.get(sel[1:]) or "").strip()
                continue
            els = card.select(self._css(sel))
            if els:
                raw[src_field] = self._extract_value(els[0], sel)
        if "product_id" not in raw or not raw["product_id"]:
            return None
        raw.setdefault("title", raw.get("product_id"))
        return self._to_product(self._platform(), raw)

    @staticmethod
    def _css(sel: str) -> str:
        """剥离 @attr 后缀得到纯 CSS selector"""
        return sel.split("@", 1)[0] if "@" in sel else sel

    @staticmethod
    def _extract_value(el, sel: str) -> str:
        """按 selector 提取：<css>@<attr> 取属性，否则取 strip 后的文本"""
        if "@" in sel:
            attr = sel.split("@", 1)[1]
            return (el.get(attr) or "").strip()
        return el.get_text(strip=True)

    def _extract_from_soup(self, soup, list_cfg: dict) -> dict:
        raw: dict = {}
        for src_field, sel in list_cfg.get("fields", {}).items():
            els = soup.select(self._css(sel))
            if els:
                raw[src_field] = self._extract_value(els[0], sel)
        # 列表页没有卡片时的降级: 无字段即无结果
        return raw

    def _to_product(self, platform: str, raw: dict) -> Product:
        mapped = self._map(raw)
        mapped.setdefault("category", "unknown")
        # 数值清洗: 价格/销量/评价（优先从源值清洗，field_map 直通时也需覆盖）
        price_src = self._src("price")
        if price_src in raw:
            mapped["price"] = clean_price(raw[price_src])
        origin_src = self._src("original_price")
        if origin_src in raw and raw[origin_src]:
            mapped["original_price"] = clean_price(raw[origin_src])
        sales_src = self._src("sales")
        if sales_src in raw:
            mapped["sales"] = self._parse_count(raw[sales_src])
        review_src = self._src("review_count")
        if review_src in raw:
            mapped["review_count"] = self._parse_count(raw[review_src])
        if not mapped.get("price"):
            mapped["price"] = 0.0
        return Product.from_raw(platform, mapped)

    @staticmethod
    def _parse_count(value) -> int:
        """销量/评价数清洗: '已售 1.2万+' / '评价 8000+' / '3,500' -> 整数"""
        s = str(value).replace(",", "").strip()
        m = re.search(r"\d+(?:\.\d+)?", s)  # 前缀文案（"已售""评价"）只取首个数字
        if not m:
            return 0
        num = m.group()
        mul = 1
        tail = s[m.end():]
        if "万" in tail or tail.startswith("万"):
            mul = 10_000
        elif "亿" in tail or tail.startswith("亿"):
            mul = 100_000_000
        try:
            return int(float(num) * mul)
        except (TypeError, ValueError):
            return 0

    def _platform(self) -> str:
        return self.config.get("platform", "crawler")