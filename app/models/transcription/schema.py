from mysql.connector import Error as MySQLError

from app.database import get_cursor, get_db
from app.logging_config import get_logger


def init_db_command() -> None:
    """
    Initializes the 'transcriptions' table schema in the MySQL database.
    Called via the 'flask init-db' command or initialization sequence.
    Ensures the table and indices exist.
    Includes columns for user association, file metadata, status, and results.
    Uses transactions for atomicity.
    """
    cursor = get_cursor()
    logger = get_logger(__name__, component="DB:Schema:MySQL")
    logger.info("[DB:Schema:MySQL] Checking/Initializing 'transcriptions' table schema...")

    try:
        # --- Dependency Check: Ensure 'users' table exists first ---
        cursor.execute("SHOW TABLES LIKE 'users'")
        if not cursor.fetchone():
            logger.error("Cannot initialize 'transcriptions' table: 'users' table does not exist yet.")
            raise RuntimeError("User table must exist before transcriptions table can be initialized.")
        cursor.fetchall()  # Consume results if any

        # --- Create 'transcriptions' table if it doesn't exist (MySQL syntax) ---
        # --- MODIFIED: Added 'disabled' to title_generation_status ENUM ---
        create_table_sql = '''
            CREATE TABLE IF NOT EXISTS transcriptions (
                id VARCHAR(36) PRIMARY KEY,
                user_id INT NOT NULL,
                filename VARCHAR(255),
                generated_title VARCHAR(255) DEFAULT NULL,
                title_generation_status ENUM('pending', 'processing', 'success', 'failed', 'disabled') NOT NULL DEFAULT 'pending',
                file_size_mb DOUBLE,
                audio_length_minutes DOUBLE,
                detected_language VARCHAR(10),
                transcription_text MEDIUMTEXT,
                api_used VARCHAR(50),
                api_model VARCHAR(120) DEFAULT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP NULL DEFAULT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                progress_log JSON,
                error_message TEXT,
                has_transcription_warning BOOLEAN NOT NULL DEFAULT FALSE,
                transcription_warning_detail JSON DEFAULT NULL,
                context_prompt_used BOOLEAN DEFAULT FALSE,
                downloaded BOOLEAN DEFAULT FALSE,
                is_hidden_from_user BOOLEAN NOT NULL DEFAULT FALSE,
                hidden_date TIMESTAMP NULL DEFAULT NULL,
                hidden_reason ENUM('USER_DELETED', 'RETENTION_POLICY') DEFAULT NULL,
                pending_workflow_prompt_text TEXT DEFAULT NULL,
                pending_workflow_prompt_title VARCHAR(100) DEFAULT NULL,
                pending_workflow_prompt_color VARCHAR(7) DEFAULT NULL,
                pending_workflow_origin_prompt_id INT DEFAULT NULL,
                public_api_invocation BOOLEAN NOT NULL DEFAULT FALSE,
                cost DECIMAL(10, 5) DEFAULT NULL,

                 FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                 INDEX idx_transcription_user (user_id),
                INDEX idx_transcription_status (status),
                INDEX idx_transcription_created_at (created_at),
                INDEX idx_transcription_api_used (api_used),
                INDEX idx_transcription_language (detected_language),
                INDEX idx_transcription_user_hidden_created (user_id, is_hidden_from_user, created_at),
                INDEX idx_transcription_hidden_date (is_hidden_from_user, hidden_date),
                INDEX idx_title_generation_status (title_generation_status),
                FULLTEXT INDEX ftx_transcription_history (filename, generated_title, transcription_text)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        '''
        # --- END MODIFIED ---
        cursor.execute(create_table_sql)
        logger.debug("CREATE TABLE IF NOT EXISTS transcriptions executed.")

        # --- Idempotent ALTER TABLE to handle potential existing tables ---
        # Check and rename/modify audio_length_seconds if it exists
        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'audio_length_seconds'")
        old_col_exists = cursor.fetchone()
        cursor.fetchall()  # Consume remaining results
        if old_col_exists:
            logger.info("Found old 'audio_length_seconds' column. Renaming and changing type to DOUBLE for 'audio_length_minutes'.")
            cursor.execute("ALTER TABLE transcriptions CHANGE COLUMN audio_length_seconds audio_length_minutes DOUBLE")
        else:
            cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'audio_length_minutes'")
            new_col_exists = cursor.fetchone()
            cursor.fetchall()  # Consume remaining results
            if not new_col_exists:
                logger.info("Adding 'audio_length_minutes' column (DOUBLE).")
                cursor.execute("ALTER TABLE transcriptions ADD COLUMN audio_length_minutes DOUBLE AFTER file_size_mb")

        # Check and add context_prompt_used
        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'context_prompt_used'")
        context_col_exists = cursor.fetchone()
        cursor.fetchall()  # Consume remaining results
        if not context_col_exists:
            logger.info("Adding 'context_prompt_used' column (BOOLEAN).")
            cursor.execute("ALTER TABLE transcriptions ADD COLUMN context_prompt_used BOOLEAN DEFAULT FALSE AFTER error_message")

        # Check and add transcription warning flag
        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'has_transcription_warning'")
        transcription_warning_col_exists = cursor.fetchone()
        cursor.fetchall()
        if not transcription_warning_col_exists:
            logger.info("Adding 'has_transcription_warning' column (BOOLEAN).")
            cursor.execute(
                "ALTER TABLE transcriptions "
                "ADD COLUMN has_transcription_warning BOOLEAN NOT NULL DEFAULT FALSE "
                "AFTER error_message"
            )

        # Check and add downloaded column
        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'downloaded'")
        downloaded_col_exists = cursor.fetchone()
        cursor.fetchall()  # Consume remaining results
        if not downloaded_col_exists:
            logger.info("Adding 'downloaded' column (BOOLEAN).")
            cursor.execute("ALTER TABLE transcriptions ADD COLUMN downloaded BOOLEAN DEFAULT FALSE AFTER context_prompt_used")

        # Check and add is_hidden_from_user
        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'is_hidden_from_user'")
        hidden_flag_exists = cursor.fetchone()
        cursor.fetchall()  # Consume remaining results
        if not hidden_flag_exists:
            logger.info("Adding 'is_hidden_from_user' column (BOOLEAN).")
            cursor.execute("ALTER TABLE transcriptions ADD COLUMN is_hidden_from_user BOOLEAN NOT NULL DEFAULT FALSE AFTER downloaded")

        # Check and add hidden_date
        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'hidden_date'")
        hidden_date_exists = cursor.fetchone()
        cursor.fetchall()  # Consume remaining results
        if not hidden_date_exists:
            logger.info("Adding 'hidden_date' column (TIMESTAMP).")
            cursor.execute("ALTER TABLE transcriptions ADD COLUMN hidden_date TIMESTAMP NULL DEFAULT NULL AFTER is_hidden_from_user")

        # Check and add hidden_reason
        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'hidden_reason'")
        hidden_reason_exists = cursor.fetchone()
        cursor.fetchall()  # Consume remaining results
        if not hidden_reason_exists:
            logger.info("Adding 'hidden_reason' column (ENUM).")
            cursor.execute("ALTER TABLE transcriptions ADD COLUMN hidden_reason ENUM('USER_DELETED', 'RETENTION_POLICY') DEFAULT NULL AFTER hidden_date")

        # Add generated_title and title_generation_status columns idempotently
        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'generated_title'")
        gen_title_exists = cursor.fetchone()
        cursor.fetchall()
        if not gen_title_exists:
            logger.info("Adding 'generated_title' column (VARCHAR(255)) to 'transcriptions' table.")
            cursor.execute("ALTER TABLE transcriptions ADD COLUMN generated_title VARCHAR(255) DEFAULT NULL AFTER filename")

        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'title_generation_status'")
        title_status_exists = cursor.fetchone()
        cursor.fetchall()
        if not title_status_exists:
            logger.info("Adding 'title_generation_status' column (ENUM) to 'transcriptions' table.")
            # --- MODIFIED: Added 'disabled' to ENUM definition for new column ---
            cursor.execute("ALTER TABLE transcriptions ADD COLUMN title_generation_status ENUM('pending', 'processing', 'success', 'failed', 'disabled') NOT NULL DEFAULT 'pending' AFTER generated_title")
            # --- END MODIFIED ---
        else:
            # --- MODIFIED: Modify existing column to include 'disabled' ---
            cursor.execute("SELECT COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'transcriptions' AND COLUMN_NAME = 'title_generation_status'")
            current_enum_type = cursor.fetchone()['COLUMN_TYPE']
            cursor.fetchall()
            if 'disabled' not in current_enum_type:
                logger.info("Modifying 'title_generation_status' ENUM to include 'disabled'.")
                cursor.execute("ALTER TABLE transcriptions MODIFY COLUMN title_generation_status ENUM('pending', 'processing', 'success', 'failed', 'disabled') NOT NULL DEFAULT 'pending'")
            # --- END MODIFIED ---

        # --- MODIFIED: Add pending_workflow_origin_prompt_id column idempotently ---
        pending_workflow_columns = {
            'pending_workflow_prompt_text': "TEXT DEFAULT NULL AFTER llm_operation_ran_at",
            'pending_workflow_prompt_title': "VARCHAR(100) DEFAULT NULL AFTER pending_workflow_prompt_text",
            'pending_workflow_prompt_color': "VARCHAR(7) DEFAULT NULL AFTER pending_workflow_prompt_title",
            'pending_workflow_origin_prompt_id': "INT DEFAULT NULL AFTER pending_workflow_prompt_color" # Added
        }
        # --- END MODIFIED ---
        for col_name, col_def in pending_workflow_columns.items():
            cursor.execute(f"SHOW COLUMNS FROM transcriptions LIKE '{col_name}'")
            col_exists = cursor.fetchone()
            cursor.fetchall()
            if not col_exists:
                logger.info(f"Adding '{col_name}' column to 'transcriptions' table.")
                cursor.execute(f"ALTER TABLE transcriptions ADD COLUMN {col_name} {col_def}")
        # --- END NEW ---

        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'public_api_invocation'")
        public_api_exists = cursor.fetchone()
        cursor.fetchall()
        if not public_api_exists:
            logger.info("Adding 'public_api_invocation' column to 'transcriptions' table.")
            cursor.execute("ALTER TABLE transcriptions ADD COLUMN public_api_invocation BOOLEAN NOT NULL DEFAULT FALSE AFTER pending_workflow_origin_prompt_id")

        # Check and add cost
        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'cost'")
        cost_col_exists = cursor.fetchone()
        cursor.fetchall()  # Consume remaining results
        if not cost_col_exists:
            logger.info("Adding 'cost' column (DECIMAL(10, 5)).")
            cursor.execute("ALTER TABLE transcriptions ADD COLUMN cost DECIMAL(10, 5) DEFAULT NULL AFTER pending_workflow_origin_prompt_id")

        # Check and add is_pinned
        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'is_pinned'")
        is_pinned_col_exists = cursor.fetchone()
        cursor.fetchall()
        if not is_pinned_col_exists:
            logger.info("Adding 'is_pinned' column (BOOLEAN).")
            cursor.execute("ALTER TABLE transcriptions ADD COLUMN is_pinned BOOLEAN NOT NULL DEFAULT FALSE AFTER cost")

        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'api_model'")
        if not cursor.fetchone():
            cursor.execute(
                "ALTER TABLE transcriptions "
                "ADD COLUMN api_model VARCHAR(120) DEFAULT NULL AFTER api_used"
            )
        cursor.fetchall()

        # --- Add/Check Indexes ---
        index_checks = {
            'idx_transcription_created_at': 'created_at',
            'idx_transcription_api_used': 'api_used',
            'idx_transcription_language': 'detected_language',
            'idx_transcription_user_hidden_created': 'user_id, is_hidden_from_user, created_at',
            'idx_transcription_hidden_date': 'is_hidden_from_user, hidden_date',
            'idx_title_generation_status': 'title_generation_status',
            'idx_transcription_user_pinned_created': 'user_id, is_pinned, created_at',
        }
        for idx_name, col_def in index_checks.items():
            cursor.execute(f"SHOW INDEX FROM transcriptions WHERE Key_name = '{idx_name}'")
            idx_exists = cursor.fetchone()
            cursor.fetchall()
            if not idx_exists:
                logger.info(f"Adding index '{idx_name}' to 'transcriptions' table.")
                cursor.execute(f"ALTER TABLE transcriptions ADD INDEX {idx_name} ({col_def})")

        cursor.execute("SHOW INDEX FROM transcriptions WHERE Key_name = 'ftx_transcription_history'")
        fulltext_exists = cursor.fetchone()
        cursor.fetchall()
        if not fulltext_exists:
            logger.info("Adding full-text history search index.")
            cursor.execute(
                "ALTER TABLE transcriptions ADD FULLTEXT INDEX "
                "ftx_transcription_history (filename, generated_title, transcription_text)"
            )

        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'completed_at'")
        completed_at_col = cursor.fetchone()
        cursor.fetchall()
        if not completed_at_col:
            logger.info("Adding 'completed_at' column (TIMESTAMP).")
            cursor.execute(
                "ALTER TABLE transcriptions "
                "ADD COLUMN completed_at TIMESTAMP NULL DEFAULT NULL AFTER created_at"
            )

        # Normalize timestamp columns
        cursor.execute("SHOW COLUMNS FROM transcriptions LIKE 'created_at'")
        created_at_col = cursor.fetchone()
        cursor.fetchall()
        created_at_type = (created_at_col.get('Type') if isinstance(created_at_col, dict) else (created_at_col[1] if created_at_col else "")).lower()
        if created_at_col and 'timestamp' not in created_at_type:
            logger.info("Converting 'created_at' column on 'transcriptions' table to TIMESTAMP.")
            cursor.execute("ALTER TABLE transcriptions MODIFY COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP")

        for col_name in ('hidden_date', 'llm_operation_ran_at'):
            cursor.execute(f"SHOW COLUMNS FROM transcriptions LIKE '{col_name}'")
            col_info = cursor.fetchone()
            cursor.fetchall()
            col_type = (col_info.get('Type') if isinstance(col_info, dict) else (col_info[1] if col_info else "")).lower()
            if col_info and 'timestamp' not in col_type:
                logger.info(f"Converting '{col_name}' column on 'transcriptions' table to TIMESTAMP.")
                cursor.execute(f"ALTER TABLE transcriptions MODIFY COLUMN {col_name} TIMESTAMP NULL DEFAULT NULL")
        get_db().commit()
        logger.info("[DB:Schema:MySQL] 'transcriptions' table schema verified/initialized.")

    except MySQLError as err:
        logger.error(f"MySQL error during 'transcriptions' table initialization: {err}", exc_info=True)
        get_db().rollback()
        raise
    except RuntimeError as e:  # Catch dependency errors
        logger.error(f"Initialization dependency error: {e}")
        get_db().rollback()
        raise
    finally:
        # The cursor is managed by the application context, so we don't close it here.
        pass
