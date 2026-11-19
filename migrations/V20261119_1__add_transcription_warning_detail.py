"""Add the per-chunk detail behind an incomplete-transcript warning.

Fresh databases get ``transcription_warning_detail`` from the baseline
``CREATE TABLE`` in ``app.models.transcription.schema``. Existing databases skip
the model initializers at startup, so they need this ordered migration.
"""

from __future__ import annotations


TABLE = "transcriptions"
FLAG_COLUMN = "has_transcription_warning"
DETAIL_COLUMN = "transcription_warning_detail"


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute("SHOW TABLES LIKE %s", (table_name,))
    return cursor.fetchone() is not None


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE %s", (column_name,))
    return cursor.fetchone() is not None


def upgrade(db) -> None:
    cursor = db.cursor()
    try:
        if not _table_exists(cursor, TABLE):
            return

        if not _column_exists(cursor, TABLE, FLAG_COLUMN):
            cursor.execute(
                f"ALTER TABLE {TABLE} "
                f"ADD COLUMN {FLAG_COLUMN} BOOLEAN NOT NULL DEFAULT FALSE "
                "AFTER error_message"
            )

        if not _column_exists(cursor, TABLE, DETAIL_COLUMN):
            cursor.execute(
                f"ALTER TABLE {TABLE} "
                f"ADD COLUMN {DETAIL_COLUMN} JSON DEFAULT NULL "
                f"AFTER {FLAG_COLUMN}"
            )
        db.commit()
    finally:
        cursor.close()
