import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DATA_DIR, DB_PATH, DEFAULT_KEYWORDS


DEFAULT_CATEGORIES = [
    ("染发护理", ["植物染发剂", "染发膏"]),
    ("防脱头皮护理", ["防脱洗发水", "头皮精华液", "头皮按摩精油"]),
    ("洗护沐浴", ["控油洗发水", "洗发水套装", "香氛沐浴露"]),
    ("祛痘护理", ["祛痘凝胶"]),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY,
                value TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                category_id INTEGER REFERENCES categories(id),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                platform TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                image_url TEXT,
                shop_name TEXT,
                first_keyword TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                raw_json TEXT,
                UNIQUE(platform, external_id)
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id),
                collected_at TEXT NOT NULL,
                keyword TEXT NOT NULL,
                price_min REAL,
                price_max REAL,
                sales_count INTEGER,
                repurchase_rate REAL,
                raw_sales_text TEXT,
                UNIQUE(product_id, collected_at, keyword)
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_product_time
                ON snapshots(product_id, collected_at);
            CREATE TABLE IF NOT EXISTS collection_runs (
                id INTEGER PRIMARY KEY,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                keyword_count INTEGER NOT NULL DEFAULT 0,
                product_count INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS douyin_opportunities (
                id INTEGER PRIMARY KEY,
                external_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                raw_json TEXT
            );
            CREATE TABLE IF NOT EXISTS douyin_snapshots (
                id INTEGER PRIMARY KEY,
                opportunity_id INTEGER NOT NULL REFERENCES douyin_opportunities(id),
                collected_at TEXT NOT NULL,
                search_volume_min INTEGER,
                search_volume_max INTEGER,
                search_volume_text TEXT,
                growth_rate REAL,
                has_source INTEGER NOT NULL DEFAULT 0,
                recommendation TEXT,
                benefits TEXT,
                raw_json TEXT,
                UNIQUE(opportunity_id, collected_at)
            );
            CREATE INDEX IF NOT EXISTS idx_douyin_snapshots_time
                ON douyin_snapshots(opportunity_id, collected_at);
            """
        )
        keyword_columns = {row["name"] for row in db.execute("PRAGMA table_info(keywords)")}
        if "category_id" not in keyword_columns:
            db.execute("ALTER TABLE keywords ADD COLUMN category_id INTEGER REFERENCES categories(id)")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('auto_enabled','0')")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('interval_hours','12')")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('batch_size','2')")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('pages_per_keyword','2')")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('min_delay_seconds','20')")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('keyword_cursor','0')")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('daily_start_hour','13')")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('last_cycle_date','')")
        db.execute(
            "UPDATE collection_runs SET status='failed', finished_at=?, error='服务中断，任务未完成' WHERE status='running'",
            (utc_now(),),
        )
        count = db.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]
        if count == 0:
            db.executemany(
                "INSERT INTO keywords(value, enabled, created_at) VALUES(?, 1, ?)",
                [(word, utc_now()) for word in DEFAULT_KEYWORDS],
            )
        _migrate_categories(db)


def _migrate_categories(db):
    """Create the initial category structure without touching product history."""
    if db.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        for name, _ in DEFAULT_CATEGORIES:
            db.execute(
                "INSERT INTO categories(name, enabled, created_at) VALUES(?, 1, ?)",
                (name, utc_now()),
            )
    for name, values in DEFAULT_CATEGORIES:
        category = db.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()
        if category:
            placeholders = ",".join("?" for _ in values)
            db.execute(
                f"UPDATE keywords SET category_id=? WHERE category_id IS NULL AND value IN ({placeholders})",
                (category["id"], *values),
            )
    unassigned = db.execute("SELECT COUNT(*) FROM keywords WHERE category_id IS NULL").fetchone()[0]
    if unassigned:
        db.execute(
            "INSERT OR IGNORE INTO categories(name, enabled, created_at) VALUES('其他', 1, ?)",
            (utc_now(),),
        )
        other_id = db.execute("SELECT id FROM categories WHERE name='其他'").fetchone()[0]
        db.execute("UPDATE keywords SET category_id=? WHERE category_id IS NULL", (other_id,))


def list_keywords():
    with connect() as db:
        return [dict(row) for row in db.execute(
            """
            SELECT k.id, k.value,
                   CASE WHEN k.enabled=1 AND COALESCE(c.enabled, 1)=1 THEN 1 ELSE 0 END AS enabled,
                   k.category_id, c.name AS category_name, k.created_at
            FROM keywords k LEFT JOIN categories c ON c.id=k.category_id
            ORDER BY c.id, k.id
            """
        )]


def list_categories():
    with connect() as db:
        categories = [dict(row) for row in db.execute("SELECT * FROM categories ORDER BY id")]
        keywords = [dict(row) for row in db.execute(
            "SELECT id, value, enabled, category_id, created_at FROM keywords ORDER BY id"
        )]
    grouped = {}
    for keyword in keywords:
        grouped.setdefault(keyword["category_id"], []).append(keyword)
    for category in categories:
        category["enabled"] = bool(category["enabled"])
        category["keywords"] = grouped.get(category["id"], [])
    return categories


def replace_categories(categories: list[dict]):
    cleaned_categories = []
    seen_names = set()
    seen_keywords = set()
    for category in categories:
        name = category.get("name", "").strip()
        if not name or name in seen_names:
            raise ValueError("品类名称不能为空或重复")
        seen_names.add(name)
        words = []
        for value in category.get("keywords", []):
            value = value.strip()
            if not value:
                continue
            if value in seen_keywords:
                raise ValueError(f"关键词“{value}”不能同时属于多个品类")
            seen_keywords.add(value)
            words.append(value)
        if not words:
            raise ValueError(f"品类“{name}”至少需要一个关键词")
        cleaned_categories.append({"name": name, "enabled": bool(category.get("enabled", True)), "keywords": words})
    if not cleaned_categories:
        raise ValueError("至少保留一个品类")

    with connect() as db:
        db.execute("DELETE FROM keywords")
        db.execute("DELETE FROM categories")
        for category in cleaned_categories:
            cursor = db.execute(
                "INSERT INTO categories(name, enabled, created_at) VALUES(?, ?, ?)",
                (category["name"], 1 if category["enabled"] else 0, utc_now()),
            )
            db.executemany(
                "INSERT INTO keywords(value, enabled, category_id, created_at) VALUES(?, 1, ?, ?)",
                [(value, cursor.lastrowid, utc_now()) for value in category["keywords"]],
            )
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('keyword_cursor','0')")
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('last_cycle_date','')")
    return list_categories()


def category_keyword_values(category_id: int):
    with connect() as db:
        exists = db.execute("SELECT 1 FROM categories WHERE id=?", (category_id,)).fetchone()
        if not exists:
            return None
        return {row["value"] for row in db.execute(
            "SELECT value FROM keywords WHERE category_id=?", (category_id,)
        )}


def replace_keywords(values: list[str]):
    cleaned = list(dict.fromkeys(v.strip() for v in values if v.strip()))
    replace_categories([{"name": "未分类", "enabled": True, "keywords": cleaned}])
    return list_keywords()


def start_run(mode: str, keyword_count: int) -> int:
    with connect() as db:
        cur = db.execute(
            "INSERT INTO collection_runs(mode,status,started_at,keyword_count) VALUES(?, 'running', ?, ?)",
            (mode, utc_now(), keyword_count),
        )
        return cur.lastrowid


def finish_run(run_id: int, status: str, product_count: int = 0, error: str | None = None):
    with connect() as db:
        db.execute(
            "UPDATE collection_runs SET status=?, finished_at=?, product_count=?, error=? WHERE id=?",
            (status, utc_now(), product_count, error, run_id),
        )


def upsert_product(item: dict, keyword: str, collected_at: str):
    with connect() as db:
        db.execute(
            """
            INSERT INTO products(platform,external_id,title,url,image_url,shop_name,first_keyword,
                                 first_seen_at,last_seen_at,raw_json)
            VALUES('1688',?,?,?,?,?,?,?, ?, ?)
            ON CONFLICT(platform,external_id) DO UPDATE SET
                title=excluded.title, url=excluded.url,
                image_url=COALESCE(excluded.image_url, products.image_url),
                shop_name=COALESCE(excluded.shop_name, products.shop_name),
                last_seen_at=excluded.last_seen_at, raw_json=excluded.raw_json
            """,
            (
                item["external_id"], item["title"], item["url"], item.get("image_url"),
                item.get("shop_name"), keyword, collected_at, collected_at,
                json.dumps(item, ensure_ascii=False),
            ),
        )
        product_id = db.execute(
            "SELECT id FROM products WHERE platform='1688' AND external_id=?",
            (item["external_id"],),
        ).fetchone()[0]
        db.execute(
            """
            INSERT OR REPLACE INTO snapshots(product_id,collected_at,keyword,price_min,price_max,
                                             sales_count,repurchase_rate,raw_sales_text)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                product_id, collected_at, keyword, item.get("price_min"), item.get("price_max"),
                item.get("sales_count"), item.get("repurchase_rate"), item.get("raw_sales_text"),
            ),
        )


