owner_payload = {"email": "owner@example.com", "password": "password123", "role": "SHOP_OWNER"}

def register_owner(client):
    tokens = client.post("/api/v1/auth/register", json=owner_payload).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}

def create_shop(client, headers, name = "Cut Here"):
    return client.post("/api/v1/shops", headers=headers, json={"name": name, "address": "12 Market Street"})

def test_maps_config_removed(client):
    # The keyless Leaflet/OpenStreetMap picker needs no server-side key endpoint.
    assert client.get("/api/v1/barber/maps-config").status_code in (401, 404)

def test_set_and_clear_shop_location(client):
    headers = register_owner(client)
    shop = create_shop(client, headers).json()
    assert shop["latitude"] is None and shop["longitude"] is None and shop["place_id"] is None

    saved = client.put(f"/api/v1/barber/shops/{shop['id']}/location", headers=headers, json={
        "latitude": 12.9716, "longitude": 77.5946, "place_id": "ChIJabc123", "postal_code": "560001", "address": "12 Market Street, Bengaluru"})
    assert saved.status_code == 200
    body = saved.json()
    assert body["latitude"] == 12.9716 and body["longitude"] == 77.5946
    assert body["place_id"] == "ChIJabc123" and body["address"] == "12 Market Street, Bengaluru"
    assert body["postal_code"] == "560001"

    # Location is visible on the public shop detail.
    public = client.get(f"/api/v1/shops/{shop['id']}")
    assert public.status_code == 200
    assert public.json()["latitude"] == 12.9716
    assert public.json()["postal_code"] == "560001"

    # Sending no coordinates clears the pin (this is the "Clear pin" flow);
    # it must keep the editable address and pincode.
    partial = client.put(f"/api/v1/barber/shops/{shop['id']}/location", headers=headers, json={"address": "New Address Town"})
    assert partial.status_code == 200
    body = partial.json()
    assert body["latitude"] is None and body["longitude"] is None and body["place_id"] is None
    assert body["address"] == "New Address Town"
    assert body["postal_code"] == "560001"

def test_location_validation_rejects_bad_coordinates(client):
    headers = register_owner(client)
    shop = create_shop(client, headers).json()
    url = f"/api/v1/barber/shops/{shop['id']}/location"

    out_of_range = client.put(url, headers=headers, json={"latitude": 120, "longitude": 0})
    assert out_of_range.status_code == 422
    half_pair = client.put(url, headers=headers, json={"latitude": 12.9})
    assert half_pair.status_code == 422
    bad_pincode = client.put(url, headers=headers, json={"postal_code": "!!!"})
    assert bad_pincode.status_code == 422

def test_location_requires_ownership(client):
    owner_headers = register_owner(client)
    shop = create_shop(client, owner_headers).json()

    other_tokens = client.post("/api/v1/auth/register", json={"email": "other@example.com", "password": "password123", "role": "SHOP_OWNER"}).json()
    other_headers = {"Authorization": f"Bearer {other_tokens['access_token']}"}
    assert client.put(f"/api/v1/barber/shops/{shop['id']}/location", headers=other_headers, json={"latitude": 1, "longitude": 1}).status_code == 403
