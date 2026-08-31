import hashlib
import random
from datetime import datetime, timezone


TITLES = [
    "草本植物染发膏家用遮白发一洗黑",
    "氨基酸控油蓬松洗发水贴牌代发",
    "头皮护理精华液按摩营养液",
    "香氛沐浴露持久留香家庭装",
    "生姜防脱洗发水洗护套装",
    "茶树祛痘凝胶痘肌护理厂家直供",
]


async def collect_demo(keyword: str, round_no: int = 1, limit: int = 20):
    seed = int(hashlib.md5(keyword.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).isoformat()
    items = []
    for index in range(min(limit, 12)):
        external_id = f"demo-{seed}-{index}"
        base = 30 + rng.randint(0, 2000)
        sales = base + max(round_no - 1, 0) * rng.randint(1, 80)
        title = f"{keyword} {TITLES[index % len(TITLES)]}"
        items.append({
            "external_id": external_id,
            "title": title,
            "url": f"https://detail.1688.com/offer/{100000000000 + index}.html",
            "image_url": "/static/demo-product.svg",
            "shop_name": "演示供应商",
            "price_min": round(3 + rng.random() * 30, 2),
            "price_max": None,
            "sales_count": sales,
            "raw_sales_text": f"成交 {sales} 笔",
            "collected_at": now,
        })
    return items
