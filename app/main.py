from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import STATIC_DIR
from .db import category_keyword_values, get_settings, init_db, list_brands, list_categories, list_keywords, load_douyin_opportunities, load_products_with_snapshots, recent_runs, recent_runs_for_mode, replace_brands, replace_categories, replace_keywords, save_settings
from .douyin_ranking import rank_douyin_opportunities
from .douyin_navigation import run_douyin_navigation
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


class BrandItem(BaseModel):
    id: int | None = None
    name: str
    aliases: list[str] = Field(default_factory=list)
    enabled: bool = True


class BrandsPayload(BaseModel):
    brands: list[BrandItem]


class CollectPayload(BaseModel):
    mode: str = "live"


class DouyinCollectPayload(BaseModel):
    pages: int = 2


class DouyinOpenPayload(BaseModel):
    action: str


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


@app.get("/api/brands")
def brands_get():
    return list_brands()


@app.put("/api/brands")
def brands_put(payload: BrandsPayload):
    try:
        return replace_brands([item.model_dump() for item in payload.brands])
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
    hide_brands: bool = True,
):
    allowed_keywords = None
    if category_id is not None:
        allowed_keywords = category_keyword_values(category_id)
        if allowed_keywords is None:
            raise HTTPException(404, "品类不存在")
    ranked = rank_products(load_products_with_snapshots(), keyword, min_sales, allowed_keywords, list_brands())
    if hide_brands:
        ranked = [item for item in ranked if item["brand_status"] != "blocked"]
    return ranked[:limit]


@app.get("/api/overview")
def overview(hide_brands: bool = True):
    all_ranked = rank_products(load_products_with_snapshots(), brands=list_brands())
    blocked = sum(1 for item in all_ranked if item["brand_status"] == "blocked")
    ranked = [item for item in all_ranked if item["brand_status"] != "blocked"] if hide_brands else all_ranked
    return {
        "product_count": len(ranked),
        "growth_ready": sum(1 for p in ranked if p["daily_velocity"] is not None),
        "high_risk": sum(1 for p in ranked if p["risk_flags"]),
        "brand_blocked_count": blocked,
        "latest_run": recent_runs(1)[0] if recent_runs(1) else None,
    }


@app.get("/api/douyin/opportunities")
def douyin_opportunities(limit: int = Query(300, ge=1, le=2000), hide_brands: bool = True):
    ranked = rank_douyin_opportunities(load_douyin_opportunities(), list_brands())
    if hide_brands:
        ranked = [item for item in ranked if item["brand_status"] != "blocked"]
    return ranked[:limit]


@app.post("/api/douyin/opportunities/{opportunity_id}/open")
def douyin_open(opportunity_id: int, payload: DouyinOpenPayload):
    opportunity = next(
        (item for item in rank_douyin_opportunities(load_douyin_opportunities(), list_brands()) if item["id"] == opportunity_id),
        None,
    )
    if opportunity is None:
        raise HTTPException(404, "抖音机会词不存在")
    if payload.action == "source" and not opportunity["has_source"]:
        raise HTTPException(409, "该机会词当前没有官方货源")
    result = run_douyin_navigation(
        payload.action, opportunity["title"], opportunity.get("source_page", 1)
    )
    if not result["accepted"]:
        raise HTTPException(409, result["message"])
    return result


@app.get("/api/douyin/overview")
def douyin_overview(hide_brands: bool = True):
    all_ranked = rank_douyin_opportunities(load_douyin_opportunities(), list_brands())
    blocked = sum(1 for item in all_ranked if item["brand_status"] == "blocked")
    ranked = [item for item in all_ranked if item["brand_status"] != "blocked"] if hide_brands else all_ranked
    runs = recent_runs_for_mode("douyin", 1)
    return {
        "opportunity_count": len(ranked),
        "growing_count": sum(1 for item in ranked if (item["growth_rate"] or 0) > 0),
        "source_count": sum(1 for item in ranked if item["has_source"]),
        "brand_blocked_count": blocked,
        "latest_run": runs[0] if runs else None,
    }


@app.get("/api/runs")
def runs():
    return recent_runs()


@app.get("/health")
def health():
    return {"ok": True}
