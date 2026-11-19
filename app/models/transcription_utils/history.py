"""
User history management helpers for transcriptions.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from mysql.connector import Error as MySQLError

from app.database import get_cursor, get_db
from app.models.transcription import _map_row_to_transcription_dict
from .history_filters import HistoryFilters, build_history_filter_clause


def get_all_transcriptions_for_admin(
    user_id: int,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves ALL transcription records for a specific user (including hidden),
    ordered by creation date DESC. Intended for admin views.
    """
    log_prefix = f"[DB:History:AdminView:User:{user_id}]"
    sql = 'SELECT * FROM transcriptions WHERE user_id = %s ORDER BY created_at DESC'
    params: List[Any] = [user_id]

    if limit is not None and limit > 0:
        sql += ' LIMIT %s'
        params.append(limit)
        limit_msg = f" with limit {limit}"
    else:
        limit_msg = ""

    transcriptions: List[Dict[str, Any]] = []
    cursor = get_cursor()
    try:
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        transcriptions = [_map_row_to_transcription_dict(row) for row in rows if row]
        logging.debug(
            "%s Retrieved %s total transcription records (including hidden)%s.",
            log_prefix,
            len(transcriptions),
            limit_msg,
        )
    except MySQLError as err:
        logging.error(
            "%s Error retrieving all transcriptions for admin: %s",
            log_prefix,
            err,
            exc_info=True,
        )
        transcriptions = []
    return transcriptions


def purge_user_history(user_id: int, max_items: int, retention_days: int) -> int:
    """
    Soft-deletes old and excess transcription history items for a specific user.
    Applies retention days first, then max items limit. Only affects visible records.
    Returns the total number of records hidden, or -1 on error.
    """
    if max_items <= 0 and retention_days <= 0:
        logging.debug(
            "[DB:HistoryPurge:User:%s] No history limits set. Skipping purge.",
            user_id,
        )
        return 0

    cursor = get_cursor()
    hidden_count = 0
    log_prefix = f"[DB:HistoryPurge:User:{user_id}]"
    logging.debug(
        "%s Starting history purge (soft delete). Limits - MaxItems: %s, RetentionDays: %s.",
        log_prefix,
        max_items,
        retention_days,
    )

    try:
        if retention_days > 0:
            try:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
                cutoff_iso = cutoff_date.isoformat(timespec='seconds')
                logging.debug(
                    "%s Hiding records older than %s (%s days).",
                    log_prefix,
                    cutoff_iso,
                    retention_days,
                )
                sql_hide_by_date = """
                    UPDATE transcriptions
                    SET is_hidden_from_user = TRUE, hidden_date = NOW(), hidden_reason = 'RETENTION_POLICY'
                    WHERE user_id = %s AND created_at < %s AND is_hidden_from_user = FALSE
                """
                cursor.execute(sql_hide_by_date, (user_id, cutoff_iso))
                hidden_by_date = cursor.rowcount
                if hidden_by_date > 0:
                    hidden_count += hidden_by_date
                    logging.debug(
                        "%s Hid %s records based on retention days.",
                        log_prefix,
                        hidden_by_date,
                    )
                else:
                    logging.debug(
                        "%s No visible records found older than retention period.",
                        log_prefix,
                    )
            except Exception as date_purge_err:
                logging.error(
                    "%s Error during date-based hiding step: %s",
                    log_prefix,
                    date_purge_err,
                    exc_info=True,
                )

        if max_items > 0:
            try:
                cursor.execute(
                    "SELECT COUNT(*) as count FROM transcriptions WHERE user_id = %s AND is_hidden_from_user = FALSE",
                    (user_id,),
                )
                current_count_result = cursor.fetchone()
                cursor.fetchall()
                current_visible_count = (
                    current_count_result['count'] if current_count_result else 0
                )
                logging.debug(
                    "%s Current visible item count after date purge: %s. Max items limit: %s.",
                    log_prefix,
                    current_visible_count,
                    max_items,
                )

                if current_visible_count > max_items:
                    num_to_hide = current_visible_count - max_items
                    logging.debug(
                        "%s Exceeds max items limit. Need to hide oldest %s visible records.",
                        log_prefix,
                        num_to_hide,
                    )
                    sql_hide_by_count = """
                        UPDATE transcriptions
                        SET is_hidden_from_user = TRUE, hidden_date = NOW(), hidden_reason = 'RETENTION_POLICY'
                        WHERE user_id = %s AND is_hidden_from_user = FALSE
                        ORDER BY created_at ASC
                        LIMIT %s
                    """
                    cursor.execute(sql_hide_by_count, (user_id, num_to_hide))
                    hidden_by_count = cursor.rowcount
                    if hidden_by_count > 0:
                        hidden_count += hidden_by_count
                        logging.debug(
                            "%s Hid %s additional records based on max items limit.",
                            log_prefix,
                            hidden_by_count,
                        )
                    if hidden_by_count != num_to_hide:
                        logging.warning(
                            "%s Mismatch hiding by count: Expected %s, Hid %s.",
                            log_prefix,
                            num_to_hide,
                            hidden_by_count,
                        )
                else:
                    logging.debug(
                        "%s Visible item count is within the max items limit.",
                        log_prefix,
                    )
            except Exception as count_purge_err:
                logging.error(
                    "%s Error during count-based hiding step: %s",
                    log_prefix,
                    count_purge_err,
                    exc_info=True,
                )

        get_db().commit()
        if hidden_count > 0:
            logging.debug(
                "%s History purge (soft delete) completed. Total hidden: %s.",
                log_prefix,
                hidden_count,
            )
        else:
            logging.debug(
                "%s History purge (soft delete) completed. No records hidden.",
                log_prefix,
            )

    except MySQLError as err:
        logging.error(
            "%s MySQL error during history purge transaction: %s",
            log_prefix,
            err,
            exc_info=True,
        )
        try:
            get_db().rollback()
        except Exception as rb_err:
            logging.error(
                "%s Error during rollback after purge failure: %s",
                log_prefix,
                rb_err,
            )
        hidden_count = -1

    return hidden_count


