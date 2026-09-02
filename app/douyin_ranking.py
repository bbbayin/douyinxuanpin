import json
import math

from .collectors.alibaba1688 import search_url
from .brands import classify_brand


def rank_douyin_opportunities(opportunities: list[dict], brands: list[dict] | None = None) -> list[dict]:
    ranked = []
    for opportunity in opportunities:
        if not opportunity["snapshots"]:
            continue
        latest = opportunity["snapshots"][-1]
        growth = latest.get("growth_rate")
        volume_max = latest.get("search_volume_max") or 0
        benefits = json.loads(latest.get("benefits") or "[]")
        score = math.log1p(volume_max) * 8 + max(min(growth or 0, 6), -1) * 12
        if latest.get("has_source"):
            score += 10
        score += len(benefits) * 2
        brand = classify_brand([opportunity["title"]], brands)
        ranked.append({
            "id": opportunity["id"], "external_id": opportunity["external_id"], "title": opportunity["title"],
            "first_seen_at": opportunity["first_seen_at"], "last_seen_at": opportunity["last_seen_at"],
            "search_volume_min": latest.get("search_volume_min"),
            "search_volume_max": latest.get("search_volume_max"),
            "search_volume_text": latest.get("search_volume_text"),
            "growth_rate": growth, "has_source": bool(latest.get("has_source")),
            "recommendation": latest.get("recommendation") or "",
            "benefits": benefits, "collected_at": latest["collected_at"],
            "snapshot_count": len(opportunity["snapshots"]), "score": round(score, 1),
            "source_page": max(1, int(latest.get("source_page") or 1)),
            "alibaba_url": search_url(opportunity["title"]),
            **brand,
        })
    if ranked:
        latest_collection = max(item["last_seen_at"] for item in ranked)
        ranked = [item for item in ranked if item["last_seen_at"] == latest_collection]
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked
