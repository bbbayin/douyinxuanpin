import unicodedata


DEFAULT_BRANDS = [
    ("欧莱雅", ["巴黎欧莱雅", "loreal", "l'oréal"]),
    ("海飞丝", ["head & shoulders", "headandshoulders"]),
    ("潘婷", ["pantene"]),
    ("飘柔", ["rejoice"]),
    ("沙宣", ["vidal sassoon"]),
    ("清扬", ["clear洗发水"]),
    ("施华蔻", ["schwarzkopf"]),
    ("卡诗", ["kerastase", "kérastase"]),
    ("资生堂", ["shiseido"]),
    ("多芬", ["dove"]),
    ("力士", ["lux"]),
    ("舒肤佳", ["safeguard"]),
    ("玉兰油", ["olay"]),
    ("妮维雅", ["nivea"]),
    ("凡士林", ["vaseline"]),
    ("强生", ["johnson's", "johnsons"]),
    ("维多利亚的秘密", ["维密", "victoria's secret", "victoriassecret"]),
    ("百雀羚", ["pechoin"]),
    ("珀莱雅", ["proya"]),
    ("自然堂", ["chando"]),
    ("相宜本草", ["inoherb"]),
    ("韩束", ["kans"]),
    ("丸美", ["marubi"]),
    ("薇诺娜", ["winona"]),
    ("可复美", []),
    ("夸迪", []),
    ("修丽可", ["skinceuticals"]),
    ("雅诗兰黛", ["estee lauder", "estéelauder"]),
    ("兰蔻", ["lancome", "lancôme"]),
    ("科颜氏", ["kiehl's", "kiehls"]),
    ("SK-II", ["skii"]),
    ("理肤泉", ["la roche-posay", "larocheposay"]),
    ("雅漾", ["avene", "avène"]),
    ("曼秀雷敦", ["mentholatum"]),
    ("云南白药", []),
    ("同仁堂", ["北京同仁堂", "南京同仁堂"]),
    ("蜂花", []),
    ("滋源", ["seeyoung"]),
    ("阿道夫", ["adolph"]),
    ("霸王", ["bawang"]),
    ("舒蕾", ["slek"]),
    ("美加净", ["maxam"]),
    ("片仔癀", []),
    ("隆力奇", []),
    ("高露洁", ["colgate"]),
    ("佳洁士", ["crest"]),
]

REVIEW_SIGNALS = ("官方正品", "正品", "专柜", "品牌授权", "官方旗舰", "旗舰店", "进口原装", "防伪标")


def normalize_brand_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(char for char in normalized if char.isalnum())


def classify_brand(values: list[str | None], brands: list[dict] | None) -> dict:
    texts = [normalize_brand_text(value or "") for value in values if value]
    for brand in brands or []:
        if not brand.get("enabled", True):
            continue
        aliases = [brand.get("name", ""), *(brand.get("aliases") or [])]
        for alias in aliases:
            needle = normalize_brand_text(alias)
            if len(needle) >= 2 and any(needle in text for text in texts):
                return {
                    "brand_status": "blocked",
                    "brand_name": brand.get("name", alias),
                    "brand_reason": f"命中品牌：{brand.get('name', alias)}",
                    "brand_alias": alias,
                }
    for signal in REVIEW_SIGNALS:
        needle = normalize_brand_text(signal)
        if any(needle in text for text in texts):
            return {
                "brand_status": "review",
                "brand_name": None,
                "brand_reason": f"疑似品牌：{signal}",
                "brand_alias": signal,
            }
    return {"brand_status": "safe", "brand_name": None, "brand_reason": "", "brand_alias": None}
