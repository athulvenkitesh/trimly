from datetime import date, timedelta

from fastapi.testclient import TestClient


def register(client: TestClient, email: str, role: str) -> dict:
    return client.post("/api/v1/auth/register",
                       json={"email": email, "password": "password123", "role": role}).json()


def bookable_shop(client: TestClient, owner_headers: dict) -> tuple[dict, dict]:
    shop = client.post("/api/v1/shops", headers=owner_headers,
                       json={"name": "Review Cuts", "latitude": 12.97, "longitude": 77.6}).json()
    service = client.post(f"/api/v1/shops/{shop['id']}/services", headers=owner_headers,
                          json={"name": "Cut", "duration_minutes": 30, "price_paise": 10000}).json()
    for weekday in range(7):
        client.put(f"/api/v1/barber/shops/{shop['id']}/business-hours", headers=owner_headers,
                   json={"weekday": weekday, "opens_at": "09:00", "closes_at": "18:00", "is_closed": False})
    return shop, service


def customer_book(client: TestClient, shop: dict, service: dict, email: str) -> dict:
    cust = register(client, email, "CUSTOMER")
    headers = {"Authorization": f"Bearer {cust['access_token']}"}
    day = (date.today() + timedelta(days=2)).isoformat()
    slot = client.get(f"/api/v1/shops/{shop['id']}/availability?service_id={service['id']}&date={day}").json()["slots"][0]
    client.post("/api/v1/bookings", headers=headers,
                json={"shop_id": shop["id"], "service_id": service["id"], "starts_at": slot})
    return headers


def test_review_requires_a_booking(client):
    owner = register(client, "revowner@example.com", "SHOP_OWNER")
    shop, _ = bookable_shop(client, {"Authorization": f"Bearer {owner['access_token']}"})
    stranger = register(client, "stranger@example.com", "CUSTOMER")
    response = client.post(f"/api/v1/shops/{shop['id']}/reviews",
                           headers={"Authorization": f"Bearer {stranger['access_token']}"},
                           json={"rating": 5, "comment": "great"})
    assert response.status_code == 403


def test_review_flow_and_rating_summary(client):
    owner = register(client, "revowner2@example.com", "SHOP_OWNER")
    shop, service = bookable_shop(client, {"Authorization": f"Bearer {owner['access_token']}"})
    headers = customer_book(client, shop, service, "reviewer@example.com")

    created = client.post(f"/api/v1/shops/{shop['id']}/reviews", headers=headers,
                          json={"rating": 4, "comment": "Sharp fade, friendly folks"})
    assert created.status_code == 201
    body = created.json()
    assert body["rating"] == 4
    assert body["customer_name"] == "reviewer"  # email local part only

    # One review per shop per customer.
    duplicate = client.post(f"/api/v1/shops/{shop['id']}/reviews", headers=headers, json={"rating": 1})
    assert duplicate.status_code == 409

    listing = client.get(f"/api/v1/shops/{shop['id']}/reviews").json()
    assert listing["rating_count"] == 1
    assert listing["rating_avg"] == 4.0
    assert listing["reviews"][0]["comment"] == "Sharp fade, friendly folks"


def test_rating_bounds_and_missing_shop(client):
    owner = register(client, "revowner3@example.com", "SHOP_OWNER")
    shop, service = bookable_shop(client, {"Authorization": f"Bearer {owner['access_token']}"})
    headers = customer_book(client, shop, service, "bounds@example.com")
    for rating in (0, 6):
        response = client.post(f"/api/v1/shops/{shop['id']}/reviews", headers=headers, json={"rating": rating})
        assert response.status_code == 422
    assert client.get("/api/v1/shops/99999/reviews").status_code == 404
    assert client.post("/api/v1/shops/99999/reviews", headers=headers, json={"rating": 3}).status_code == 404


def test_discovery_includes_rating_aggregates(client):
    owner = register(client, "revowner4@example.com", "SHOP_OWNER")
    shop, service = bookable_shop(client, {"Authorization": f"Bearer {owner['access_token']}"})
    for email, rating in (("r1@example.com", 5), ("r2@example.com", 3)):
        headers = customer_book(client, shop, service, email)
        client.post(f"/api/v1/shops/{shop['id']}/reviews", headers=headers, json={"rating": rating})

    found = client.get("/api/v1/discover/search", params={"q": "Review"}).json()
    match = next((item for item in found if item["id"] == shop["id"]), None)
    assert match is not None
    assert match["rating_avg"] == 4.0
    assert match["rating_count"] == 2

    nearby = client.get("/api/v1/discover/nearby", params={"latitude": 12.97, "longitude": 77.6}).json()
    match = next((item for item in nearby if item["id"] == shop["id"]), None)
    assert match["rating_avg"] == 4.0
    assert match["rating_count"] == 2
