from reviewer.diff import parse_diff

SAMPLE = """\
diff --git a/shop/db.py b/shop/db.py
index 1111111..2222222 100644
--- a/shop/db.py
+++ b/shop/db.py
@@ -10,4 +10,6 @@ def connect(path):
     conn = sqlite3.connect(path)
-    return conn
+    conn.row_factory = sqlite3.Row
+    return conn

+
diff --git a/shop/tests/test_new.py b/shop/tests/test_new.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/shop/tests/test_new.py
@@ -0,0 +1,2 @@
+def test_ok():
+    assert True
"""


def test_parses_files_and_flags():
    files = parse_diff(SAMPLE)
    assert [f.path for f in files] == ["shop/db.py", "shop/tests/test_new.py"]
    assert not files[0].is_new and files[1].is_new
    assert files[1].is_test and not files[0].is_test


def test_maps_added_lines_to_new_file_numbers():
    db = parse_diff(SAMPLE)[0]
    # línea 10 es contexto, la 11 vieja se borra, 11 y 12 nuevas se agregan, 13 contexto, 14 nueva
    assert db.added_lines == {
        11: "    conn.row_factory = sqlite3.Row",
        12: "    return conn",
        14: "",
    }


def test_new_file_lines_start_at_one():
    test_file = parse_diff(SAMPLE)[1]
    assert test_file.added_lines == {1: "def test_ok():", 2: "    assert True"}


def test_empty_diff():
    assert parse_diff("") == []
