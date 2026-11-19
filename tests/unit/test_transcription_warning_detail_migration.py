"""Existing databases must gain transcription_warning_detail through a migration."""
import importlib

migration = importlib.import_module("migrations.V20261119_1__add_transcription_warning_detail")


class _Cursor:
    def __init__(self, existing_columns):
        self.existing_columns = set(existing_columns)
        self.calls = []
        self._last = None

    def execute(self, sql, params=None):
        self.calls.append(sql)
        if sql.startswith("SHOW TABLES"):
            self._last = object()
        elif sql.startswith("SHOW COLUMNS"):
            self._last = object() if params[0] in self.existing_columns else None
        else:
            self._last = None

    def fetchone(self):
        return self._last

    def close(self):
        pass


class _Db:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


def _alters(cursor):
    return [sql for sql in cursor.calls if sql.startswith("ALTER TABLE")]


def test_adds_detail_column_to_a_database_that_only_has_the_flag():
    cursor = _Cursor({"has_transcription_warning"})
    db = _Db(cursor)

    migration.upgrade(db)

    alters = _alters(cursor)
    assert len(alters) == 1
    assert "ADD COLUMN transcription_warning_detail JSON" in alters[0]
    assert db.committed


def test_is_a_no_op_when_both_columns_exist():
    cursor = _Cursor({"has_transcription_warning", "transcription_warning_detail"})

    migration.upgrade(_Db(cursor))

    assert _alters(cursor) == []
