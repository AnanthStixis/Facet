"""Outbound email.

Every message is rendered with the *sending organization's* branding, because
a feedback invitation that looks like it came from a software vendor rather
than from the recipient's own client gets deleted unread.
"""

from __future__ import annotations

import asyncio
import smtplib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from html import escape

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("facet.email")


@dataclass(slots=True)
class Branding:
    org_name: str
    accent_color: str = "#B4633A"
    logo_url: str | None = None
    footer_note: str | None = None


def _shell(branding: Branding, heading: str, body_html: str, cta: tuple[str, str] | None) -> str:
    """Minimal, table-based HTML.

    Corporate mail clients remain the least capable rendering targets in
    software, so this deliberately avoids flexbox, grid, and web fonts.
    """
    logo_block = (
        f'<img src="{escape(branding.logo_url)}" alt="{escape(branding.org_name)}" '
        f'height="34" style="max-height:34px;border:0;display:block">'
        if branding.logo_url
        else f'<span style="font:600 17px Helvetica,Arial,sans-serif;color:#12161C">'
        f"{escape(branding.org_name)}</span>"
    )
    cta_block = ""
    if cta:
        label, url = cta
        cta_block = f"""
        <tr><td style="padding:22px 0 6px">
          <a href="{escape(url)}" style="background:{branding.accent_color};color:#fff;
             font:600 14px Helvetica,Arial,sans-serif;text-decoration:none;
             padding:12px 22px;border-radius:6px;display:inline-block">{escape(label)}</a>
        </td></tr>
        <tr><td style="font:400 12px Helvetica,Arial,sans-serif;color:#8A93A0;padding-top:10px">
          If the button does not work, paste this into your browser:<br>
          <span style="color:#5A6472;word-break:break-all">{escape(url)}</span>
        </td></tr>"""

    footer = escape(branding.footer_note) if branding.footer_note else ""
    return f"""<!doctype html>
<html><body style="margin:0;background:#F6F7F9;padding:28px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
 <tr><td align="center">
  <table role="presentation" width="560" cellpadding="0" cellspacing="0"
         style="background:#fff;border:1px solid #DDE1E6;border-radius:10px;padding:30px">
    <tr><td style="padding-bottom:20px;border-bottom:2px solid {branding.accent_color}">
        {logo_block}</td></tr>
    <tr><td style="font:600 20px Helvetica,Arial,sans-serif;color:#12161C;padding:24px 0 8px">
        {escape(heading)}</td></tr>
    <tr><td style="font:400 14px/1.6 Helvetica,Arial,sans-serif;color:#39414D">
        {body_html}</td></tr>
    {cta_block}
    <tr><td style="padding-top:26px;border-top:1px solid #DDE1E6;
        font:400 11px/1.5 Helvetica,Arial,sans-serif;color:#8A93A0">
        {footer}{'<br>' if footer else ''}
        Sent by {escape(branding.org_name)} via {escape(settings.product_name)}.
    </td></tr>
  </table>
 </td></tr>
</table></body></html>"""


def _plain(heading: str, body_text: str, cta: tuple[str, str] | None) -> str:
    parts = [heading, "", body_text]
    if cta:
        parts += ["", f"{cta[0]}: {cta[1]}"]
    return "\n".join(parts)