def load_products_with_snapshots():
    with connect() as db:
        products = [dict(row) for row in db.execute("SELECT * FROM products")]
        snapshots = [dict(row) for row in db.execute(
            "SELECT * FROM snapshots ORDER BY product_id, collected_at"
        )]
    grouped = {}
    for snap in snapshots:
        grouped.setdefault(snap["product_id"], []).append(snap)
    for product in products:
        product["snapshots"] = grouped.get(product["id"], [])
    return products


def recent_runs(limit: int = 20):
    with connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM collection_runs ORDER BY id DESC LIMIT ?", (limit,)
        )]


def upsert_douyin_opportunity(item: dict, collected_at: str):
    with connect() as db:
        db.execute(
            """
            INSERT INTO douyin_opportunities(external_id,title,first_seen_at,last_seen_at,raw_json)
            VALUES(?,?,?,?,?)
            ON CONFLICT(external_id) DO UPDATE SET
                title=excluded.title, last_seen_at=excluded.last_seen_at, raw_json=excluded.raw_json
            """,
            (item["external_id"], item["title"], collected_at, collected_at, json.dumps(item, ensure_ascii=False)),
        )
        opportunity_id = db.execute(
            "SELECT id FROM douyin_opportunities WHERE external_id=?", (item["external_id"],)
        ).fetchone()[0]
        db.execute(
            """
            INSERT OR REPLACE INTO douyin_snapshots(
                opportunity_id,collected_at,search_volume_min,search_volume_max,search_volume_text,
                growth_rate,has_source,recommendation,benefits,raw_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                opportunity_id, collected_at, item.get("search_volume_min"), item.get("search_volume_max"),
                item.get("search_volume_text"), item.get("growth_rate"), 1 if item.get("has_source") else 0,
                item.get("recommendation"), json.dumps(item.get("benefits", []), ensure_ascii=False),
                json.dumps(item, ensure_ascii=False),
            ),
        )


def load_douyin_opportunities():
    with connect() as db:
        opportunities = [dict(row) for row in db.execute("SELECT * FROM douyin_opportunities")]
        snapshots = [dict(row) for row in db.execute(
            "SELECT * FROM douyin_snapshots ORDER BY opportunity_id, collected_at"
        )]
    grouped = {}
    for snapshot in snapshots:
        grouped.setdefault(snapshot["opportunity_id"], []).append(snapshot)
    for opportunity in opportunities:
        opportunity["snapshots"] = grouped.get(opportunity["id"], [])
    return opportunities


def recent_runs_for_mode(mode: str, limit: int = 20):
    with connect() as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM collection_runs WHERE mode=? ORDER BY id DESC LIMIT ?", (mode, limit)
        )]


def get_settings():
    with connect() as db:
        values = {row["key"]: row["value"] for row in db.execute("SELECT * FROM settings")}
    return {
        "auto_enabled": values.get("auto_enabled", "0") == "1",
        "interval_hours": max(1, int(values.get("interval_hours", "12"))),
        "batch_size": max(1, min(5, int(values.get("batch_size", "2")))),
        "pages_per_keyword": max(1, min(3, int(values.get("pages_per_keyword", "2")))),
        "min_delay_seconds": max(10, min(120, int(values.get("min_delay_seconds", "20")))),
        "keyword_cursor": max(0, int(values.get("keyword_cursor", "0"))),
        "daily_start_hour": max(13, min(23, int(values.get("daily_start_hour", "13")))),
        "last_cycle_date": values.get("last_cycle_date", ""),
    }


def save_settings(
    auto_enabled: bool,
    interval_hours: int,
    batch_size: int = 2,
    pages_per_keyword: int = 2,
    min_delay_seconds: int = 20,
    daily_start_hour: int = 13,
):
    interval_hours = max(1, min(interval_hours, 168))
    batch_size = max(1, min(batch_size, 5))
    pages_per_keyword = max(1, min(pages_per_keyword, 3))
    min_delay_seconds = max(10, min(min_delay_seconds, 120))
    daily_start_hour = max(13, min(daily_start_hour, 23))
    with connect() as db:
        db.executemany(
            "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
            [
                ("auto_enabled", "1" if auto_enabled else "0"),
                ("interval_hours", str(interval_hours)),
                ("batch_size", str(batch_size)),
                ("pages_per_keyword", str(pages_per_keyword)),
                ("min_delay_seconds", str(min_delay_seconds)),
                ("daily_start_hour", str(daily_start_hour)),
            ],
        )
    return get_settings()


def save_keyword_cursor(cursor: int):
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('keyword_cursor',?)", (str(max(0, cursor)),))


def save_last_cycle_date(value: str):
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('last_cycle_date',?)", (value,))
