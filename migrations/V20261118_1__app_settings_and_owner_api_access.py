"""Add the app_settings table and let the built-in admin role use the public API.

The deployment mode itself is seeded by ``access_service.ensure_access_settings``
during bootstrap: databases that already have users are stored as team mode,
so upgrading never switches an existing team installation to personal mode.
"""

from app.models.app_settings import TABLE_SQL


def upgrade(db):
    cursor = db.cursor()
    cursor.execute(TABLE_SQL)
    cursor.execute("SHOW COLUMNS FROM roles LIKE 'allow_public_api_access'")
    has_column = cursor.fetchone() is not None
    cursor.fetchall()
    if has_column:
        cursor.execute("UPDATE roles SET allow_public_api_access = 1 WHERE name = 'admin'")
    db.commit()