async def send(
    *,
    to: str,
    subject: str,
    heading: str,
    body_html: str,
    body_text: str,
    branding: Branding,
    cta: tuple[str, str] | None = None,
) -> bool:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.email_from_name} <{settings.email_from}>"
    message["To"] = to
    message["Date"] = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
    message["Message-ID"] = f"<{uuid.uuid4()}@facet>"
    message.set_content(_plain(heading, body_text, cta))
    message.add_alternative(_shell(branding, heading, body_html, cta), subtype="html")

    backend = settings.email_backend

    if backend == "file":
        # Development transport: writes a .eml the user can open in any mail
        # client, so templates are reviewable without a running SMTP server.
        outbox = settings.outbox_path
        outbox.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        safe_to = "".join(c if c.isalnum() else "_" for c in to)
        path = outbox / f"{stamp}-{safe_to}.eml"
        path.write_bytes(bytes(message))
        log.info("email_written", to=to, subject=subject, path=str(path))
        return True

    if backend == "console":
        log.info("email_console", to=to, subject=subject, body=body_text)
        return True

    if backend == "smtp":
        def _send_sync() -> bool:
            try:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
                    if settings.smtp_tls:
                        client.starttls()
                    if settings.smtp_user:
                        client.login(settings.smtp_user, settings.smtp_password)
                    client.send_message(message)
                return True
            except Exception as exc:  # noqa: BLE001
                # Never fail the originating action because mail is down. The
                # caller reports email_sent=false and the admin can resend.
                log.error("email_send_failed", to=to, error=str(exc))
                return False

        # smtplib is blocking. Run it off the event loop so one slow or
        # unreachable SMTP handshake (an office365 timeout, say) cannot stall
        # every other request the server is handling concurrently.
        return await asyncio.to_thread(_send_sync)

    log.warning("email_backend_not_implemented", backend=backend)
    return False


def render_preview(
    *,
    kind: str,
    branding: Branding,
    subject_template: str | None = None,
) -> dict[str, str]:
    """Render a sample email exactly as `_shell` would, for an admin to check
    their branding (logo, accent colour, footer note) before anything is
    actually sent — using placeholder recipient and subject-matter names."""
    if kind == "invitation":
        subject = f"You have been invited to {branding.org_name}"
        if subject_template:
            try:
                subject = subject_template.format(org_name=branding.org_name)
            except (KeyError, IndexError):
                pass
        heading = "Welcome, Jordan"
        body_html = (
            f"You have been given access to <b>{escape(branding.org_name)}</b> on "
            f"{escape(settings.product_name)}. Set a password to activate your "
            f"account. This link can be used once and expires in "
            f"{settings.invite_token_ttl_hours} hours."
        )
        cta = ("Set your password", "https://example.com/accept-invite?token=sample")
    else:
        subject_label = "Acme Renewal Q4"
        subject = f"Your feedback on {subject_label}"
        if subject_template:
            try:
                subject = subject_template.format(
                    org_name=branding.org_name, subject_label=subject_label
                )
            except (KeyError, IndexError):
                pass
        heading = "Share Your Feedback"
        body_html = (
            f"{escape(branding.org_name)} values your feedback on "
            f"<b>{escape(subject_label)}</b> and would appreciate a few minutes "
            f"of your time to share your experience. Your responses help us "
            f"understand what is working well and where we can "
            f"improve.<br><br>This is a personal, single-use link and expires "
            f"in 14 days."
        )
        cta = ("Give Feedback", "https://example.com/f/sample-token")

    return {"subject": subject, "html": _shell(branding, heading, body_html, cta)}


async def send_feedback_request(
    *,
    to: str,
    full_name: str,
    org_name: str,
    subject_label: str,
    link: str,
    expires_at: datetime,
    branding: Branding,
    subject_template: str | None = None,
) -> bool:
    """Invite an external contact to give feedback.

    Carries the *client's* branding, not the vendor's. A feedback request that
    looks like it came from a software company the recipient has never heard of
    gets deleted unread, which is the difference between a 40% response rate
    and a 4% one.
    """
    import re

    first_name = full_name.split()[0] if full_name.strip() else "there"
    deadline = expires_at.strftime("%d %B %Y")
    # Strip a trailing parenthetical annotation (e.g. "Aarav Mehta (client
    # relationship)" -> "Aarav Mehta") so the email reads naturally even when
    # the caller passes a label that includes internal categorisation.
    subject_label = re.sub(r"\s*\([^)]*\)\s*$", "", subject_label).strip()
    subject = f"Your Feedback on {subject_label}"
    if subject_template:
        try:
            subject = subject_template.format(org_name=org_name, subject_label=subject_label)
        except (KeyError, IndexError):
            pass
    return await send(
        to=to,
        subject=subject,
        heading="Share Your Feedback",
        body_html=(
            f"Dear {escape(first_name)},<br><br>"
            f"{escape(org_name)} values your feedback on "
            f"<b>{escape(subject_label)}</b> and would appreciate a few minutes "
            f"of your time to share your experience. Your responses help us "
            f"understand what is working well and where we can "
            f"improve.<br><br>"
            f"This is a personal, single-use link and will expire on "
            f"{escape(deadline)}."
        ),
        body_text=(
            f"Dear {first_name},\n\n"
            f"{org_name} values your feedback on {subject_label} and would "
            f"appreciate a few minutes of your time to share your experience. "
            f"Your responses help us understand what is working well and "
            f"where we can improve.\n\n"
            f"This is a personal, single-use link and will expire on "
            f"{deadline}."
        ),
        branding=branding,
        cta=("Give Feedback", link),
    )

