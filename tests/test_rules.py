from reviewer.rules import check_admin_routes

UNPROTECTED = '''
@app.post("/admin/products")
def admin_add_product():
    return db.add_product(request.json)
'''

DECORATED = '''
@app.post("/admin/products")
@require_admin
def admin_add_product():
    return db.add_product(request.json)
'''

CHECK_IN_BODY = '''
@app.delete("/admin/products/<int:pid>")
def admin_delete(pid):
    check_admin_token(request)
    return db.delete(pid)
'''

PUBLIC = '''
@app.get("/products/search")
def search():
    return db.search(request.args["q"])
'''


def test_flags_admin_route_without_auth():
    [finding] = check_admin_routes(UNPROTECTED, "shop/app.py")
    assert (finding.rule, finding.severity, finding.line) == ("ADMIN-NO-AUTH", "critical", 2)


def test_accepts_auth_decorator_or_explicit_check():
    assert check_admin_routes(DECORATED, "shop/app.py") == []
    assert check_admin_routes(CHECK_IN_BODY, "shop/app.py") == []


def test_ignores_public_routes():
    assert check_admin_routes(PUBLIC, "shop/app.py") == []
