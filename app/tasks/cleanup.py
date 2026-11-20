# app/tasks/cleanup.py
# Defines the background task for cleaning up old files and purging user history.

import logging
import os
import threading
from typing import Optional
from app.logging_config import get_logger

# Import necessary services and models
from app.services import file_service
from app.models import transcription_utils
from app.models import user as user_model
from app.models import llm_operation as llm_operation_model
from app.models import live_session as live_session_model
from app.models import background_job as background_job_model
from app.models.role import Role

from flask import Flask

from mysql.connector import Error as MySQLError

def run_cleanup_task(
    app: Flask,
    *,
    run_once: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """
    The cleanup task. It never runs inside a web worker: the container runs it
    as a thread of the background worker process (`flask worker --with-cleanup`),
    or on its own with `flask cleanup-loop`.
    Periodically cleans old uploaded files and purges user transcription history based on role limits.
    The one-shot mode is used by cron and the explicit Flask CLI command.

    Args:
        app: The Flask application instance.
    """
    logger = get_logger(__name__, component="Task:Cleanup")
    stop_event = stop_event or threading.Event()
    initial_wait_seconds = 0 if run_once else 20
    if initial_wait_seconds:
        logger.debug(
            f"Cleanup process started. Waiting {initial_wait_seconds}s for app startup..."
        )
        if stop_event.wait(initial_wait_seconds):
            return
        logger.debug("Initial wait complete. Starting periodic cleanup loop.")

    sleep_interval_seconds = 6 * 60 * 60

    while not stop_event.is_set():
        logger.debug("Starting cleanup cycle.")

        try:
            # Ensure operations run within the Flask application context
            with app.app_context():
                config = app.config

                # --- 1. Old File Cleanup ---
                upload_dir = config['TEMP_UPLOADS_DIR']
                threshold = config.get('DELETE_THRESHOLD', 24 * 60 * 60) # Default 24h
                logger.debug(f"Running periodic file cleanup in '{upload_dir}' (threshold: {threshold}s).")
                try:
                    # If queue state cannot be read, skip deletion rather than
                    # remove an input that a delayed job still needs.
                    protected_paths = background_job_model.get_active_transcription_file_paths()
                    deleted_count = file_service.cleanup_old_files(
                        upload_dir, threshold, protected_paths=protected_paths
                    )
                    if deleted_count > 0:
                        logger.info(f"File cleanup finished. Deleted {deleted_count} old file(s).")
                    else:
                        logger.debug("File cleanup finished. No old files to delete.")
                except Exception as file_err:
                    logger.error(f"Error during file cleanup: {file_err}", exc_info=True)

                # --- 2. User History Purging (Soft Delete) ---
                logger.debug("Running periodic history cleanup (soft delete).")
                total_hidden_history = 0
                try:
                    all_users = user_model.get_all_users()
                    logger.debug(f"Found {len(all_users)} users for history check.")

                    for user in all_users:
                        user_logger = get_logger(__name__, component="Task:Cleanup", user_id=user.id)
                        try:
                            role: Optional[Role] = user.role
                            if role:
                                max_items = role.max_history_items
                                retention_days = role.history_retention_days

                                if max_items > 0 or retention_days > 0:
                                    user_logger.debug("Checking history limits.", extra={"role": role.name, "max_items": max_items, "retention_days": retention_days})
                                    hidden_count = transcription_utils.purge_user_history(user.id, max_items, retention_days)

                                    if hidden_count > 0:
                                        total_hidden_history += hidden_count
                                        user_logger.info(f"Hid {hidden_count} history records based on retention policy.")
                                    elif hidden_count == 0:
                                        user_logger.debug("No history records needed hiding.")
                                    else: # hidden_count == -1 indicates an error during purge
                                        user_logger.error("Error occurred during history hiding (check model logs).")
                                else:
                                    user_logger.debug("No history limits set for role; skipping.", extra={"role": role.name})
                            else:
                                user_logger.warning("User has no role assigned. Skipping history hiding.")
                        except MySQLError as user_db_err:
                            user_logger.error(f"DB error processing history hiding: {user_db_err}", exc_info=True)
                        except Exception as user_purge_err:
                            user_logger.error(f"Error processing history hiding: {user_purge_err}", exc_info=True)

                    if total_hidden_history > 0:
                        logger.info(f"History hiding finished. Hid {total_hidden_history} records across all users.")
                    else:
                        logger.debug("History hiding finished. No records hidden.")

                except MySQLError as history_db_err:
                    logger.error(f"DB error during history hiding process: {history_db_err}", exc_info=True)
                except Exception as history_err:
                    logger.error(f"Error during history hiding process: {history_err}", exc_info=True)

                # --- 3. Physical Deletion of Old Hidden Records ---
                physical_delete_days = config.get('PHYSICAL_DELETION_DAYS', 120)
                logger.debug(f"Running physical deletion of records hidden for more than {physical_delete_days} days.")
                total_physically_deleted = 0
                try:
                    deleted_count = transcription_utils.physically_delete_hidden_records(physical_delete_days)
                    if deleted_count > 0:
                        total_physically_deleted = deleted_count
                        logger.info(f"Physically deleted {total_physically_deleted} old hidden records.")
                    elif deleted_count == 0:
                        logger.debug("No old hidden records found for physical deletion.")
                    else: # deleted_count == -1 indicates an error
                        logger.error("Error occurred during physical deletion (check model logs).")
                except MySQLError as physical_del_db_err:
                    logger.error(f"DB error during physical deletion: {physical_del_db_err}", exc_info=True)
                except Exception as physical_del_err:
                    logger.error(f"Error during physical deletion: {physical_del_err}", exc_info=True)

                # --- 4. Physical Deletion of Orphaned LLM Operations ---
                # Transcription deletion severs llm_operations links (ON DELETE
                # SET NULL); purge the orphaned rows on the same schedule so
                # their stored prompt/result text follows the same policy.
                logger.debug(f"Running orphaned LLM operation cleanup (older than {physical_delete_days} days).")
                try:
                    orphans_deleted = llm_operation_model.delete_orphaned_llm_operations(physical_delete_days)
                    if orphans_deleted > 0:
                        logger.info(f"Deleted {orphans_deleted} orphaned LLM operation record(s).")
                    elif orphans_deleted == 0:
                        logger.debug("No orphaned LLM operations found for cleanup.")
                except MySQLError as orphan_db_err:
                    logger.error(f"DB error during orphaned LLM operation cleanup: {orphan_db_err}", exc_info=True)
                except Exception as orphan_err:
                    logger.error(f"Error during orphaned LLM operation cleanup: {orphan_err}", exc_info=True)

                # --- 5. Durable Live Session Retention ---
                # Keep replay/idempotency state for a bounded period, then
                # remove terminal and abandoned rows (including stale claims).
                logger.debug("Running live-session retention cleanup.")
                try:
                    live_sessions_deleted = live_session_model.purge_expired_sessions()
                    if live_sessions_deleted > 0:
                        logger.info(
                            "Deleted %s expired live-session record(s).",
                            live_sessions_deleted,
                        )
                except MySQLError as live_session_db_err:
                    logger.error(
                        "DB error during live-session retention cleanup: %s",
                        live_session_db_err,
                        exc_info=True,
                    )
                except Exception as live_session_err:
                    logger.error(
                        "Error during live-session retention cleanup: %s",
                        live_session_err,
                        exc_info=True,
                    )

                # --- 6. Durable Background Job Retention ---
                # Keep terminal rows long enough to diagnose failures, then
                # remove them so the queue table cannot grow without bound.
                background_job_retention_days = config.get(
                    'BACKGROUND_JOB_RETENTION_DAYS', 30
                )
                background_job_purge_batch_size = config.get(
                    'BACKGROUND_JOB_PURGE_BATCH_SIZE', 1000
                )
                logger.debug(
                    "Running terminal background-job cleanup (older than %s days).",
                    background_job_retention_days,
                )
                try:
                    jobs_deleted = background_job_model.purge_terminal_jobs(
                        background_job_retention_days,
                        background_job_purge_batch_size,
                    )
                    if jobs_deleted > 0:
                        logger.info(
                            "Deleted %s retained terminal background job record(s).",
                            jobs_deleted,
                        )
                except MySQLError as background_job_db_err:
                    logger.error(
                        "DB error during terminal background-job cleanup: %s",
                        background_job_db_err,
                        exc_info=True,
                    )
                except Exception as background_job_err:
                    logger.error(
                        "Error during terminal background-job cleanup: %s",
                        background_job_err,
                        exc_info=True,
                    )

        except Exception as cycle_err:
            try:
                logger.error(f"Error during cleanup task cycle: {cycle_err}", exc_info=True)
            except Exception:
                print(f"CRITICAL [Task:Cleanup]: Logging failed during cleanup task error: {cycle_err}", flush=True)
            if run_once:
                raise

        if run_once:
            return

        # --- Sleep until the next cycle ---
        try:
            logger.debug(f"Cleanup cycle finished. Sleeping for {sleep_interval_seconds} seconds.")
        except Exception:
            print("INFO [Task:Cleanup]: Cleanup cycle finished. Sleeping...", flush=True)

        stop_event.wait(sleep_interval_seconds)


def start_cleanup_thread(app: Flask, stop_event: threading.Event) -> threading.Thread:
    """Run the cleanup loop in a daemon thread of the current process.

    Used by the background worker so cleanup does not need its own Python
    process (which would load the whole app for about a second of work every
    six hours). Each cycle already catches its own errors; if the loop still
    dies unexpectedly, the process exits so the container restarts, rather
    than leaving retention cleanup silently stopped.
    """
    def _target() -> None:
        try:
            run_cleanup_task(app, stop_event=stop_event)
        except BaseException:
            logging.getLogger(__name__).critical(
                "Embedded cleanup loop stopped unexpectedly; exiting so the process restarts.",
                exc_info=True,
            )
            os._exit(1)

    thread = threading.Thread(target=_target, name="cleanup-loop", daemon=True)
    thread.start()
    return thread


def run_cleanup_once(app: Flask) -> None:
    """Run one cleanup cycle for cron, containers, or manual operation."""
    run_cleanup_task(app, run_once=True)
