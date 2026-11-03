import os
os.environ["DATABASE_URL"] = "sqlite:///./test_booking.db"
from fastapi.testclient import TestClient
import pytest
from app.core.database import Base, engine
from app.main import app

@pytest.fixture(autouse=True)
def schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
