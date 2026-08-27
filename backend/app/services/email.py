"""Outbound email.

Every message is rendered with the *sending organization's* branding, because
a feedback invitation that looks like it came from a software vendor rather
than from the recipient's own client gets deleted unread.
"""

from __future__ import annotations

import asyncio
import smtplib
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from html import escape

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import TargetType

log = get_logger("facet.email")

# `send_feedback_request` covers every polymorphic target type, and one
# generic "we value your feedback on X, share your experience" sentence does
# not read naturally for all of them. A client, product, or service is a
# thing the recipient has an *experience with* — the original copy fits. An
# employee, manager, team, or department is a *person or group being
# reviewed* — the recipient is being asked to evaluate someone, not to
# recount their own experience of them, so the framing has to shift to
# "share feedback on" rather than "share your experience of".
#
# `send_assignment_notice` and `send_reminder` share this same distinction
# (see `_person_review_noun` below), so all three functions read from the
# one mapping rather than keeping their own copies in sync by hand.
_PERSON_REVIEW_TARGET_TYPES = {
    TargetType.EMPLOYEE,
    TargetType.MANAGER,
    TargetType.TEAM,
    TargetType.DEPARTMENT,
}

_PERSON_REVIEW_NOUNS = {
    TargetType.EMPLOYEE: "colleague",
    TargetType.MANAGER: "manager",
    TargetType.TEAM: "team",
    TargetType.DEPARTMENT: "department",
}


def _person_review_noun(target_type: str | TargetType | None) -> str | None:
    """Resolve `target_type` to its "your <noun>" word, or None if this
    target isn't a person/group being reviewed (client, product, service,
    an unrecognised type, or no type at all). Centralised so the three
    call sites below can't quietly drift out of sync with each other."""
    try:
        resolved = TargetType(target_type) if target_type else None
    except ValueError:
        resolved = None
    if resolved not in _PERSON_REVIEW_TARGET_TYPES:
        return None
    return _PERSON_REVIEW_NOUNS[resolved]

def _hours_label(hours: int) -> str:
    """'1 hour' when the invite TTL is exactly one hour, '72 hours'
    otherwise — every invitation-family email quotes this duration, and a
    literal ' hours' suffix reads as a grammar bug the moment the setting
    is ever configured to 1 (as it currently is for local testing)."""
    return f"{hours} hour" if hours == 1 else f"{hours} hours"

