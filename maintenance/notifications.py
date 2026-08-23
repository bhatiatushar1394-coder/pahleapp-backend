from .models import Complaint, Notification, RegistrationRequest, User


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


def notify(users, *, kind, title, body="", link="", complaint=None, registration=None, exclude=None):
    recipients = _unique_users(users, exclude=exclude)
    if not recipients:
        return
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