async def send_assignment_notice(
    *,
    to: str,
    full_name: str,
    org_name: str,
    subject_label: str,
    cycle_name: str,
    link: str,
    due_at: datetime | None,
    branding: Branding,
    external: bool = False,
) -> bool:
    """Sent once, the moment a reviewer is assigned — distinct from
    `send_reminder`'s later "you still haven't" nudge, this is the one-time
    "you have been asked" notice. Same external/internal split as the
    reminder: an internal reviewer already has an account and the link just
    points them at their queue, so only the external framing claims the link
    signs them straight in.
    """
    first_name = full_name.split()[0] if full_name.strip() else "there"
    when = f" It closes on {due_at.strftime('%d %B')}." if due_at else ""
    return await send(
        to=to,
        subject=f"You have been asked for feedback on {subject_label}",
        heading=f"{first_name}, you have been asked for feedback",
        body_html=(
            f"You have been asked to give feedback on "
            f"<b>{escape(subject_label)}</b> for {escape(cycle_name)}.{escape(when)}"
            + (
                "<br><br>It takes about two minutes, and this link signs you "
                "straight in."
                if external
                else "<br><br>It takes about two minutes — sign in to respond."
            )
        ),
        body_text=(
            f"You have been asked to give feedback on {subject_label} for "
            f"{cycle_name}.{when} It takes about two minutes."
        ),
        branding=branding,
        cta=("Give feedback", link),
    )




async def send_reminder(
    *,
    to: str,
    full_name: str,
    org_name: str,
    subject_label: str,
    cycle_name: str,
    link: str,
    due_at: datetime | None,
    branding: Branding,
    external: bool = False,
) -> bool:
    """A single, specific nudge.

    Names the one thing outstanding rather than saying "you have pending
    items". A reminder that requires the reader to go and look up what it is
    about is a reminder that gets postponed.
    """
    first_name = full_name.split()[0] if full_name.strip() else "there"
    when = f" It closes on {due_at.strftime('%d %B')}." if due_at else ""
    return await send(
        to=to,
        subject=f"Reminder: your feedback on {subject_label}",
        heading=f"{first_name}, a quick reminder",
        body_html=(
            f"You have not yet given your feedback on "
            f"<b>{escape(subject_label)}</b> for {escape(cycle_name)}.{escape(when)}"
            + (
                "<br><br>It takes about two minutes, and this link signs you "
                "straight in."
                if external
                else "<br><br>It takes about two minutes."
            )
        ),
        body_text=(
            f"You have not yet given your feedback on {subject_label} for "
            f"{cycle_name}.{when} It takes about two minutes."
        ),
        branding=branding,
        cta=("Give feedback", link),
    )