def _first_name(name: str) -> str:
    """First word of a name, capitalized if it wasn't already — a name
    stored all-lowercase (e.g. typed that way at signup) would otherwise
    show up verbatim as "Dear sagar" or "Welcome, raj!". Only the first
    letter is touched; the rest of the word is left exactly as given, so a
    name with its own internal capitalization (e.g. "McDonald", "deWitt")
    is never mangled. Falls back to "there" for a blank name."""
    first = name.split()[0] if name.strip() else ""
    return first[0].upper() + first[1:] if first else "there"

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
        else "&nbsp;"
    )
    heading_block = (
        f'<tr><td style="font:600 20px Helvetica,Arial,sans-serif;color:#12161C;padding:24px 0 8px">'
        f'{escape(heading)}</td></tr>'
        if heading
        else ""
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
          Or click the link below:<br>
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
    {heading_block}
    <tr><td style="font:400 14px/1.6 Helvetica,Arial,sans-serif;color:#39414D">
        {body_html}</td></tr>
    {cta_block}
    <tr><td style="padding-top:26px;border-top:1px solid #DDE1E6;
        font:400 11px/1.5 Helvetica,Arial,sans-serif;color:#8A93A0">
        {footer}{'<br>' if footer else ''}
        Powered by Stixis AI Solutions © Copyright 2026-2027
    </td></tr>
  </table>
 </td></tr>
</table></body></html>"""


def _plain(heading: str, body_text: str, cta: tuple[str, str] | None) -> str:
    parts = [heading, "", body_text] if heading else [body_text]
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
        max_attempts = 3
        retry_delay_seconds = 1.5

        def _send_sync() -> bool:
            last_error: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
                        if settings.smtp_tls:
                            client.starttls()
                        if settings.smtp_user:
                            client.login(settings.smtp_user, settings.smtp_password)
                        client.send_message(message)
                    return True
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt < max_attempts:
                        delay = retry_delay_seconds * attempt
                        log.warning(
                            "email_send_retry",
                            to=to,
                            attempt=attempt,
                            error=str(exc),
                            retry_in_seconds=delay,
                        )
                        time.sleep(delay)
            log.error(
                "email_send_failed", to=to, error=str(last_error), attempts=max_attempts
            )
            return False

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
            f"Welcome to {escape(branding.org_name)}! We're excited to have you "
            f"on board.<br><br>"
            f"You have been given access to <b>{escape(branding.org_name)}</b> as "
            f"an Admin. Set a password to "
            f"activate your account. This link can be used once and expires in "
            f"{_hours_label(settings.invite_token_ttl_hours)}."
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
        heading = "Please Share Your Feedback"
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
    target_type: str | TargetType | None = None,
    subject_template: str | None = None,
) -> bool:
    """Invite an external contact to give feedback.

    Carries the *client's* branding, not the vendor's. A feedback request that
    looks like it came from a software company the recipient has never heard of
    gets deleted unread, which is the difference between a 40% response rate
    and a 4% one.

    `target_type` picks the copy: `subject_label` is a *thing with which the
    recipient has an experience* (a client relationship, a product, a
    service) for most target types, but for employee, manager, team, and
    department targets it names a *person or group being reviewed*, and the
    wording switches accordingly. An unrecognised or missing target_type
    falls back to the original client-style copy rather than raising, since a
    caller passing a still-valid but newly-added TargetType should degrade
    gracefully, not break the send.
    """
    import re

    first_name = _first_name(full_name)
    deadline = expires_at.strftime("%d %B %Y")
    subject_label = re.sub(r"\s*\([^)]*\)\s*$", "", subject_label).strip()

    noun = _person_review_noun(target_type)

    if noun is not None:
        subject = "Feedback Request"
        if subject_template:
            try:
                subject = subject_template.format(org_name=org_name, subject_label=subject_label)
            except (KeyError, IndexError):
                pass
        heading = f"Share your feedback on {subject_label}"
        body_html = (
            f"Dear {escape(first_name)},<br><br>"
            f"You have been asked to share feedback on your "
            f"{noun}, <b>{escape(subject_label)}</b>. Your input helps build "
            f"a clear, well-rounded picture of how things are going and "
            f"where there is room to grow.<br><br>"
            f"This link will expire on "
            f"{escape(deadline)}."
        )
        body_text = (
            f"Dear {first_name},\n\n"
            f"You have been asked to share feedback on your {noun}, "
            f"{subject_label}. Your input helps build a clear, well-rounded "
            f"picture of how things are going and where there is room to "
            f"grow.\n\n"
            f"This link will expire on "
            f"{deadline}."
        )
    else:
        subject = "Please Share Your Feedback"
        if subject_template:
            try:
                subject = subject_template.format(org_name=org_name, subject_label=subject_label)
            except (KeyError, IndexError):
                pass
        heading = ""
        try:
            is_proposal = target_type is not None and TargetType(target_type) == TargetType.PROPOSAL
        except ValueError:
            is_proposal = False
        experience_line = (
            "Your responses help us understand where we can improve."
            if is_proposal
            else "Your responses help us understand what is working well "
                 "and where we can improve."
        )
        body_html = (
            f"Dear {escape(first_name)},<br><br>"
            f"{escape(org_name)} values your feedback on "
            f"<b>{escape(subject_label)}</b> and would appreciate a few minutes "
            f"of your time to share your experience. {experience_line}<br><br>"
            f"This link will expire on "
            f"{escape(deadline)}."
        )
        body_text = (
            f"Dear {first_name},\n\n"
            f"{org_name} values your feedback on {subject_label} and would "
            f"appreciate a few minutes of your time to share your experience. "
            f"{experience_line}\n\n"
            f"This link will expire on "
            f"{deadline}."
        )

    return await send(
        to=to,
        subject=subject,
        heading=heading,
        body_html=body_html,
        body_text=body_text,
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
    target_type: str | TargetType | None = None,
) -> bool:
    first_name = _first_name(full_name)
    when = f" It closes on {due_at.strftime('%d %B')}." if due_at else ""
    noun = _person_review_noun(target_type)

    if noun is not None:
        opening_html = (
            f"You have been asked to share feedback on your {noun}, "
            f"<b>{escape(subject_label)}</b>, as part of "
            f"{escape(cycle_name)}.{escape(when)}"
        )
        opening_text = (
            f"You have been asked to share feedback on your {noun}, "
            f"{subject_label}, as part of {cycle_name}.{when}"
        )
    else:
        opening_html = (
            f"We would appreciate your feedback on "
            f"<b>{escape(subject_label)}</b>.{escape(when)}"
        )
        opening_text = (
            f"We would appreciate your feedback on {subject_label}."
            f"{when}"
        )

    closing_html = (
        "It takes just a couple of minutes to complete — the link below "
        "will sign you in automatically."
        if external
        else "It takes just a couple of minutes to complete."
    )
    closing_text = "It takes just a couple of minutes to complete."

    return await send(
        to=to,
        subject="Feedback Request",
        heading="",
        body_html=(
            f"Dear {escape(first_name)},<br><br>{opening_html} {closing_html} "
            f"Thank you for your time."
        ),
        body_text=(
            f"Dear {first_name},\n\n{opening_text} {closing_text} "
            f"Thank you for your time."
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
    target_type: str | TargetType | None = None,
) -> bool:
    first_name = _first_name(full_name)
    when = f" It closes on {due_at.strftime('%d %B')}." if due_at else ""
    noun = _person_review_noun(target_type)

    if noun is not None:
        opening_html = (
            f"You have not yet shared your feedback on your {noun}, "
            f"<b>{escape(subject_label)}</b>, for "
            f"{escape(cycle_name)}.{escape(when)}"
        )
        opening_text = (
            f"You have not yet shared your feedback on your {noun}, "
            f"{subject_label}, for {cycle_name}.{when}"
        )
    else:
        opening_html = (
            f"You have not yet given your feedback on "
            f"<b>{escape(subject_label)}</b> for {escape(cycle_name)}.{escape(when)}"
        )
        opening_text = (
            f"You have not yet given your feedback on {subject_label} for "
            f"{cycle_name}.{when}"
        )

    closing_html = (
        "It takes about two minutes, and this link signs you straight in."
        if external
        else "It takes about two minutes."
    )
    closing_text = "It takes about two minutes."

    return await send(
        to=to,
        subject=f"Reminder: your feedback on {subject_label}",
        heading="A quick reminder",
        body_html=(
            f"Dear {escape(first_name)},<br><br>{opening_html} {closing_html}"
        ),
        body_text=(
            f"Dear {first_name},\n\n{opening_text} {closing_text}"
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
    first_name = _first_name(full_name)
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
    first_name = _first_name(full_name)
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


async def send_org_rejected(
    *,
    to: str,
    org_name: str,
    contact_name: str,
    rejection_reason: str,
    branding: Branding,
) -> bool:
    """Tell a self-registered applicant their organization was not approved.

    No CTA — there is nothing for the recipient to click through to. This is
    a closed loop, not an invitation to take further action on the platform.
    """
    first_name = _first_name(contact_name)
    return await send(
        to=to,
        subject=f"Your Registration for {org_name} Was Not Approved",
        heading=f"Dear {first_name}",
        body_html=(
            f"Thank you for your interest.<br><br>"
            f"We have reviewed your registration request for "
            f"<b>{escape(org_name)}</b> and regret to inform you that we are "
            f"unable to approve it at this time.<br><br>"
            f"Reason: {escape(rejection_reason)}<br><br>"
            f"We appreciate the time you took to register, and wish you the "
            f"best in your future endeavors."
        ),
        body_text=(
            f"Thank you for your interest.\n\n"
            f"We have reviewed your registration request for {org_name} and "
            f"regret to inform you that we are unable to approve it at this "
            f"time.\n\n"
            f"Reason: {rejection_reason}\n\n"
            f"We appreciate the time you took to register, and wish you the "
            f"best in your future endeavors."
        ),
        branding=branding,
    )


async def send_org_suspended(
    *,
    to: str,
    org_name: str,
    contact_name: str,
    suspension_reason: str,
    branding: Branding,
) -> bool:
    """Tell an org's primary contact that their organization has been
    suspended, and that this already took effect — not that it is about to.

    No CTA — there is no link to give someone whose sessions were just
    revoked; a "sign in" button here would only invite a failed attempt.
    """
    first_name = _first_name(contact_name)
    return await send(
        to=to,
        subject=f"Your {org_name} Account Has Been Suspended",
        heading=f"Dear {first_name}",
        body_html=(
            f"We would like to inform you that access to "
            f"{settings.product_name} for {org_name} has been temporarily "
            f"suspended.\n\n"
            f"Reason: {escape(suspension_reason)}<br><br>"
            f"As part of this action, all active sessions associated with "
            f"your organization have been signed out. Access will remain "
            f"unavailable until the organization is reactivated."
        ),
        body_text=(
            f"We would like to inform you that access to "
            f"{settings.product_name} for {org_name} has been temporarily "
            f"suspended.\n\n"
            f"Reason: {suspension_reason}\n\n"
            f"As part of this action, all active sessions associated with "
            f"your organization have been signed out. Access will remain "
            f"unavailable until the organization is reactivated."
        ),
        branding=branding,
    )


async def send_organization_reactivated(
    *,
    to: str,
    org_name: str,
    contact_name: str,
    branding: Branding,
) -> bool:
    """Tell an org's primary contact that access has been restored.

    Counterpart to `send_org_suspended` — no CTA here either. There is no
    token or one-time link involved in a reactivation; existing accounts
    simply work again, so the message just needs to say sign-in is open,
    not hand the recipient another link to click.
    """
    first_name = _first_name(contact_name)
    return await send(
        to=to,
        subject=f"Your {org_name} Account Has Been Reactivated",
        heading=f"Dear {first_name}",
        body_html=(
            f"We would like to inform you that access "
            f"for {org_name} has been reactivated.\n\n"
            f"You and your team can now sign in and continue using the "
            f"platform."
        ),
        body_text=(
            f"We would like to inform you that access "
            f"for {org_name} has been reactivated.\n\n"
            f"You and your team can now sign in and continue using the "
            f"platform."
        ),
        branding=branding,
    )


async def send_invitation(
    *,
    to: str,
    full_name: str,
    org_name: str,
    invite_url: str,
    branding: Branding,
    subject_template: str | None = None,
    kind: str = "invitation",
    role: str | None = None,
) -> bool:
    """
    `kind` selects which invitation this is:

      - "invitation" (default): a Client Admin account being created —
        Super Admin provisioning a tenant, adding a Client Admin to an
        existing org, or approving one via the non-"approval" path. Always
        "as an Admin", because these three callers only ever create Client
        Admins.

      - "approval": the self-registration "Request access" flow being
        approved. Distinct copy acknowledging a request was reviewed, not
        just that access was handed out.

      - "user": a regular org member being invited from Users → Create (or
        bulk import), where the role picked in that form can be Admin,
        Manager, or Employee. `role` is a human-readable label (e.g.
        "Admin", "Manager", "Employee") and the sentence is built around it
        rather than assuming Admin — this is what fixes an Employee or
        Manager invite wrongly reading "as an Admin".
    """
    first_name = _first_name(full_name)

    if kind == "approval":
        subject = "Your Organization Has Been Approved"
        if subject_template:
            try:
                subject = subject_template.format(org_name=org_name)
            except (KeyError, IndexError):
                pass
        return await send(
            to=to,
            subject=subject,
            heading=f"Dear {first_name}",
            body_html=(
                f"We are pleased to inform you that your request to register "
                f"<b>{escape(org_name)}</b> "
                f"has been approved. You may now activate your admin account "
                f"using the link below.<br><br>"
                f"This link will expire in "
                f"{_hours_label(settings.invite_token_ttl_hours)}."
            ),
            body_text=(
                f"We are pleased to inform you that your request to register "
                f"{org_name} has been approved. You "
                f"may now activate your admin account using the link below.\n\n"
                f"This link will expire in "
                f"{_hours_label(settings.invite_token_ttl_hours)}."
            ),
            branding=branding,
            cta=("Activate Your Account", invite_url),
        )

    if kind == "user":
        # role is optional in the signature for backward-compatibility, but
        # every real "user" call site should supply one — "User" is only a
        # fallback so a missing role degrades gracefully instead of raising.
        display_role = role or "User"
        article = "an" if display_role[:1].upper() in "AEIOU" else "a"
        subject = f"You Have Been Added to {org_name}"
        if subject_template:
            try:
                subject = subject_template.format(org_name=org_name)
            except (KeyError, IndexError):
                pass
        return await send(
            to=to,
            subject=subject,
            heading=f"Dear {first_name}",
            body_html=(
                f"You have been added to <b>{escape(org_name)}</b> as {article} "
                f"{escape(display_role)}.<br><br>"
                f"Set a password to activate your account and get started. "
                f"This link can be used once and expires in "
                f"{_hours_label(settings.invite_token_ttl_hours)}."
            ),
            body_text=(
                f"You have been added to {org_name} as {article} {display_role}.\n\n"
                f"Set a password to activate your account and get started. "
                f"This link can be used once and expires in "
                f"{_hours_label(settings.invite_token_ttl_hours)}."
            ),
            branding=branding,
            cta=("Set Your Password", invite_url),
        )

    # Default: "invitation" — Client Admin account, recipient did not
    # initiate the request.
    subject = "You have been invited"
    if subject_template:
        try:
            subject = subject_template.format(org_name=org_name)
        except (KeyError, IndexError):
            pass
    return await send(
        to=to,
        subject=subject,
        heading=f"Welcome, {first_name}!",
        body_html=(
            f"We're excited to have you on "
            f"board.<br><br>"
            f"You have been given access as "
            f"an Admin. Set a password to "
            f"activate your account. This link can be used once and expires "
            f"in {_hours_label(settings.invite_token_ttl_hours)}."
        ),
        body_text=(
            f"We're excited to have you on board.\n\n"
            f"You have been given access as "
            f"an Admin. Set a password to activate "
            f"your account. This link is single use and expires in "
            f"{_hours_label(settings.invite_token_ttl_hours)}."
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
    first_name = _first_name(full_name)
    return await send(
        to=to,
        subject=f"Reset your {org_name} password",
        heading="Password reset request",
        body_html=(
            f"Dear {escape(first_name)},<br><br>"
            f"A password reset was requested for your account. This link "
            f"can be used once and expires in {expires_in_hours} hours. If "
            f"you did not expect this, you can ignore it — your password "
            f"will not change unless you follow the link and set a new one."
        ),
        body_text=(
            f"Dear {first_name},\n\n"
            f"A password reset was requested for your account. This link "
            f"can only be used once and will expire in "
            f"{_hours_label(expires_in_hours)}. If you did not expect this, "
            f"you can ignore it."
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
    target_type: str | TargetType | None = None,
) -> bool:
    """Confirm a submitted response was received.

    Unlike `send_feedback_request` / `send_assignment_notice` /
    `send_reminder` above, this one doesn't split copy by `target_type` —
    it always reads "your feedback on X", regardless of whether X is a
    person/group being reviewed (employee, manager, team, department) or a
    client/product/service. `target_type` is accepted for signature
    parity with the other send_* functions but is currently unused here.
    """
    first_name = _first_name(full_name)
    body_html = (
        f"Your feedback on <b>{escape(subject_label)}</b> has been received. "
        f"We appreciate you taking the time to share it with "
        f"{escape(org_name)}."
    )
    body_text = (
        f"Your feedback on {subject_label} has been received. We appreciate "
        f"you taking the time to share it with {org_name}."
    )

    return await send(
        to=to,
        subject=f"Thank you for your feedback on {subject_label}",
        heading=f"Thank you, {first_name}",
        body_html=body_html,
        body_text=body_text,
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