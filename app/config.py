from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "products.db"
BROWSER_PROFILE = DATA_DIR / "browser_profile"
DOUYIN_BROWSER_PROFILE = DATA_DIR / "douyin_browser_profile"
STATIC_DIR = ROOT / "static"

DEFAULT_KEYWORDS = [
    "植物染发剂",
    "染发膏",
    "防脱洗发水",
    "头皮精华液",
    "控油洗发水",
    "洗发水套装",
    "香氛沐浴露",
    "头皮按摩精油",
    "祛痘凝胶",
]

RISK_TERMS = {
    "生发": "功效宣称风险",
    "防脱": "功效宣称风险",
    "祛痘": "功效宣称风险",
    "美白": "功效宣称风险",
    "消毒": "消毒产品资质风险",
    "医用": "医疗相关资质风险",
    "治疗": "医疗功效宣称风险",
    "正品": "品牌与授权风险",
}
