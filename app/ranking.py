import math
from datetime import datetime

from .config import RISK_TERMS


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def risk_flags(title: str) -> list[str]:
    return [f"{term}：{reason}" for term, reason in RISK_TERMS.items() if term in title]


def sales_scope(snapshot: dict) -> str:
    return "all_network" if "全网" in (snapshot.get("raw_sales_text") or "") else "offer"


def comparable_daily_baseline(snaps: list[dict], latest: dict):
    candidates = []
    for snapshot in snaps[:-1]:
        hours = (_dt(latest["collected_at"]) - _dt(snapshot["collected_at"])).total_seconds() / 3600
        if 20 <= hours <= 28 and sales_scope(snapshot) == sales_scope(latest):
            candidates.append((abs(hours - 24), snapshot, hours))
    if not candidates:
        return None, None
    _, snapshot, hours = min(candidates, key=lambda item: item[0])
    return snapshot, hours


def rank_products(
    products: list[dict],
    keyword: str = "",
    min_sales: int = 0,
    allowed_keywords: set[str] | None = None,
) -> list[dict]:
    ranked = []
    for product in products:
        if keyword and keyword not in (product.get("first_keyword") or "") and keyword not in product["title"]:
            continue
        snaps = [s for s in product["snapshots"] if s.get("sales_count") is not None]
        if allowed_keywords is not None:
            snaps = [s for s in snaps if s.get("keyword") in allowed_keywords]
        if not snaps:
            continue
        latest = snaps[-1]
        if latest["sales_count"] < min_sales:
            continue
        previous, hours = comparable_daily_baseline(snaps, latest)
        delta = None
        growth_rate = None
        velocity = None
        data_quality_issue = None
        raw_delta = None
        if previous:
            delta = latest["sales_count"] - previous["sales_count"]
            raw_delta = delta
            growth_rate = delta / max(previous["sales_count"], 1)
            if delta < 0:
                data_quality_issue = "累计销量回落，疑似展示口径变化"
            elif growth_rate > 3 and delta > 3000:
                data_quality_issue = "单日增幅异常，已从趋势排名排除"
            else:
                velocity = delta * 24 / hours
            if data_quality_issue:
                delta = None
                growth_rate = None
        sales_signal = math.log1p(max(latest["sales_count"], 0)) * 6
        growth_signal = 0 if velocity is None else max(min(velocity, 1000), -100) * 0.7
        rate_signal = 0 if growth_rate is None else max(min(growth_rate, 3), -1) * 18
        score = round(sales_signal + growth_signal + rate_signal, 1)
        flags = risk_flags(product["title"])
        ranked.append({
            **{k: v for k, v in product.items() if k not in {"snapshots", "raw_json"}},
            "image_url": product.get("image_url") or ("/static/demo-product.svg" if str(product.get("external_id", "")).startswith("demo-") else None),
            "keyword": latest["keyword"],
            "price_min": latest["price_min"],
            "price_max": latest["price_max"],
            "sales_count": latest["sales_count"],
            "raw_sales_text": latest["raw_sales_text"],
            "collected_at": latest["collected_at"],
            "snapshot_count": len(snaps),
            "interval_hours": None if hours is None else round(hours, 1),
            "sales_delta": delta,
            "raw_sales_delta": raw_delta,
            "growth_rate": None if growth_rate is None else round(growth_rate, 4),
            "daily_velocity": None if velocity is None else round(velocity, 1),
            "score": score,
            "risk_flags": flags,
            "sales_scope": sales_scope(latest),
            "data_quality_issue": data_quality_issue,
            "comparison_note": (
                data_quality_issue
                or (f"与约{round(hours, 1)}小时前同口径快照比较" if previous else "等待次日同一时段、同一口径快照")
            ),
            "confidence": "medium" if previous and not data_quality_issue else "baseline",
        })
    ranked.sort(key=lambda x: (x["daily_velocity"] is not None, x["score"]), reverse=True)
    return ranked