async def send_escalation(
    *,
    to: str,
    full_name: str,
    org_name: str,
    cycle_name: str,
    outstanding: list[str],
    link: str,
    branding: Branding,
) -> bool:
    """One digest to the round's owner when nudging has stopped working."""
    first_name = full_name.split()[0] if full_name.strip() else "there"
    shown = outstanding[:15]
    items = "".join(f"<li>{escape(name)}</li>" for name in shown)
    more = (
        f"<li>and {len(outstanding) - len(shown)} more</li>"
        if len(outstanding) > len(shown)
        else ""
    )
    return await send(
        to=to,
        subject=f"{len(outstanding)} outstanding in {cycle_name}",
        heading=f"{first_name}, these people have not responded",
        body_html=(
            f"Everyone below has been reminded the maximum number of times for "
            f"<b>{escape(cycle_name)}</b> and has still not responded. Further "
            f"automated reminders have stopped."
            f"<ul>{items}{more}</ul>"
            f"A word in person is usually more effective than another email."
        ),
        body_text=(
            f"{len(outstanding)} people have not responded to {cycle_name} and "
            f"have been reminded the maximum number of times: "
            + ", ".join(shown)
        ),
        branding=branding,
        cta=("Open the round", link),
    )


async def send_proposal_feedback_request(
    *,
    to: str,
    full_name: str,
    org_name: str,
    proposal_title: str,
    proposal_reference: str,
    link: str,
    branding: Branding,
) -> bool:
    """Ask a prospect what they thought of a proposal.

    The framing matters commercially: this is sent while a decision may still
    be pending, so it must read as a request to improve rather than a nudge to
    buy. Getting that wrong makes the whole module unusable by a sales team.
    """
    first_name = full_name.split()[0] if full_name.strip() else "there"
    return await send(
        to=to,
        subject=f"Your review on our proposal: {proposal_title}",
        heading=f"{first_name}, how was our proposal?",
        body_html=(
            f"We recently sent you <b>{escape(proposal_title)}</b> "
            f"({escape(proposal_reference)}). Whatever you decide, we would "
            f"value five minutes on how the proposal itself landed — the "
            f"technical approach, whether the estimate looked realistic, and "
            f"how we handled the process.<br><br>"
            f"This is not a sales follow-up. It goes to the team that writes "
            f"the proposals, and it is how they get better."
        ),
        body_text=(
            f"We recently sent you {proposal_title} ({proposal_reference}). "
            f"Whatever you decide, we would value five minutes on how the "
            f"proposal itself landed. This is not a sales follow-up."
        ),
        branding=branding,
        cta=("Share your view", link),
    )


async def send_invitation(
    *,
    to: str,
    full_name: str,
    org_name: str,
    invite_url: str,
    branding: Branding,
    subject_template: str | None = None,
) -> bool:
    subject = f"You have been invited to {org_name}"
    if subject_template:
        try:
            subject = subject_template.format(org_name=org_name)
        except (KeyError, IndexError):
            # An unsubstitutable placeholder (a typo, or a `{` the customer
            # did not mean as one) should never break the send — fall back
            # to the default rather than raising mid-invite.
            pass
    return await send(
        to=to,
        subject=subject,
        heading=f"Welcome, {full_name.split()[0]}",
        body_html=(
            f"You have been given access to <b>{escape(org_name)}</b> on "
            f"{escape(settings.product_name)}. Set a password to activate your "
            f"account. This link can be used once and expires in "
            f"{settings.invite_token_ttl_hours} hours."
        ),
        body_text=(
            f"You have been given access to {org_name}. Set a password to activate "
            f"your account. This link is single use and expires in "
            f"{settings.invite_token_ttl_hours} hours."
        ),
        branding=branding,
        cta=("Set your password", invite_url),
    )


