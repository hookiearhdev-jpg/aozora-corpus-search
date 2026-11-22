"""FastAPI バックエンド (/api/health, /api/stats, /api/search, CORS) の統合テスト。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app


def test_api_endpoints() -> None:
    client = TestClient(app)

    # 1. Health check
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    health_data = r_health.json()
    assert health_data["status"] == "ok"
    print(f"[OK] GET /api/health: {health_data}")

    # 2. CORS preflight check (Next.js origin)
    r_cors = client.options(
        "/api/search",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r_cors.status_code == 200
    assert r_cors.headers.get("access-control-allow-origin") == "http://localhost:3000"
    print("[OK] CORS preflight (http://localhost:3000) allowed")

    # 3. Stats endpoint
    r_stats = client.get("/api/stats")
    assert r_stats.status_code == 200
    stats = r_stats.json()
    assert stats["book_count"] > 0 and stats["token_count"] > 0
    print(
        f"[OK] GET /api/stats: {stats['book_count']:,} 作品 / "
        f"{stats['sentence_count']:,} 文 / {stats['token_count']:,} トークン"
    )

    # 4. Single-key search
    r_single = client.post(
        "/api/search",
        json={
            "key": {"lemma": "走る", "pos": "動詞"},
            "limit": 20,
            "context_chars": 25,
        },
    )
    assert r_single.status_code == 200, r_single.text
    d_single = r_single.json()
    assert d_single["total_count"] > 0 and len(d_single["items"]) == 20
    for item in d_single["items"]:
        assert item["left_context_full"] + item["key_text"] + item["right_context_full"] == item["text"]
        assert item["key_text"] == item["surface"]
        assert item["card_url"].startswith("https://www.aozora.gr.jp/")
    print(
        f"[OK] POST /api/search (単一キー: 動詞・走る): "
        f"total={d_single['total_count']:,}, elapsed={d_single['elapsed_ms']} ms"
    )

    # 5. Collocation search (2語前=助詞 + 動詞・走る)
    r_colloc = client.post(
        "/api/search",
        json={
            "key": {"lemma": "走る", "pos": "動詞"},
            "collocations": [
                {
                    "direction": "before",
                    "distance": 2,
                    "distance_mode": "exact",
                    "condition": {"pos": "助詞"},
                }
            ],
            "limit": 20,
            "context_chars": 25,
        },
    )
    assert r_colloc.status_code == 200, r_colloc.text
    d_colloc = r_colloc.json()
    assert d_colloc["total_count"] > 0 and len(d_colloc["items"]) == 20
    for item in d_colloc["items"]:
        assert item["left_context_full"] + item["key_text"] + item["right_context_full"] == item["text"]
    print(
        f"[OK] POST /api/search (共起: 2語前=助詞 + 動詞・走る): "
        f"total={d_colloc['total_count']:,}, elapsed={d_colloc['elapsed_ms']} ms"
    )

    # 6. Validation: empty key returns 400
    r_empty = client.post("/api/search", json={"key": {}})
    assert r_empty.status_code == 400
    print("[OK] POST /api/search (空キー -> 400 Bad Request)")

    # 7. Works catalog endpoint (all + pagination + search filter)
    r_works = client.get("/api/works", params={"limit": 100, "offset": 0})
    assert r_works.status_code == 200, r_works.text
    d_works = r_works.json()
    assert d_works["total_count"] == stats["book_count"]
    assert d_works["returned_count"] == 100
    assert d_works["items"][0]["card_url"].startswith("https://www.aozora.gr.jp/")

    r_works_p2 = client.get("/api/works", params={"limit": 100, "offset": 100})
    assert r_works_p2.status_code == 200
    assert r_works_p2.json()["items"][0]["book_id"] != d_works["items"][0]["book_id"]

    r_works_q = client.get("/api/works", params={"q": "夏目漱石", "limit": 50})
    assert r_works_q.status_code == 200
    d_works_q = r_works_q.json()
    assert d_works_q["total_count"] > 0
    assert all(
        "夏目漱石" in item["author"] or "夏目漱石" in item["title"]
        for item in d_works_q["items"]
    )
    print(
        f"[OK] GET /api/works: 全 {d_works['total_count']:,} 作品 / "
        f"ページネーションOK / 検索(q='夏目漱石'): {d_works_q['total_count']} 件"
    )


if __name__ == "__main__":
    test_api_endpoints()
    print("\nALL FASTAPI TESTS PASSED SUCCESSFULLY!")
