# app/services/email_service.py
# Handles sending emails, initially for password recovery.
# (No changes needed for MySQL migration)

import logging
from flask import current_app, render_template, url_for
from flask_mail import Message # Import Message class
from app.extensions import mail # Import the mail instance from extensions

class EmailServiceError(Exception):
    """Custom exception for email service errors."""
    pass

def send_password_reset_email(user_email: str, username: str, token: str) -> None:
    """
    Sends a password reset email to the user.

    Args:
        user_email: The recipient's email address.
        username: The recipient's username (for personalization).
        token: The password reset token.

    Raises:
        EmailServiceError: If email configuration is missing or sending fails.
    """
    log_prefix = f"[SERVICE:Email:Reset:{user_email}]"

    required_configs = ['MAIL_SERVER', 'MAIL_DEFAULT_SENDER']
    auth_configs_present = current_app.config.get('MAIL_USERNAME') and current_app.config.get('MAIL_PASSWORD')

    if not all(current_app.config.get(key) for key in required_configs):
        logging.critical(f"{log_prefix} Email service is not fully configured in .env (missing server or sender). Cannot send email.")
        raise EmailServiceError("Email service is not configured.")

    try:
        reset_url = url_for('auth.reset_password_request', token=token, _external=True)
        logging.debug(f"{log_prefix} Generated reset URL: {reset_url}")
    except RuntimeError as e:
        logging.error(f"{log_prefix} Failed to generate reset URL (likely missing app context): {e}")
        raise EmailServiceError("Could not generate password reset URL.") from e

    subject = "Reset your password - Transcriber"
    sender = current_app.config['MAIL_DEFAULT_SENDER']
    recipients = [user_email]

    try:
        html_body = render_template('email/reset_password.html',
                                    username=username,
                                    reset_url=reset_url)
        text_body = render_template('email/reset_password.txt',
                                    username=username,
                                    reset_url=reset_url)

        msg = Message(subject=subject,
                      sender=sender,
                      recipients=recipients,
                      body=text_body,
                      html=html_body)

        logging.info(f"{log_prefix} Attempting to send password reset email...")
        mail.send(msg)
        logging.info(f"{log_prefix} Password reset email sent successfully.")

    except Exception as e:
        logging.error(f"{log_prefix} Failed to send password reset email: {e}", exc_info=True)
        raise EmailServiceError("Failed to send password reset email.") from e

# Future: Add functions for other email types (e.g., email confirmation)
# def send_confirmation_email(user_email: str, username: str, token: str) -> None: ...