import json
from typing import Any, Dict, Optional

from mysql.connector import Error as MySQLError

from app.database import get_cursor, get_db
from app.logging_config import get_logger


TERMINAL_JOB_STATUSES = {"finished", "error", "cancelled", "interrupted"}


def update_job_progress(job_id: str, message: str) -> None:
    """
    Appends a progress message to the job's progress log (JSON array/TEXT) in the database.
    Uses MySQL's JSON_ARRAY_APPEND if JSON type is used, otherwise reads/modifies/writes TEXT.
    """
    short_job_id = job_id[:8]
    log_prefix = f"[DB:Job:{short_job_id}]"
    cursor = get_cursor()

    is_json_type = False
    try:
        cursor.execute("SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'transcriptions' AND COLUMN_NAME = 'progress_log'")
        result = cursor.fetchone()
        cursor.fetchall()
        if result and result['DATA_TYPE'].lower() == 'json':
            is_json_type = True
    except MySQLError as schema_err:
        get_logger(__name__).warning(f"Could not determine progress_log column type for job {job_id}: {schema_err}. Assuming TEXT fallback.")
        is_json_type = False
    except Exception as e:
         get_logger(__name__).warning(f"Error checking progress_log column type for job {job_id}: {e}. Assuming TEXT fallback.")
         is_json_type = False

    try:
        if is_json_type:
            sql = """
                UPDATE transcriptions
                SET progress_log = JSON_ARRAY_APPEND(
                    COALESCE(progress_log, JSON_ARRAY()),
                    '$',
                    %s
                )
                WHERE id = %s
            """
            cursor.execute(sql, (message, job_id))
        else:
            cursor.execute("SELECT progress_log FROM transcriptions WHERE id = %s", (job_id,))
            row = cursor.fetchone()
            cursor.fetchall()

            if row:
                current_log_json = row['progress_log']
                current_log = []
                try:
                    if current_log_json:
                        parsed_log = json.loads(current_log_json)
                        if isinstance(parsed_log, list):
                            current_log = parsed_log
                        else:
                            get_logger(__name__).warning(f"Progress log TEXT is not a list ({type(parsed_log)}) for job {job_id}. Resetting.")
                except (json.JSONDecodeError, TypeError):
                    get_logger(__name__).warning(f"Could not parse progress log TEXT for job {job_id}. Resetting log. Content: {current_log_json}")
    
                current_log.append(message)
                new_log_json = json.dumps(current_log)
                cursor.execute("UPDATE transcriptions SET progress_log = %s WHERE id = %s", (new_log_json, job_id))
            else:
                 get_logger(__name__).warning(f"Attempted to update progress for non-existent job {job_id} (TEXT fallback).")

        get_db().commit()
        get_logger(__name__, job_id=job_id).debug(f"Appended progress message: '{message}'")

    except MySQLError as err:
        get_logger(__name__, job_id=job_id).error(f"MySQL error updating DB progress log: {err}", exc_info=True)
        try:
            get_db().rollback()
        except Exception as rb_err:
            get_logger(__name__, job_id=job_id).error(f"Error during rollback after progress update failure: {rb_err}")
    finally:
        # The cursor is managed by the application context, so we don't close it here.
        pass


def update_job_status(job_id: str, status: str) -> None:
    """Updates the status field of a specific job record."""
    logger = get_logger(__name__, job_id=job_id, component="DB:Job")
    valid_statuses = ['pending', 'processing', 'finished', 'error', 'cancelling', 'cancelled', 'interrupted']
    if status not in valid_statuses:
        logger.error(f"Attempted to set invalid status: '{status}'")
        return

    if status in TERMINAL_JOB_STATUSES:
        sql = """
            UPDATE transcriptions
            SET status = %s,
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
            WHERE id = %s
        """
    else:
        sql = "UPDATE transcriptions SET status = %s WHERE id = %s"
    cursor = get_cursor()
    try:
        cursor.execute(sql, (status, job_id))
        get_db().commit()
        if cursor.rowcount > 0:
            logger.info(f"Updated status to: {status}")
        else:
            logger.warning("Attempted to update status for non-existent job.")
    except MySQLError as err:
        logger.error(f"Error updating status to '{status}': {err}", exc_info=True)
        get_db().rollback()
    finally:
        # The cursor is managed by the application context, so we don't close it here.
        pass


def set_job_error(job_id: str, error_message: str) -> None:
    """
    Sets the job status to 'error' and records the error message.
    Also attempts to add the error message to the progress log.
    """
    logger = get_logger(__name__, job_id=job_id, component="DB:Job")

    try:
        update_job_progress(job_id, f"ERROR: {error_message}")
    except Exception as prog_err:
        logger.error(f"Failed to add error message to progress log: {prog_err}", exc_info=True)

    sql = """
        UPDATE transcriptions
        SET status = 'error',
            completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
            error_message = %s
        WHERE id = %s
        """
    cursor = get_cursor()
    try:
        cursor.execute(sql, (error_message, job_id))
        get_db().commit()
        if cursor.rowcount > 0:
            logger.error(f"Set error status. Message: {error_message}")
        else:
             logger.warning("Attempted to set error status for non-existent job.")
    except MySQLError as err:
        logger.error(f"Error setting error status in DB: {err}", exc_info=True)
        get_db().rollback()
    finally:
        # The cursor is managed by the application context, so we don't close it here.
        pass


