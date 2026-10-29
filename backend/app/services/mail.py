"""Outgoing email over SMTP, with branded HTML and plain-text bodies.

Email is optional: when LLX_SMTP_HOST is empty, ``enabled()`` is False and callers fall
back to links that an administrator shares. Sending never raises into a request; failures
are logged so that a mail outage cannot reveal whether an account exists.
"""

from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

from ..config import get_settings

log = logging.getLogger(__name__)


def enabled() -> bool:
    return get_settings().mail_enabled


def send(to: str, subject: str, text: str, html_body: str) -> bool:
    """Send one message. Returns True on success; logs and returns False on failure."""
    s = get_settings()
    if not s.mail_enabled:
        return False
    msg = EmailMessage()
    name, addr = parseaddr(s.mail_from)
    msg["From"] = formataddr((name or "LorvenLax", addr))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=addr.split("@")[-1] if "@" in addr else None)
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    try:
        if s.smtp_security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
        with client:
            if s.smtp_security == "starttls":
                client.starttls(context=ssl.create_default_context())
            if s.smtp_username:
                client.login(s.smtp_username, s.smtp_password)
            client.send_message(msg)
        log.info("mail sent subject=%r", subject)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log.error("mail delivery failed subject=%r error=%s", subject, exc)
        return False


# --------------------------------------------------------------------------- templates

def _layout(heading: str, paragraphs: list[str], button: tuple[str, str] | None, footer: str) -> str:
    """Table-based layout with inline styles so it renders in Gmail, Outlook and Apple Mail."""
    body = "".join(f'<p style="margin:0 0 16px;font-size:15px;line-height:24px;color:#3f3f46">{p}</p>' for p in paragraphs)
    cta = ""
    link_note = ""
    if button:
        label, url = button
        safe_url = html.escape(url, quote=True)
        cta = (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 24px"><tr>'
               f'<td style="border-radius:8px;background:#4338ca"><a href="{safe_url}" '
               f'style="display:inline-block;padding:12px 22px;font-size:15px;font-weight:600;color:#ffffff;'
               f'text-decoration:none;border-radius:8px">{html.escape(label)}</a></td></tr></table>')
        link_note = (f'<p style="margin:0 0 16px;font-size:13px;line-height:20px;color:#71717a">If the button does not work, '
                     f'copy this link into your browser:<br><a href="{safe_url}" style="color:#4338ca;word-break:break-all">'
                     f'{safe_url}</a></p>')
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(heading)}</title></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:32px 16px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px">
<tr><td style="padding:0 4px 20px">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="width:36px;height:36px;border-radius:8px;background:#4338ca;color:#ffffff;font-size:14px;font-weight:700;text-align:center">LL</td>
<td style="padding-left:10px;font-size:15px;font-weight:600;color:#18181b">LorvenLax AI Testing</td>
</tr></table></td></tr>
<tr><td style="background:#ffffff;border:1px solid #e4e4e7;border-radius:12px;padding:32px">
<h1 style="margin:0 0 16px;font-size:20px;line-height:28px;color:#18181b">{html.escape(heading)}</h1>
{body}{cta}{link_note}
<p style="margin:0;font-size:13px;line-height:20px;color:#71717a">{footer}</p>
</td></tr>
<tr><td style="padding:20px 4px;font-size:12px;line-height:18px;color:#a1a1aa;text-align:center">
Lorven Lax Tech Labs Pvt. Ltd. &middot; This is an automated message; replies are not monitored.</td></tr>
</table></td></tr></table></body></html>"""


def password_reset(name: str, url: str, minutes: int) -> tuple[str, str, str]:
    subject = "Reset your LorvenLax password"
    expiry = f"{minutes} minutes" if minutes < 120 else f"{minutes // 60} hours"
    text = (f"Hi {name},\n\nWe received a request to reset the password for your LorvenLax account.\n\n"
            f"Choose a new password here (the link works once and expires in {expiry}):\n{url}\n\n"
            "If you did not ask for this, you can ignore this email. Your password will not change.\n\n"
            "Lorven Lax Tech Labs Pvt. Ltd.")
    page = _layout("Reset your password",
                   [f"Hi {html.escape(name)},",
                    "We received a request to reset the password for your LorvenLax account. "
                    f"Click the button below to choose a new one. The link works once and expires in {expiry}."],
                   ("Choose a new password", url),
                   "If you did not ask for this, you can ignore this email. Your password will not change.")
    return subject, text, page


def admin_password_reset(name: str, admin_name: str, url: str, hours: int) -> tuple[str, str, str]:
    subject = "Set a new LorvenLax password"
    text = (f"Hi {name},\n\n{admin_name}, an administrator of your LorvenLax workspace, sent you a link to set a new password.\n\n"
            f"Choose a new password here (the link works once and expires in {hours} hours):\n{url}\n\n"
            "If you were not expecting this, contact your administrator.\n\nLorven Lax Tech Labs Pvt. Ltd.")
    page = _layout("Set a new password",
                   [f"Hi {html.escape(name)},",
                    f"{html.escape(admin_name)}, an administrator of your LorvenLax workspace, sent you a link to set a new password. "
                    f"The link works once and expires in {hours} hours."],
                   ("Choose a new password", url),
                   "If you were not expecting this, contact your administrator.")
    return subject, text, page


def password_changed(name: str, when: str, signin_url: str) -> tuple[str, str, str]:
    subject = "Your LorvenLax password was changed"
    text = (f"Hi {name},\n\nThe password for your LorvenLax account was changed on {when}. "
            "You have been signed out on every device.\n\n"
            "If you did not make this change, reset your password straight away and tell your workspace administrator:\n"
            f"{signin_url}\n\nLorven Lax Tech Labs Pvt. Ltd.")
    page = _layout("Your password was changed",
                   [f"Hi {html.escape(name)},",
                    f"The password for your LorvenLax account was changed on {html.escape(when)}. "
                    "For your security, you have been signed out on every device."],
                   ("Sign in", signin_url),
                   "If you did not make this change, reset your password straight away and tell your workspace administrator.")
    return subject, text, page


def invitation(org_name: str, inviter: str, role: str, url: str) -> tuple[str, str, str]:
    subject = f"{inviter} invited you to {org_name} on LorvenLax"
    text = (f"Hi,\n\n{inviter} invited you to join the {org_name} workspace on LorvenLax AI Testing as a {role}.\n\n"
            f"Accept the invitation here:\n{url}\n\nLorven Lax Tech Labs Pvt. Ltd.")
    page = _layout(f"Join {org_name} on LorvenLax",
                   [f"{html.escape(inviter)} invited you to join the <strong>{html.escape(org_name)}</strong> workspace "
                    f"on LorvenLax AI Testing as a <strong>{html.escape(role)}</strong>."],
                   ("Accept invitation", url),
                   "If you were not expecting this invitation, you can ignore this email.")
    return subject, text, page


def test_message() -> tuple[str, str, str]:
    subject = "LorvenLax email is working"
    text = "This is a test message from your LorvenLax installation. Email delivery is configured correctly."
    page = _layout("Email is working", ["This is a test message from your LorvenLax installation. "
                                        "Password reset links and invitations will now be emailed."], None,
                   "You received this because an administrator ran the email test command.")
    return subject, text, page
