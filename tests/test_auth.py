def test_registration_and_login(client):
    registration = client.post("/api/v1/auth/register", json={"email": "customer@example.com", "password": "password123"})
    assert registration.status_code == 201
    assert registration.json()["access_token"]
    login = client.post("/api/v1/auth/login", json={"email": "customer@example.com", "password": "password123"})
    assert login.status_code == 200
