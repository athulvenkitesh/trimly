from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def register(client: TestClient, email: str, role: str) -> dict:
    return client.post("/api/v1/auth/register",
                       json={"email": email, "password": "password123", "role": role}).json()


def owner_with_shop(client: TestClient, name: str) -> tuple[dict, dict, dict]:
    owner = register(client, f"{name.lower().replace(' ', '')}@example.com", "SHOP_OWNER")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    shop = client.post("/api/v1/shops", headers=headers, json={"name": name}).json()
    service = client.post(f"/api/v1/shops/{shop['id']}/services", headers=headers,
                          json={"name": "Cut", "duration_minutes": 30, "price_paise": 20000}).json()
    for weekday in range(7):
        client.put(f"/api/v1/barber/shops/{shop['id']}/business-hours", headers=headers,
                   json={"weekday": weekday, "opens_at": "00:00", "closes_at": "23:59", "is_closed": False})
    return shop, service, headers


def parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def test_next_slot_is_counted_from_the_current_time(client):
    shop, service, headers = owner_with_shop(client, "Next Slot Cuts")
    body = client.get(f"/api/v1/barber/shops/{shop['id']}/next-slot", headers=headers).json()
    assert body["is_open"] is True
    assert body["service_id"] == service["id"]
    assert body["service_name"] == "Cut"
    starts = parse(body["starts_at"])
    now = datetime.now(timezone.utc)
    # Rounded up to the next 5 minutes, so it can never be in the past.
    assert now - timedelta(minutes=1) <= starts <= now + timedelta(minutes=6)
    assert starts.minute % 5 == 0


def test_buffer_pushes_the_next_slot_later(client):
    shop, _, headers = owner_with_shop(client, "Buffer Cuts")
    after = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    body = client.get(f"/api/v1/barber/shops/{shop['id']}/next-slot",
                      headers=headers, params={"after": after}).json()
    assert parse(body["starts_at"]) >= datetime.now(timezone.utc) + timedelta(minutes=14)


def test_hand_picked_time_in_the_past_falls_back_to_now(client):
    shop, _, headers = owner_with_shop(client, "Edited Slot Cuts")
    past = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    body = client.get(f"/api/v1/barber/shops/{shop['id']}/next-slot",
                      headers=headers, params={"after": past}).json()
    starts = parse(body["starts_at"])
    now = datetime.now(timezone.utc)
    assert now - timedelta(minutes=1) <= starts <= now + timedelta(minutes=6)


def test_walk_in_occupies_the_slot_and_moves_it_forward(client):
    shop, _, headers = owner_with_shop(client, "Walk In Cuts")
    first = client.get(f"/api/v1/barber/shops/{shop['id']}/next-slot", headers=headers).json()
    seated = client.post(f"/api/v1/barber/shops/{shop['id']}/walk-in", headers=headers,
                         json={"starts_at": first["starts_at"]})
    assert seated.status_code == 201
    body = seated.json()
    assert body["is_walk_in"] is True
    assert body["customer_id"] is None and body["walk_in_name"] == "Walk-in customer"

    moved = client.get(f"/api/v1/barber/shops/{shop['id']}/next-slot", headers=headers).json()
    assert parse(moved["starts_at"]) >= parse(first["starts_at"]) + timedelta(minutes=30)

    again = client.post(f"/api/v1/barber/shops/{shop['id']}/walk-in", headers=headers,
                        json={"starts_at": first["starts_at"]})
    assert again.status_code == 409
    assert again.json()["detail"]["error"]["code"] == "SLOT_NOT_AVAILABLE"


def test_walk_in_without_a_slot_seats_the_next_free_time(client):
    shop, _, headers = owner_with_shop(client, "Auto Seat Cuts")
    first = parse(client.get(f"/api/v1/barber/shops/{shop['id']}/next-slot", headers=headers).json()["starts_at"])
    seated = client.post(f"/api/v1/barber/shops/{shop['id']}/walk-in", headers=headers, json={}).json()
    assert parse(seated["starts_at"]) == first


def test_walk_in_is_refused_while_the_shop_is_closed(client):
    shop, _, headers = owner_with_shop(client, "Closed Shop Cuts")
    closed = client.put(f"/api/v1/barber/shops/{shop['id']}/status", headers=headers, json={"is_open": False})
    assert closed.status_code == 200 and closed.json()["is_open"] is False
    assert client.post(f"/api/v1/barber/shops/{shop['id']}/walk-in", headers=headers, json={}).status_code == 409
    slot = client.get(f"/api/v1/barber/shops/{shop['id']}/next-slot", headers=headers).json()
    assert slot["is_open"] is False and slot["starts_at"] is None


def test_shop_without_hours_says_so_instead_of_no_slots(client):
    """An empty shop with hours unconfigured must not read like everything is booked."""
    owner = register(client, "nohourslot@example.com", "SHOP_OWNER")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    shop = client.post("/api/v1/shops", headers=headers, json={"name": "No Hours Cuts"}).json()
    client.post(f"/api/v1/shops/{shop['id']}/services", headers=headers,
                json={"name": "Cut", "duration_minutes": 30, "price_paise": 20000})

    body = client.get(f"/api/v1/barber/shops/{shop['id']}/next-slot", headers=headers).json()
    assert body["is_open"] is True and body["starts_at"] is None
    assert body["reason"] == "no_hours"

    refused = client.post(f"/api/v1/barber/shops/{shop['id']}/walk-in", headers=headers, json={})
    assert refused.status_code == 409
    assert "business hours" in refused.json()["detail"]

    for weekday in range(7):
        client.put(f"/api/v1/barber/shops/{shop['id']}/business-hours", headers=headers,
                   json={"weekday": weekday, "opens_at": "00:00", "closes_at": "23:59", "is_closed": False})
    body = client.get(f"/api/v1/barber/shops/{shop['id']}/next-slot", headers=headers).json()
    assert body["starts_at"] is not None and body["reason"] is None