async def send_password_reset(
    *,
    to: str,
    full_name: str,
    org_name: str,
    reset_url: str,
    expires_in_hours: int,
    branding: Branding,
) -> bool:
    """An admin-initiated reset link for an existing account.

    Distinct wording from the invitation email on purpose — this is not
    onboarding, and a recipient who did not expect it should be able to tell
    at a glance that someone with admin access requested a password change
    on their account.
    """
    first_name = full_name.split()[0] if full_name.strip() else "there"
    return await send(
        to=to,
        subject=f"Reset your {org_name} password",
        heading=f"{first_name}, reset your password",
        body_html=(
            f"An administrator at <b>{escape(org_name)}</b> requested a password "
            f"reset for your account. This link can be used once and expires in "
            f"{expires_in_hours} hours. If you did not expect this, you can "
            f"ignore it — your password will not change unless you follow the "
            f"link and set a new one."
        ),
        body_text=(
            f"An administrator at {org_name} requested a password reset for your "
            f"account. This link is single use and expires in "
            f"{expires_in_hours} hours. If you did not expect this, you can "
            f"ignore it."
        ),
        branding=branding,
        cta=("Reset your password", reset_url),
    )


async def send_thank_you(
    *,
    to: str,
    full_name: str,
    org_name: str,
    subject_label: str,
    branding: Branding,
) -> bool:
    """Sent to an external respondent right after they submit.

    No link, no call to action — just a close of the loop. Someone who just
    gave two minutes of honest feedback and hears nothing again reasonably
    assumes it went nowhere; this is the one message that tells them
    otherwise.
    """
    first_name = full_name.split()[0] if full_name.strip() else "there"
    return await send(
        to=to,
        subject=f"Thank you for your feedback on {subject_label}",
        heading=f"Thank you, {first_name}",
        body_html=(
            f"Your feedback on <b>{escape(subject_label)}</b> has been received. "
            f"We appreciate you taking the time to share it with "
            f"{escape(org_name)}."
        ),
        body_text=(
            f"Your feedback on {subject_label} has been received. We appreciate "
            f"you taking the time to share it with {org_name}."
        ),
        branding=branding,
    )


async def send_response_notification(
    *,
    to: str,
    org_name: str,
    subject_label: str,
    respondent_name: str | None,
    cycle_name: str,
    answers: list[tuple[str, str]],
    overall_score: float | None,
    comment: str | None,
    branding: Branding,
) -> bool:
    """BCC copy sent to a configured internal address when an external
    response comes in, carrying the full answer content itself — this is
    read by someone who explicitly does not want to open the app for every
    response, so a link to "sign in and look" defeats the point.
    `respondent_name` is omitted entirely for an anonymous round — this
    notification must not become a side channel that de-anonymises a
    response the product otherwise protects. The answers themselves are not
    identity-revealing and are always included.
    """
    who = escape(respondent_name) if respondent_name else "Someone"
    who_text = respondent_name if respondent_name else "Someone"

    rows_html = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#555;'>{escape(question)}</td>"
        f"<td style='padding:4px 0;font-weight:600;'>{escape(answer)}</td></tr>"
        for question, answer in answers
    )
    rows_text = "\n".join(f"- {question}: {answer}" for question, answer in answers)

    overall_html = (
        f"<p style='margin:12px 0 4px;'><b>Overall rating:</b> {overall_score:g} / 5</p>"
        if overall_score is not None
        else ""
    )
    overall_text = f"\nOverall rating: {overall_score:g} / 5" if overall_score is not None else ""

    comment_html = (
        f"<p style='margin:12px 0 4px;'><b>Comment:</b><br>{escape(comment)}</p>" if comment else ""
    )
    comment_text = f"\nComment: {comment}" if comment else ""

    return await send(
        to=to,
        subject=f"New response: {subject_label} ({cycle_name})",
        heading="A new response has come in",
        body_html=(
            f"{who} responded to <b>{escape(cycle_name)}</b>, about "
            f"<b>{escape(subject_label)}</b>.<br><br>"
            f"<table style='border-collapse:collapse;width:100%;'>{rows_html}</table>"
            f"{overall_html}{comment_html}"
        ),
        body_text=(
            f"{who_text} responded to {cycle_name}, about {subject_label}.\n\n"
            f"{rows_text}{overall_text}{comment_text}"
        ),
        branding=branding,
    )