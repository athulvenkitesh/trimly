from datetime import date, timedelta

from fastapi.testclient import TestClient


def register(client: TestClient, email: str, role: str) -> dict:
    return client.post("/api/v1/auth/register",
                       json={"email": email, "password": "password123", "role": role}).json()


def headers_for(account: dict) -> dict:
    return {"Authorization": f"Bearer {account['access_token']}"}


def shop_with_menu(client: TestClient, owner_headers: dict, name: str = "Marutharoad",
                   latitude: float = 12.9716, longitude: float = 77.5946) -> tuple[dict, dict]:
    shop = client.post("/api/v1/shops", headers=owner_headers,
                       json={"name": name, "address": "12 Market Street", "postal_code": "560001",
                             "latitude": latitude, "longitude": longitude}).json()
    service = client.post(f"/api/v1/shops/{shop['id']}/services", headers=owner_headers,
                          json={"name": "Haircut", "duration_minutes": 30, "price_paise": 14000}).json()
    for weekday in range(7):
        client.put(f"/api/v1/barber/shops/{shop['id']}/business-hours", headers=owner_headers,
                   json={"weekday": weekday, "opens_at": "09:00", "closes_at": "18:00", "is_closed": False})
    return shop, service


def ask(client: TestClient, message: str, token: str | None = None, **extra) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = client.post("/api/v1/chat/customer", headers=headers,
                           json={"message": message, **extra})
    assert response.status_code == 200, response.text
    return response.json()


# ── Customer assistant ─────────────────────────────────────────────────────

def test_shops_are_ranked_by_distance_with_prices(client):
    owner = register(client, "near@example.com", "SHOP_OWNER")
    shop_with_menu(client, headers_for(owner), name="Marutharoad", latitude=12.9716, longitude=77.5946)
    shop_with_menu(client, headers_for(owner), name="Far Cuts", latitude=13.3, longitude=77.9)

    reply = ask(client, "haircut near me", latitude=12.9716, longitude=77.5946)

    assert reply["intent"] == "nearby"
    assert [card["title"] for card in reply["cards"]][0] == "Marutharoad"
    assert "₹140" in reply["answer"]
    assert any(source["kind"] == "shop" for source in reply["sources"])


def test_service_prices_come_from_the_menu(client):
    owner = register(client, "prices@example.com", "SHOP_OWNER")
    shop_with_menu(client, headers_for(owner))

    reply = ask(client, "how much is a haircut at Marutharoad?")

    assert reply["intent"] == "services"
    assert "Haircut — ₹140 · 30 min" in reply["answer"]
    assert "Convenience fee ₹0" in reply["answer"]


def test_customer_chat_books_the_requested_slot(client):
    owner = register(client, "bookowner@example.com", "SHOP_OWNER")
    shop, service = shop_with_menu(client, headers_for(owner))
    customer = register(client, "chatcust@example.com", "CUSTOMER")

    reply = ask(client, "book a haircut at Marutharoad tomorrow at 11am", token=customer["access_token"])

    assert reply["intent"] == "book"
    assert reply["booking"]["code"]
    assert reply["booking"]["starts_at"].endswith("11:00:00+00:00")
    booked = client.get("/api/v1/customer/bookings", headers=headers_for(customer)).json()
    assert [item["code"] for item in booked] == [reply["booking"]["code"]]
    assert booked[0]["shop_id"] == shop["id"] and booked[0]["service_id"] == service["id"]


def test_single_shop_is_used_when_no_shop_is_named(client):
    owner = register(client, "nobook@example.com", "SHOP_OWNER")
    shop_with_menu(client, headers_for(owner))
    customer = register(client, "windowshop@example.com", "CUSTOMER")

    reply = ask(client, "book a haircut tomorrow at 11am", token=customer["access_token"])

    assert reply["booking"] is not None
    assert len(client.get("/api/v1/customer/bookings", headers=headers_for(customer)).json()) == 1


def test_ambiguous_shop_question_never_books_blindly(client):
    owner = register(client, "two@example.com", "SHOP_OWNER")
    shop_with_menu(client, headers_for(owner), name="Marutharoad")
    shop_with_menu(client, headers_for(owner), name="Far Cuts")
    customer = register(client, "unsure@example.com", "CUSTOMER")

    reply = ask(client, "book a haircut tomorrow at 11am", token=customer["access_token"])

    assert reply["booking"] is None
    assert [card["kind"] for card in reply["cards"]] == ["shop", "shop"]
    assert client.get("/api/v1/customer/bookings", headers=headers_for(customer)).json() == []


def test_booking_requires_a_signed_in_customer(client):
    owner = register(client, "anon@example.com", "SHOP_OWNER")
    shop_with_menu(client, headers_for(owner))

    reply = ask(client, "book a haircut at Marutharoad tomorrow at 11am")

    assert reply["booking"] is None
    assert "sign in" in reply["answer"].lower()


