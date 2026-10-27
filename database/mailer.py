"""Framework-light email sender.

Two delivery backends are supported, selected automatically:

1. **Resend HTTP API** (used when ``RESEND_API_KEY`` is set). Sends over
   HTTPS (port 443), which works on hosts that block outbound SMTP ports
   such as Render's free tier. Configure:

       RESEND_API_KEY  Resend API key (required to enable this backend)
       MAIL_FROM       Verified sender address, e.g. "Spendly <no-reply@yourdomain.com>"
                       (Resend's shared "onboarding@resend.dev" works for testing)

2. **SMTP** (fallback, used when ``RESEND_API_KEY`` is not set). Reads:

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

import requests
from flask import render_template

RESEND_API_URL = "https://api.resend.com/emails"


def _truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def send_email(to, subject, html_body, text_body=None):
    """Send an HTML email. Raises on failure.

    Uses the Resend HTTP API when ``RESEND_API_KEY`` is configured (works on
    hosts that block SMTP ports); otherwise falls back to SMTP. The caller is
    responsible for catching/logging errors.
    """
    if os.environ.get("RESEND_API_KEY"):
        _send_via_resend(to, subject, html_body, text_body)
    else:
        _send_via_smtp(to, subject, html_body, text_body)


def _send_via_resend(to, subject, html_body, text_body=None):
    """Deliver an email through the Resend HTTP API (HTTPS, port 443)."""
    api_key = os.environ["RESEND_API_KEY"]
    sender = os.environ.get("MAIL_FROM") or "onboarding@resend.dev"

    payload = {
        "from": sender,
        "to": [to],
        "subject": subject,
        "html": html_body,
    }
    if text_body:
        payload["text"] = text_body

    response = requests.post(
        RESEND_API_URL,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Resend API error {response.status_code}: {response.text}"
        )


def _send_via_smtp(to, subject, html_body, text_body=None):
    """Deliver an email through an SMTP server."""
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
    text = f"Welcome to ExpenseTracker! Verify your email by visiting: {link}"
    send_email(to, "Verify your ExpenseTracker account", html, text_body=text)


def send_password_reset_email(to, link):
    """Render and send the password-reset email."""
    html = render_template("emails/reset_password.html", link=link)
    text = f"Reset your ExpenseTracker password by visiting: {link}"
    send_email(to, "Reset your ExpenseTracker password", html, text_body=text)
