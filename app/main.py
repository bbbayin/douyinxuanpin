from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import STATIC_DIR
from .db import category_keyword_values, get_settings, init_db, list_categories, list_keywords, load_douyin_opportunities, load_products_with_snapshots, recent_runs, recent_runs_for_mode, replace_categories, replace_keywords, save_settings
from .douyin_ranking import rank_douyin_opportunities
from .douyin_service import run_douyin_collection
from .ranking import rank_products
from .scheduler import scheduler
from .service import run_collection, schedule_live_after_cooldown


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="1688 增长选品", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class KeywordPayload(BaseModel):
    values: list[str]


class CategoryItem(BaseModel):
    id: int | None = None
    name: str
    enabled: bool = True
    keywords: list[str]


class CategoriesPayload(BaseModel):
    categories: list[CategoryItem]


class CollectPayload(BaseModel):
    mode: str = "live"


class DouyinCollectPayload(BaseModel):
    pages: int = 2


class SettingsPayload(BaseModel):
    auto_enabled: bool
    interval_hours: int = 12
    batch_size: int = 2
    pages_per_keyword: int = 2
    min_delay_seconds: int = 20
    daily_start_hour: int = 13


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/keywords")
def keywords_get():
    return list_keywords()


@app.put("/api/keywords")
def keywords_put(payload: KeywordPayload):
    if not payload.values:
        raise HTTPException(400, "至少保留一个关键词")
    return replace_keywords(payload.values)


@app.get("/api/categories")
def categories_get():
    return list_categories()


@app.put("/api/categories")
def categories_put(payload: CategoriesPayload):
    try:
        return replace_categories([item.model_dump() for item in payload.categories])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/collect")
def collect(payload: CollectPayload):
    if payload.mode not in {"live", "demo"}:
        raise HTTPException(400, "mode 必须是 live 或 demo")
    result = run_collection(payload.mode)
    if not result["accepted"]:
        raise HTTPException(409, result["message"])
    return result


@app.post("/api/collect/schedule")
def collect_schedule():
    result = schedule_live_after_cooldown()
    if not result["accepted"]:
        raise HTTPException(409, result["message"])
    return result


@app.post("/api/douyin/collect")
def douyin_collect(payload: DouyinCollectPayload):
    result = run_douyin_collection(payload.pages, headless=False)
    if not result["accepted"]:
        raise HTTPException(409, result["message"])
    return result


@app.get("/api/settings")
def settings_get():
    return get_settings()


@app.put("/api/settings")
def settings_put(payload: SettingsPayload):
    return save_settings(
        payload.auto_enabled,
        payload.interval_hours,
        payload.batch_size,
        payload.pages_per_keyword,
        payload.min_delay_seconds,
        payload.daily_start_hour,
    )


@app.get("/api/products")
def products(
    keyword: str = "",
    category_id: int | None = None,
    min_sales: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
):
    allowed_keywords = None
    if category_id is not None:
        allowed_keywords = category_keyword_values(category_id)
        if allowed_keywords is None:
            raise HTTPException(404, "品类不存在")
    return rank_products(load_products_with_snapshots(), keyword, min_sales, allowed_keywords)[:limit]


@app.get("/api/overview")
def overview():
    ranked = rank_products(load_products_with_snapshots())
    return {
        "product_count": len(ranked),
        "growth_ready": sum(1 for p in ranked if p["daily_velocity"] is not None),
        "high_risk": sum(1 for p in ranked if p["risk_flags"]),
        "latest_run": recent_runs(1)[0] if recent_runs(1) else None,
    }


@app.get("/api/douyin/opportunities")
def douyin_opportunities(limit: int = Query(300, ge=1, le=2000)):
    return rank_douyin_opportunities(load_douyin_opportunities())[:limit]


@app.get("/api/douyin/overview")
def douyin_overview():
    ranked = rank_douyin_opportunities(load_douyin_opportunities())
    runs = recent_runs_for_mode("douyin", 1)
    return {
        "opportunity_count": len(ranked),
        "growing_count": sum(1 for item in ranked if (item["growth_rate"] or 0) > 0),
        "source_count": sum(1 for item in ranked if item["has_source"]),
        "latest_run": runs[0] if runs else None,
    }


@app.get("/api/runs")
def runs():
    return recent_runs()


@app.get("/health")
def health():
    return {"ok": True}
