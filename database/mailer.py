"""Framework-light SMTP email sender using the Python standard library.

Reads configuration from environment variables (loaded via python-dotenv in
app.py):

    MAIL_SERVER    SMTP host
    MAIL_PORT      SMTP port (default 587)
    MAIL_USE_TLS   "true"/"1"/"yes" to enable STARTTLS
    MAIL_USERNAME  SMTP username; also the default From address
    MAIL_PASSWORD  SMTP password

Credentials are never hardcoded.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage

from flask import render_template


def _truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def send_email(to, subject, html_body, text_body=None):
    """Send an HTML email via SMTP. Raises on failure.

    The caller is responsible for catching/logging errors.
    """
    host = os.environ.get("MAIL_SERVER")
    if not host:
        raise RuntimeError("MAIL_SERVER is not configured")

    port = int(os.environ.get("MAIL_PORT", "587"))
    username = os.environ.get("MAIL_USERNAME")
    password = os.environ.get("MAIL_PASSWORD")
    use_tls = _truthy(os.environ.get("MAIL_USE_TLS", "true"))
    sender = os.environ.get("MAIL_FROM") or username or "no-reply@spendly.local"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(text_body or "Please view this email in an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(host, port, timeout=15) as server:
        server.ehlo()
        if use_tls:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if username and password:
            server.login(username, password)
        server.send_message(msg)


def send_verification_email(to, link):
    """Render and send the account-verification email."""
    html = render_template("emails/verify_email.html", link=link)
    text = f"Welcome to Spendly! Verify your email by visiting: {link}"
    send_email(to, "Verify your Spendly account", html, text_body=text)


def send_password_reset_email(to, link):
    """Render and send the password-reset email."""
    html = render_template("emails/reset_password.html", link=link)
    text = f"Reset your Spendly password by visiting: {link}"
    send_email(to, "Reset your Spendly password", html, text_body=text)