def physically_delete_hidden_records(retention_period_days: int) -> int:
    """
    Physically deletes transcription records that have been hidden for longer
    than the specified retention period. Returns the number of records deleted.
    """
    log_prefix = "[DB:PhysicalDelete]"
    if retention_period_days <= 0:
        logging.warning(
            "%s Physical deletion period is zero or negative (%s days). Skipping physical deletion.",
            log_prefix,
            retention_period_days,
        )
        return 0

    cursor = get_cursor()
    deleted_count = 0
    logging.debug(
        "%s Starting physical deletion of records hidden for more than %s days.",
        log_prefix,
        retention_period_days,
    )

    try:
        sql = """
            DELETE FROM transcriptions
            WHERE is_hidden_from_user = TRUE
              AND hidden_date < (NOW() - INTERVAL %s DAY)
        """
        cursor.execute(sql, (retention_period_days,))
        deleted_count = cursor.rowcount
        get_db().commit()
        if deleted_count > 0:
            logging.debug(
                "%s Physically deleted %s hidden records.",
                log_prefix,
                deleted_count,
            )
        else:
            logging.debug(
                "%s No hidden records found older than %s days.",
                log_prefix,
                retention_period_days,
            )

    except MySQLError as err:
        logging.error(
            "%s MySQL error during physical deletion: %s",
            log_prefix,
            err,
            exc_info=True,
        )
        try:
            get_db().rollback()
        except Exception as rb_err:
            logging.error(
                "%s Error during rollback after physical deletion failure: %s",
                log_prefix,
                rb_err,
            )
        deleted_count = -1
    return deleted_count


def count_visible_user_transcriptions(
    user_id: int,
    search_query: Optional[str] = None,
    filters: Optional[HistoryFilters] = None,
) -> int:
    """Counts the visible and finished transcription records for a user,
    optionally narrowed by a search query and history filters."""
    log_prefix = f"[DB:History:User:{user_id}]"
    sql = (
        'SELECT COUNT(*) as count FROM transcriptions t '
        'WHERE t.user_id = %s AND t.is_hidden_from_user = FALSE AND t.status = %s'
    )
    params: list = [user_id, 'finished']
    if search_query and search_query.strip():
        pattern = f"%{search_query.strip()}%"
        sql += (
            ' AND (t.filename LIKE %s OR t.generated_title LIKE %s '
            'OR MATCH(t.filename, t.generated_title, t.transcription_text) AGAINST (%s IN NATURAL LANGUAGE MODE))'
        )
        params.extend([pattern, pattern, search_query.strip()])
    filter_sql, filter_params = build_history_filter_clause(filters, user_id)
    sql += filter_sql
    params.extend(filter_params)
    cursor = get_cursor()
    count = 0
    try:
        cursor.execute(sql, tuple(params))
        result = cursor.fetchone()
        count = result['count'] if result else 0
        logging.debug(
            "%s Counted %s visible finished transcriptions.",
            log_prefix,
            count,
        )
    except MySQLError as err:
        logging.error(
            "%s Error counting visible transcriptions: %s",
            log_prefix,
            err,
            exc_info=True,
        )
        count = 0
    return count