def mark_active_jobs_interrupted(job_ids) -> int:
    """Mark only jobs proven abandoned by lease/lock recovery as interrupted."""
    job_ids = [job_id for job_id in job_ids if job_id]
    if not job_ids:
        return 0
    cursor = get_cursor()
    message = "WORKER_INTERRUPTED: The application restarted before this transcription completed."
    placeholders = ", ".join(["%s"] * len(job_ids))
    try:
        cursor.execute(
            f"""
            UPDATE transcriptions
            SET status = 'interrupted',
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
                error_message = %s,
                progress_log = JSON_ARRAY_APPEND(
                    COALESCE(progress_log, JSON_ARRAY()), '$', %s
                )
            WHERE id IN ({placeholders})
              AND status IN ('pending', 'processing', 'cancelling')
            """,
            (message, message, *job_ids),
        )
        interrupted_count = cursor.rowcount
        get_db().commit()
        if interrupted_count:
            get_logger(__name__, component="DB:Recovery").warning(
                "Marked %s abandoned transcription job(s) as interrupted.", interrupted_count
            )
        return interrupted_count
    except MySQLError:
        get_db().rollback()
        get_logger(__name__, component="DB:Recovery").exception(
            "Failed to mark abandoned transcription jobs as interrupted."
        )
        raise


def finalize_job_success(
    job_id: str,
    transcription_text: str,
    detected_language: str,
    has_transcription_warning: bool = False,
    transcription_warning_detail: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Updates a job record upon successful completion. Sets status to 'finished',
    saves the transcription text and detected language, and clears any previous error message.
    Also adds a success message to the progress log.
    """
    logger = get_logger(__name__, job_id=job_id, component="DB:Job")
    success = False

    try:
        update_job_progress(job_id, "Transcription successful and saved.")
    except Exception as prog_err:
        logger.error(f"Failed to add success message to progress log: {prog_err}", exc_info=True)

    sql = """
        UPDATE transcriptions
        SET status = 'finished',
            completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
            transcription_text = %s,
            detected_language = %s,
            has_transcription_warning = %s,
            transcription_warning_detail = %s,
            error_message = NULL
        WHERE id = %s
        """
    cursor = get_cursor()
    try:
        cursor.execute(
            sql,
            (
                transcription_text,
                detected_language,
                bool(has_transcription_warning),
                json.dumps(transcription_warning_detail) if transcription_warning_detail else None,
                job_id,
            ),
        )
        get_db().commit()
        if cursor.rowcount > 0:
            logger.info("Finalized job successfully in DB.")
            success = True
        else:
             logger.warning("Attempted to finalize non-existent job.")
    except MySQLError as err:
        logger.error(f"Error finalizing successful job in DB: {err}", exc_info=True)
        get_db().rollback()
        try:
            set_job_error(job_id, f"Failed to save final results: {err}")
        except Exception as inner_e:
            logger.error(f"CRITICAL: Failed to set error status after finalize failure: {inner_e}")
    finally:
        # The cursor is managed by the application context, so we don't close it here.
        pass
    return success


def update_title_generation_status(transcription_id: str, status: str) -> bool:
    """Updates the title_generation_status for a specific transcription."""
    logger = get_logger(__name__, job_id=transcription_id, component="DB:TitleGen")
    # --- MODIFIED: Add 'disabled' to valid_statuses ---
    valid_statuses = ['pending', 'processing', 'success', 'failed', 'disabled']
    # --- END MODIFIED ---
    if status not in valid_statuses:
        logger.error(f"Attempted to set invalid title generation status: '{status}'")
        return False

    sql = "UPDATE transcriptions SET title_generation_status = %s WHERE id = %s"
    cursor = get_cursor()
    success = False
    try:
        cursor.execute(sql, (status, transcription_id))
        get_db().commit()
        if cursor.rowcount > 0:
            logger.info(f"Updated title generation status to: {status}")
            success = True
        else:
            logger.warning("Attempted to update title generation status for non-existent job.")
    except MySQLError as err:
        logger.error(f"Error updating title generation status to '{status}': {err}", exc_info=True)
        get_db().rollback()
    finally:
        # The cursor is managed by the application context, so we don't close it here.
        pass
    return success


def update_transcription_cost(transcription_id: str, cost: float) -> bool:
    """Updates the cost for a specific transcription."""
    logger = get_logger(__name__, job_id=transcription_id, component="DB:Cost")
    sql = "UPDATE transcriptions SET cost = %s WHERE id = %s"
    cursor = get_cursor()
    success = False
    try:
        cursor.execute(sql, (cost, transcription_id))
        get_db().commit()
        if cursor.rowcount > 0:
            logger.debug(f"Updated transcription cost to: {cost}")
            success = True
        else:
            logger.warning("Attempted to update cost for non-existent transcription.")
    except MySQLError as err:
        logger.error(f"Error updating transcription cost to '{cost}': {err}", exc_info=True)
        get_db().rollback()
    finally:
        # The cursor is managed by the application context, so we don't close it here.
        pass
    return success


def set_generated_title(transcription_id: str, title: str) -> bool:
    """Sets the generated_title and updates status to 'success'."""
    logger = get_logger(__name__, job_id=transcription_id, component="DB:TitleGen")
    sql = "UPDATE transcriptions SET generated_title = %s, title_generation_status = 'success' WHERE id = %s"
    cursor = get_cursor()
    success = False
    try:
        cursor.execute(sql, (title, transcription_id))
        get_db().commit()
        if cursor.rowcount > 0:
            logger.info(f"Set generated title and status to 'success'. Title: '{title}'")
            success = True
        else:
            logger.warning("Attempted to set generated title for non-existent job.")
    except MySQLError as err:
        logger.error(f"Error setting generated title: {err}", exc_info=True)
        get_db().rollback()
    finally:
        # The cursor is managed by the application context, so we don't close it here.
        pass
    return success
