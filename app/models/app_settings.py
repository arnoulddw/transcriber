# app/models/app_settings.py
# Key/value store for instance-wide settings that can change at runtime
# (deployment mode, sign-up toggle, owner account).

import logging
from typing import Dict, Optional

from mysql.connector import Error as MySQLError

from app.database import get_cursor, get_db

logger = logging.getLogger(__name__)

TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS app_settings (
        setting_key VARCHAR(64) PRIMARY KEY,
        setting_value VARCHAR(255) NULL,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def init_db_command() -> None:
    """Create the app_settings table if it does not exist."""
    cursor = get_cursor()
    cursor.execute(TABLE_SQL)
    get_db().commit()


def get_all() -> Dict[str, Optional[str]]:
    """Return every stored setting as a plain dict."""
    cursor = get_cursor()
    cursor.execute("SELECT setting_key, setting_value FROM app_settings")
    return {row['setting_key']: row['setting_value'] for row in cursor.fetchall()}


def set_values(values: Dict[str, Optional[str]], commit: bool = True) -> None:
    """Insert or update several settings at once."""
    if not values:
        return
    cursor = get_cursor()
    try:
        for key, value in values.items():
            cursor.execute(
                """
                INSERT INTO app_settings (setting_key, setting_value)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
                """,
                (key, None if value is None else str(value)),
            )
        if commit:
            get_db().commit()
    except MySQLError:
        get_db().rollback()
        logger.error("[DB:AppSettings] Failed to save settings %s.", list(values), exc_info=True)
        raise
