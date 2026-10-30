from app.db.session import with_psycopg2_driver


def test_bare_postgres_urls_name_the_psycopg2_driver():
    # SQLAlchemy 2.1 maps a bare postgresql:// URL to psycopg 3, which the image doesn't install (#49).
    assert with_psycopg2_driver("postgresql://u:p@postgres:5432/db") == "postgresql+psycopg2://u:p@postgres:5432/db"
    assert with_psycopg2_driver("postgres://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"


def test_explicit_drivers_and_other_databases_are_left_alone():
    for url in (
        "postgresql+psycopg2://u:p@h/db",
        "postgresql+psycopg://u:p@h/db",
        "sqlite:///./test.db",
        "sqlite://",
    ):
        assert with_psycopg2_driver(url) == url
