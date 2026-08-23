import json
import logging
import sys
import threading
import urllib.error
import urllib.request

from django.conf import settings

from .models import Complaint, Notification, RegistrationRequest, User

logger = logging.getLogger(__name__)

_SKIP_EMAIL_SUFFIXES = (
    "@pahle.iocl.local",
    "@example.com",
    "@example.org",
    ".local",
)


def _unique_users(users, exclude=None):
    skip = {getattr(exclude, "id", None)}
    seen = set()
    out = []
    for user in users:
        if not user or not getattr(user, "id", None) or user.id in skip or user.id in seen:
            continue
        if not user.is_active:
            continue
        seen.add(user.id)
        out.append(user)
    return out


def _can_email(user):
    address = (getattr(user, "email", "") or "").strip()
    username = getattr(user, "username", "?")
    if "@" not in address:
        logger.warning("email skip user=%s reason=no_address", username)
        return False
    lowered = address.lower()
    if any(lowered.endswith(suffix) for suffix in _SKIP_EMAIL_SUFFIXES):
        logger.warning("email skip user=%s to=%s reason=placeholder_address", username, address)
        return False
    return True


def _email_suppressed():
    if not getattr(settings, "EMAIL_HOST_PASSWORD", ""):
        logger.warning("email suppressed reason=missing_EMAIL_HOST_PASSWORD")
        return True
    if "seed" in sys.argv:
        logger.info("email suppressed reason=seed_command")
        return True
    return False


def _deliver_emails(payload):
    """HTTPS to Resend in a background thread. SMTP port 465 hangs on Render."""
    api_key = settings.EMAIL_HOST_PASSWORD
    from_email = settings.DEFAULT_FROM_EMAIL
    timeout = getattr(settings, "EMAIL_TIMEOUT", 8)
    for subject, body, to_addr in payload:
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(
                {
                    "from": from_email,
                    "to": [to_addr],
                    "subject": subject,
                    "text": body,
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "PAHLE-APP/1.0",
            },
            method="POST",
        )
        logger.info("email sending to=%s subject=%s", to_addr, subject)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            mail_id = ""
            try:
                mail_id = json.loads(raw).get("id") or ""
            except json.JSONDecodeError:
                pass
            logger.info("email sent to=%s resend_id=%s", to_addr, mail_id)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            logger.warning("email rejected to=%s status=%s body=%s", to_addr, exc.code, detail)
        except Exception:
            logger.exception("email failed to=%s", to_addr)


def _send_emails(recipients, title, body, link=""):
    if _email_suppressed():
        return
    base = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    url = f"{base}{link}" if link and base else base
    text = body.strip()
    if url:
        text = f"{text}\n\nOpen in PAHLE-APP: {url}".strip()
    payload = []
    for user in recipients:
        if not _can_email(user):
            continue
        payload.append((f"PAHLE-APP: {title}", text or title, user.email.strip()))
    if not payload:
        logger.warning(
            "email not queued title=%s reason=no_real_recipients in_app_users=%s",
            title,
            ",".join(u.username for u in recipients) or "-",
        )
        return
    logger.info("email queued title=%s to=%s", title, ",".join(item[2] for item in payload))
    threading.Thread(target=_deliver_emails, args=(payload,), daemon=True, name="pahle-email").start()


def notify(users, *, kind, title, body="", link="", complaint=None, registration=None, exclude=None):
    recipients = _unique_users(users, exclude=exclude)
    if not recipients:
        logger.warning("notify skipped kind=%s title=%s reason=no_recipients", kind, title)
        return
    logger.info(
        "in-app notify kind=%s title=%s users=%s",
        kind,
        title,
        ",".join(u.username for u in recipients),
    )
    Notification.objects.bulk_create(
        [
            Notification(
                recipient=user,
                kind=kind,
                title=title,
                body=body,
                link=link,
                complaint=complaint,
                registration=registration,
            )
            for user in recipients
        ]
    )
    _send_emails(recipients, title, body, link)


def admins():
    return list(User.objects.filter(role=User.Role.ADMIN, is_active=True))


def vendor_login(complaint):
    vendor = complaint.assigned_vendor
    if not vendor:
        return None
    return vendor.user


def cp_watchers(complaint):
    users = [complaint.submitted_by]
    pump = getattr(complaint, "pump", None)
    if pump:
        users.extend(list(pump.portal_users.filter(is_active=True)))
    return users


def complaint_link(complaint):
    return f"/complaints?q={complaint.complaint_id}"


def complaint_officers(complaint):
    users = [*admins(), complaint.sales_officer]
    pump = getattr(complaint, "pump", None)
    if pump and getattr(pump, "engineering_officer", None):
        users.append(pump.engineering_officer)
    return users


