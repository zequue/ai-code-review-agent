from reviewer.redact import PLACEHOLDER, redact


def test_redacts_known_token_formats():
    text = 'GH = "ghp_' + "a" * 36 + '"\nkey = "AKIA' + "B" * 16 + '"'
    clean, count = redact(text)
    assert "ghp_" not in clean and "AKIA" not in clean
    assert count >= 2


def test_redacts_sensitive_assignments_but_keeps_the_name():
    clean, count = redact('DB_PASSWORD = "s3cr3t-value"\napi_key: "abcdef123456"')
    assert 'DB_PASSWORD = "[REDACTED]"' in clean
    assert f'api_key: "{PLACEHOLDER}"' in clean
    assert count == 2


def test_redacts_credentials_in_urls():
    clean, _ = redact("DATABASE_URL = postgres://admin:hunter22@db.internal:5432/shop")
    assert "hunter22" not in clean


def test_leaves_normal_code_untouched():
    code = (
        'app.config["ADMIN_TOKEN"] = os.environ.get("ADMIN_TOKEN", "")\n'
        'provided = request.headers.get("X-Admin-Token", "")\n'
        "total = subtotal - discount\n"
    )
    assert redact(code) == (code, 0)
