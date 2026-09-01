import unittest

from app.collectors.alibaba1688 import is_login_url, offer_id, parse_number, parse_prices, parse_repurchase_rate, parse_sales, parse_shop_name, search_url
from app.ranking import rank_products, risk_flags
from app.collectors.douyin import parse_card_text, parse_growth, parse_volume_range
from app.douyin_ranking import rank_douyin_opportunities


class ParsingTests(unittest.TestCase):
    def test_number_units(self):
        self.assertEqual(parse_number("1.2万"), 12000)
        self.assertEqual(parse_number("3500"), 3500)

    def test_sales(self):
        self.assertEqual(parse_sales("近30天成交 1.3万 笔")[0], 13000)
        self.assertEqual(parse_sales("已有 666 人付款")[0], 666)
        self.assertEqual(parse_sales("全网1.6万+件")[0], 16000)
        self.assertEqual(parse_sales("4.8万+件")[0], 48000)

    def test_price_and_offer(self):
        self.assertEqual(parse_prices("¥ 4.50 - 8.90"), (4.5, 8.9))
        self.assertEqual(parse_prices("¥\n4\n.5\n运费3元"), (4.5, None))
        self.assertEqual(offer_id("https://detail.1688.com/offer/123456.html?x=1"), "123456")
        self.assertEqual(offer_id("http://detail.m.1688.com/page/index.html?offerId=830121548679"), "830121548679")
        self.assertTrue(is_login_url("https://login.1688.com/member/signin.htm"))
        self.assertFalse(is_login_url("https://s.1688.com/selloffer/offer_search.htm"))
        self.assertIn("%D6%B2%CE%EF", search_url("植物"))
        self.assertTrue(search_url("植物", 2).endswith("&beginPage=2"))
        text = "回头率 54%\n佛山米菲娜生物科技有限公司"
        self.assertEqual(parse_repurchase_rate(text), 0.54)
        self.assertEqual(parse_shop_name(text), "佛山米菲娜生物科技有限公司")

    def test_douyin_opportunity_card(self):
        text = "收藏\n高中生洗发水\n搜索扶持\n+0\n搜索次数\n2万-2.5万\n成交增速\n554.75%\n发相似品\n找货源"
        item = parse_card_text(text)
        self.assertEqual(item["title"], "高中生洗发水")
        self.assertEqual(parse_volume_range("2万-2.5万"), (20000, 25000))
        self.assertEqual(parse_volume_range("小于50"), (0, 50))
        self.assertEqual(parse_growth("554.75%"), 5.5475)
        self.assertTrue(item["has_source"])

    def test_douyin_links_and_source_page(self):
        ranked = rank_douyin_opportunities([{
            "id": 9, "title": "高中生洗发水", "first_seen_at": "2026-09-01T05:00:00+00:00",
            "last_seen_at": "2026-09-01T05:00:00+00:00", "snapshots": [{
                "collected_at": "2026-09-01T05:00:00+00:00", "search_volume_max": 25000,
                "search_volume_text": "2万-2.5万", "growth_rate": 5.5, "has_source": 1,
                "benefits": "[]", "source_page": 2,
            }],
        }])[0]
        self.assertEqual(ranked["source_page"], 2)
        self.assertIn("clueChannel=all_product", ranked["products_url"])
        self.assertIn("%B8%DF%D6%D0%C9%FA", ranked["alibaba_url"])


class RankingTests(unittest.TestCase):
    def test_growth_and_risk(self):
        products = [{
            "id": 1, "title": "生发防脱洗发水", "url": "x", "first_keyword": "洗发水",
            "snapshots": [
                {"sales_count": 100, "collected_at": "2026-08-29T00:00:00+00:00", "keyword":"洗发水", "price_min":10, "price_max":None, "raw_sales_text":"成交100"},
                {"sales_count": 130, "collected_at": "2026-08-30T00:00:00+00:00", "keyword":"洗发水", "price_min":10, "price_max":None, "raw_sales_text":"成交130"},
            ],
        }]
        item = rank_products(products)[0]
        self.assertEqual(item["sales_delta"], 30)
        self.assertEqual(item["daily_velocity"], 30)
        self.assertTrue(risk_flags(item["title"]))

    def test_ignores_different_sales_scope_and_short_interval(self):
        products = [{
            "id": 2, "title": "祛痘凝胶", "url": "x", "first_keyword": "祛痘凝胶",
            "snapshots": [
                {"sales_count": 30, "collected_at": "2026-08-30T08:00:00+00:00", "keyword":"祛痘凝胶", "price_min":10, "price_max":None, "raw_sales_text":"30+件"},
                {"sales_count": 47000, "collected_at": "2026-08-31T08:00:00+00:00", "keyword":"祛痘凝胶", "price_min":10, "price_max":None, "raw_sales_text":"全网4.7万+件"},
            ],
        }]
        item = rank_products(products)[0]
        self.assertIsNone(item["sales_delta"])
        self.assertIsNone(item["growth_rate"])
        self.assertEqual(item["confidence"], "baseline")

        products[0]["snapshots"][1]["raw_sales_text"] = "47000+件"
        products[0]["snapshots"][1]["collected_at"] = "2026-08-30T14:00:00+00:00"
        item = rank_products(products)[0]
        self.assertIsNone(item["sales_delta"])

    def test_filters_by_category_keywords(self):
        products = [
            {
                "id": 3, "title": "植物染发膏", "url": "x", "first_keyword": "染发膏",
                "snapshots": [{"sales_count": 10, "collected_at": "2026-08-31T08:00:00+00:00", "keyword": "染发膏", "price_min": 10, "price_max": None, "raw_sales_text": "成交10"}],
            },
            {
                "id": 4, "title": "祛痘凝胶", "url": "y", "first_keyword": "祛痘凝胶",
                "snapshots": [{"sales_count": 20, "collected_at": "2026-08-31T08:00:00+00:00", "keyword": "祛痘凝胶", "price_min": 12, "price_max": None, "raw_sales_text": "成交20"}],
            },
        ]
        ranked = rank_products(products, allowed_keywords={"染发膏", "植物染发剂"})
        self.assertEqual([item["id"] for item in ranked], [3])


if __name__ == "__main__":
    unittest.main()