def get_paginated_transcriptions(
    user_id: int,
    page: int,
    per_page: int,
    search_query: Optional[str] = None,
    filters: Optional[HistoryFilters] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves a paginated list of visible and finished transcription records for a user,
    ordered by creation date DESC. Includes the latest associated LLM operation ID.
    Optionally filters by search_query across filename, generated_title, and transcription_text,
    and by the history filters (date, model, language, duration, workflow label).
    """
    log_prefix = f"[DB:History:User:{user_id}:Page:{page}]"
    offset = (page - 1) * per_page

    search_clause = ""
    search_params: tuple = ()
    if search_query and search_query.strip():
        pattern = f"%{search_query.strip()}%"
        search_clause = (
            " AND (t.filename LIKE %s OR t.generated_title LIKE %s "
            "OR MATCH(t.filename, t.generated_title, t.transcription_text) "
            "AGAINST (%s IN NATURAL LANGUAGE MODE))"
        )
        search_params = (pattern, pattern, search_query.strip())

    filter_clause, filter_params = build_history_filter_clause(filters, user_id)

    sql = f"""
        WITH RankedOperations AS (
            SELECT
                lo.id AS llm_operation_id,
                lo.status AS llm_operation_status,
                lo.transcription_id,
                ROW_NUMBER() OVER(PARTITION BY lo.transcription_id ORDER BY lo.completed_at DESC, lo.created_at DESC) as rn
            FROM llm_operations lo
            WHERE lo.user_id = %s
              AND lo.operation_type = 'workflow'
              AND lo.status IN ('finished', 'error')
        )
        SELECT
            t.id, t.user_id, t.filename, t.generated_title, t.title_generation_status,
            t.file_size_mb, t.audio_length_minutes, t.detected_language, t.api_used, t.api_model,
            t.created_at, t.status, t.context_prompt_used, t.has_transcription_warning, t.transcription_warning_detail, t.downloaded,
            t.is_hidden_from_user, t.hidden_date, t.hidden_reason,
            t.pending_workflow_prompt_text,
            t.pending_workflow_prompt_title, t.pending_workflow_prompt_color,
            t.pending_workflow_origin_prompt_id, t.public_api_invocation,
            t.cost, t.is_pinned,
            LEFT(COALESCE(t.transcription_text, ''), 4000) AS transcription_preview,
            (CHAR_LENGTH(COALESCE(t.transcription_text, '')) > 4000) AS transcription_has_more,
            ro.llm_operation_id,
            ro.llm_operation_status
        FROM transcriptions t
        LEFT JOIN RankedOperations ro ON t.id = ro.transcription_id AND ro.rn = 1
        WHERE t.user_id = %s AND t.is_hidden_from_user = FALSE AND t.status = %s{search_clause}{filter_clause}
        ORDER BY t.is_pinned DESC, t.created_at DESC
        LIMIT %s OFFSET %s
    """
    params = (user_id, user_id, 'finished') + search_params + tuple(filter_params) + (per_page, offset)

    transcriptions: List[Dict[str, Any]] = []
    cursor = get_cursor()
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        transcriptions = [_map_row_to_transcription_dict(row) for row in rows if row]
        logging.debug(
            "%s Retrieved %s visible finished transcriptions for page %s (limit=%s, offset=%s).",
            log_prefix,
            len(transcriptions),
            page,
            per_page,
            offset,
        )
    except MySQLError as err:
        logging.error(
            "%s Error retrieving paginated transcriptions: %s",
            log_prefix,
            err,
            exc_info=True,
        )
        transcriptions = []
    return transcriptions


__all__ = [
    "get_all_transcriptions_for_admin",
    "purge_user_history",
    "physically_delete_hidden_records",
    "count_visible_user_transcriptions",
    "get_paginated_transcriptions",
]
