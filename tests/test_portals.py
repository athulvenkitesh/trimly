def test_customer_portal_is_served_at_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_bare_portal_urls_redirect_to_the_trailing_slash(client):
    # Sharing /dashboard is the common case; without the redirect StaticFiles answers 404.
    for path in ("/dashboard", "/admin"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 307, path
        assert response.headers["location"] == f"{path}/"


def test_portal_assets_are_not_cached_by_heuristics(client):
    response = client.get("/dashboard/app.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