def test_unknown_question_is_grounded_in_retrieved_rows(client):
    owner = register(client, "rag@example.com", "SHOP_OWNER")
    shop_with_menu(client, headers_for(owner))

    reply = ask(client, "beard trim pincode 560001")

    assert reply["answer"]
    assert reply["sources"], "every answer must be backed by retrieved rows"
    assert all(source["doc_id"].split(":")[0] in {"shop", "service", "hours", "review"}
               for source in reply["sources"])


def test_cheapest_question_ranks_menu_prices(client):
    owner = register(client, "compare@example.com", "SHOP_OWNER")
    shop_with_menu(client, headers_for(owner), name="Marutharoad")
    second = client.post("/api/v1/shops", headers=headers_for(owner),
                         json={"name": "Pricey Cuts", "latitude": 12.98, "longitude": 77.60}).json()
    client.post(f"/api/v1/shops/{second['id']}/services", headers=headers_for(owner),
                json={"name": "Haircut Deluxe", "duration_minutes": 45, "price_paise": 32000})

    reply = ask(client, "cheapest haircut around here", latitude=12.9716, longitude=77.5946)

    assert reply["intent"] == "compare_prices"
    assert [card["title"] for card in reply["cards"]][0] == "Haircut — ₹140"
    assert "Marutharoad is the cheapest at ₹140" in reply["answer"]
    assert any(source["doc_id"].startswith("service:") for source in reply["sources"])


# ── Owner assistant ────────────────────────────────────────────────────────

def test_owner_asks_about_todays_bookings_and_revenue(client):
    owner = register(client, "stats@example.com", "SHOP_OWNER")
    shop, service = shop_with_menu(client, headers_for(owner))
    customer = register(client, "statscust@example.com", "CUSTOMER")
    day = (date.today() + timedelta(days=2)).isoformat()
    slot = client.get(f"/api/v1/shops/{shop['id']}/availability?service_id={service['id']}&date={day}").json()["slots"][0]
    client.post("/api/v1/bookings", headers=headers_for(customer),
                json={"shop_id": shop["id"], "service_id": service["id"], "starts_at": slot})

    today = client.post("/api/v1/chat/owner", headers=headers_for(owner),
                        json={"message": "how many bookings today?"}).json()
    assert today["intent"] == "today_bookings"
    assert "No bookings yet for today" in today["answer"]

    week = client.post("/api/v1/chat/owner", headers=headers_for(owner),
                       json={"message": "how many bookings this week?"}).json()
    assert "1 confirmed booking" in week["answer"]
    assert "₹140" in week["answer"]

    revenue = client.post("/api/v1/chat/owner", headers=headers_for(owner),
                          json={"message": "what's today's revenue?"}).json()
    assert "₹0" in revenue["answer"]

    next_up = client.post("/api/v1/chat/owner", headers=headers_for(owner),
                          json={"message": "who is next?"}).json()
    assert next_up["intent"] == "next_appointment"
    assert "Haircut" in next_up["answer"]

    popular = client.post("/api/v1/chat/owner", headers=headers_for(owner),
                          json={"message": "which service is most popular?"}).json()
    assert popular["intent"] == "top_services"
    assert "Haircut — 1 booking" in popular["answer"]


def test_owner_chat_counts_a_walk_in_and_reports_hours(client):
    owner = register(client, "walk@example.com", "SHOP_OWNER")
    shop, _service = shop_with_menu(client, headers_for(owner))
    client.post(f"/api/v1/barber/shops/{shop['id']}/walk-in", headers=headers_for(owner), json={})

    walk_ins = client.post("/api/v1/chat/owner", headers=headers_for(owner),
                           json={"message": "any walk-ins?"}).json()
    assert walk_ins["intent"] == "walk_ins"
    assert "1 walk-in in the last 30 days" in walk_ins["answer"]

    hours = client.post("/api/v1/chat/owner", headers=headers_for(owner),
                        json={"message": "am i open on sunday?"}).json()
    assert hours["intent"] == "hours"
    assert "09:00–18:00" in hours["answer"]


def test_named_day_overrides_the_default_report_window(client):
    """"how many bookings do I have today?" must not answer with this week's total."""
    owner = register(client, "window@example.com", "SHOP_OWNER")
    shop_with_menu(client, headers_for(owner))

    today = client.post("/api/v1/chat/owner", headers=headers_for(owner),
                        json={"message": "how many bookings do I have today?"}).json()
    assert "This week" not in today["answer"]
    assert "today" in today["answer"].lower()

    week = client.post("/api/v1/chat/owner", headers=headers_for(owner),
                       json={"message": "how many bookings do I have this week?"}).json()
    assert "this week (" in week["answer"].lower()

    month = client.post("/api/v1/chat/owner", headers=headers_for(owner),
                        json={"message": "how many bookings did I have this month?"}).json()
    assert "this month (" in month["answer"].lower()


def test_owner_chat_is_not_reachable_by_customers(client):
    customer = register(client, "nope@example.com", "CUSTOMER")
    response = client.post("/api/v1/chat/owner", headers=headers_for(customer),
                           json={"message": "today's revenue"})
    assert response.status_code == 403


def test_owner_chat_needs_an_authenticated_session(client):
    response = client.post("/api/v1/chat/owner", json={"message": "today's revenue"})
    assert response.status_code in (401, 403)