def notify_escalation(complaint, actor, note):
    cid = complaint.complaint_id
    notify(
        complaint_officers(complaint),
        kind=Notification.Kind.ESCALATION,
        title=f"{cid} escalated by the pump user",
        body=note[:400] or f"{complaint.pump.name}: user asked for faster action.",
        link=complaint_link(complaint),
        complaint=complaint,
        exclude=actor,
    )
    vendor_user = vendor_login(complaint)
    if vendor_user:
        notify(
            [vendor_user],
            kind=Notification.Kind.ESCALATION,
            title=f"{cid} was escalated by the customer",
            body="Please treat this job as high priority.",
            link=complaint_link(complaint),
            complaint=complaint,
            exclude=actor,
        )


def notify_site_issue(issue):
    complaint = issue.complaint
    cid = complaint.complaint_id
    kind = issue.get_kind_display()
    notify(
        [*complaint_officers(complaint), *cp_watchers(complaint)],
        kind=Notification.Kind.SITE_ISSUE,
        title=f"{cid}: vendor reported a site problem",
        body=f"{kind}. {issue.description}"[:400],
        link=complaint_link(complaint),
        complaint=complaint,
        exclude=issue.reported_by,
    )


def notify_new_complaint(complaint):
    title = f"New complaint {complaint.complaint_id}"
    body = f"{complaint.pump.name}: {complaint.specific_problem}. Assign a vendor."
    notify(
        [*admins(), complaint.sales_officer],
        kind=Notification.Kind.ASSIGN_VENDOR,
        title=title,
        body=body,
        link=complaint_link(complaint),
        complaint=complaint,
        exclude=complaint.submitted_by,
    )


def notify_registration(rec: RegistrationRequest):
    who = f"{rec.first_name} {rec.last_name}".strip() or rec.username
    kind_label = rec.get_kind_display()
    notify(
        admins(),
        kind=Notification.Kind.REGISTRATION,
        title="New registration request",
        body=f"{who} applied as {kind_label}. Review and approve.",
        link="/approvals",
        registration=rec,
    )


def notify_registration_decision(rec: RegistrationRequest, user: User):
    approved = rec.status == RegistrationRequest.Status.APPROVED
    logger.info(
        "registration decision username=%s approved=%s user_email=%s request_email=%s",
        rec.username,
        approved,
        user.email,
        rec.email,
    )
    if rec.email and user.email != rec.email:
        user.email = rec.email
        user.save(update_fields=["email"])
    notify(
        [user],
        kind=Notification.Kind.REGISTRATION,
        title="Registration approved" if approved else "Registration declined",
        body=(
            "Your PAHLE-APP login is ready. You can sign in now."
            if approved
            else "Your registration was not approved. Contact the sales officer if needed."
        ),
        link="/login" if not approved else "/dashboard",
        registration=rec,
    )


def notify_transition(complaint, actor, from_status, to_status):
    cid = complaint.complaint_id
    label = complaint.get_status_display()
    pump = complaint.pump.name
    link = complaint_link(complaint)
    body = f"{pump} · {complaint.specific_problem}"

    notify(
        cp_watchers(complaint),
        kind=Notification.Kind.STATUS,
        title=f"{cid} updated to {label}",
        body=body,
        link=link,
        complaint=complaint,
        exclude=actor,
    )

    if to_status in (Complaint.Status.SUBMITTED, Complaint.Status.ASSIGNED_TO_OFFICER):
        notify(
            [*admins(), complaint.sales_officer],
            kind=Notification.Kind.ASSIGN_VENDOR,
            title=f"Assign a vendor for {cid}",
            body=body,
            link=link,
            complaint=complaint,
            exclude=actor,
        )
    else:
        notify(
            [*admins(), complaint.sales_officer],
            kind=Notification.Kind.STATUS,
            title=f"{cid} · {label}",
            body=body,
            link=link,
            complaint=complaint,
            exclude=actor,
        )

    vendor_user = vendor_login(complaint)
    if to_status == Complaint.Status.ASSIGNED_TO_VENDOR:
        notify(
            [vendor_user],
            kind=Notification.Kind.VENDOR_ASSIGNED,
            title=f"You have been assigned {cid}",
            body=f"{pump}: {complaint.specific_problem}",
            link=link,
            complaint=complaint,
            exclude=actor,
        )
    elif to_status == Complaint.Status.CLOSED:
        notify(
            [vendor_user],
            kind=Notification.Kind.STATUS,
            title=f"{cid} was closed",
            body="The pump user confirmed the work.",
            link=link,
            complaint=complaint,
            exclude=actor,
        )
    elif to_status == Complaint.Status.WORK_IN_PROGRESS and from_status in (
        Complaint.Status.WORK_COMPLETION,
        Complaint.Status.USER_CONFIRMATION,
    ):
        notify(
            [vendor_user],
            kind=Notification.Kind.STATUS,
            title=f"Re-work requested on {cid}",
            body="The user asked for the job to be done again.",
            link=link,
            complaint=complaint,
            exclude=actor,
        )
