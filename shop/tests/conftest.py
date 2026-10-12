import pytest

from shop import db
from shop.app import create_app


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "test.db"))
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def client(tmp_path):
    app = create_app(str(tmp_path / "app.db"))
    return app.test_client()
