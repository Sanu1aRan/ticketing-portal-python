"""
All ticket business rules.  (TicketService.java)

Ticket life:  Open -> In Progress -> Resolved -> Closed
              (an officer can Return it to Open, an admin can Cancel it)
Every step writes one row to ticket_history and sends the emails.
"""

from django.db import transaction

from ..models import Ticket, TicketComment, TicketHistory, User
from ..security import ServiceError
from . import email_service, file_service

SIGNATURE = "Sri Lanka Customs ICT Directorate"


def _s(value):
    # Java prints a missing value as the word "null" when joining text.
    return "null" if value is None else str(value)


def _has_text(value):
    return value is not None and value != ""


def _check_length(label, value, limit=255):
    # These columns hold 255 characters. Say so clearly instead of letting
    # the database reject the row.
    if value is not None and len(value) > limit:
        raise ServiceError(f"{label} is too long (maximum {limit} characters)")


def _name_with_unit(user):
    return _s(user.full_name) + " (" + _s(user.company) + ")"


def _admins():
    return User.objects.filter(role="admin")


def save_history(ticket, status, note):
    TicketHistory.objects.create(ticket=ticket, status=status, note=note)


def _find_user(email):
    return User.objects.filter(email=email).first()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def get_ticket_by_id(ticket_id, not_found="Ticket not found"):
    ticket = Ticket.objects.select_related("user").filter(pk=ticket_id).first()
    if ticket is None:
        raise ServiceError(not_found)
    return ticket


def get_tickets_by_user(user):
    return Ticket.objects.select_related("user").filter(user=user).order_by("-created_at", "-id")


def get_all_tickets():
    return Ticket.objects.select_related("user").order_by("-created_at", "-id")


def get_ticket_history(ticket):
    return TicketHistory.objects.filter(ticket=ticket).order_by("changed_at", "id")


def get_ticket_stats(user):
    statuses = [t.status for t in get_tickets_by_user(user)]
    return {
        "total": len(statuses),
        "open": statuses.count("Open"),
        "inProgress": statuses.count("In Progress"),
        "resolved": statuses.count("Resolved"),
        "closed": statuses.count("Closed"),
        "cancelled": statuses.count("Cancelled"),
    }


def get_recent_tickets(user):
    return get_tickets_by_user(user)[:3]


def get_unit_tickets():
    # Any officer can see every assigned ticket; the unit is only a label.
    return (
        Ticket.objects.select_related("user")
        .filter(assigned_to__isnull=False)
        .order_by("-created_at", "-id")
    )


def get_open_unassigned_tickets():
    # The officer "pickup pool"
    return (
        Ticket.objects.select_related("user")
        .filter(status="Open", assigned_to__isnull=True)
        .order_by("-created_at", "-id")
    )


# ---------------------------------------------------------------------------
# Client actions
# ---------------------------------------------------------------------------
def create_ticket(subject, description, user):
    if subject is None or description is None:
        raise ServiceError("Subject and description are required")
    _check_length("Subject", subject)

    ticket = Ticket.objects.create(subject=subject, description=description, user=user)
    save_history(ticket, "Open", "Ticket submitted")

    email_service.send_email(
        user.email,
        "Ticket Submitted — #" + str(ticket.id),
        "Dear " + user.full_name + ",\n\n"
        "Your ticket has been submitted successfully.\n\n"
        "Ticket ID: #" + str(ticket.id) + "\n"
        "Subject: " + ticket.subject + "\n"
        "Status: Open\n\n"
        "We will get back to you shortly.\n\n" + SIGNATURE,
    )

    for admin in _admins():
        email_service.send_email(
            admin.email,
            "New Ticket Submitted — #" + str(ticket.id),
            "Dear " + admin.full_name + ",\n\n"
            "A new ticket has been submitted.\n\n"
            "Ticket ID: #" + str(ticket.id) + "\n"
            "Client: " + user.full_name + "\n"
            "Subject: " + ticket.subject + "\n\n"
            "Please login to classify and assign this ticket.\n\n" + SIGNATURE,
        )
    return ticket


def update_ticket(ticket_id, subject, description):
    ticket = get_ticket_by_id(ticket_id)
    if ticket.status != "Open":
        raise ServiceError("Only Open tickets can be edited")
    if subject is None or description is None:
        raise ServiceError("Subject and description are required")
    _check_length("Subject", subject)
    ticket.subject = subject
    ticket.description = description
    ticket.save()
    return ticket


@transaction.atomic
def delete_ticket(ticket_id):
    ticket = get_ticket_by_id(ticket_id)
    TicketComment.objects.filter(ticket=ticket).delete()
    TicketHistory.objects.filter(ticket=ticket).delete()
    ticket.delete()


# ---------------------------------------------------------------------------
# Officer / admin actions
# ---------------------------------------------------------------------------
def classify_ticket(ticket_id, category, priority, classifier):
    ticket = get_ticket_by_id(ticket_id)
    _check_length("Category", category)
    _check_length("Priority", priority)
    if _has_text(category):
        ticket.category = category
    if _has_text(priority):
        ticket.priority = priority
    classified_by = _name_with_unit(classifier) if classifier is not None else "system"
    save_history(
        ticket,
        ticket.status,
        "Classified by " + classified_by
        + " — Category: " + _s(ticket.category) + ", Priority: " + _s(ticket.priority),
    )
    ticket.save()
    return ticket


def assign_ticket(ticket_id, officer_email, is_self_pickup):
    """Admin assigns a ticket to an officer, or an officer picks one up."""
    ticket = get_ticket_by_id(ticket_id)

    if not _has_text(officer_email):
        ticket.assigned_to = None
        ticket.assigned_to_name = None
        ticket.assigned_to_unit = None
        ticket.status = "Open"
        save_history(ticket, "Open", "Ticket unassigned — returned to queue")
        ticket.save()
        return ticket

    officer = _find_user(officer_email)
    if officer is None:
        raise ServiceError("Officer not found")

    ticket.assigned_to = officer_email
    ticket.assigned_to_name = _name_with_unit(officer)
    ticket.assigned_to_unit = officer.company
    ticket.status = "In Progress"
    ticket.return_reason = None
    ticket.return_attachment_path = None

    if is_self_pickup:
        save_history(ticket, "In Progress", _name_with_unit(officer) + " picked up this ticket")
        for admin in _admins():
            email_service.send_email(
                admin.email,
                "Ticket Picked Up — #" + str(ticket.id),
                "Dear " + admin.full_name + ",\n\n"
                + _name_with_unit(officer) + " has picked up a ticket.\n\n"
                "Ticket ID: #" + str(ticket.id) + "\n"
                "Subject: " + ticket.subject + "\n\n" + SIGNATURE,
            )
    else:
        save_history(ticket, "In Progress", "Assigned to " + _name_with_unit(officer))
        email_service.send_email(
            officer.email,
            "New Ticket Assigned — #" + str(ticket.id),
            "Dear " + officer.full_name + ",\n\n"
            "A ticket has been assigned to you.\n\n"
            "Ticket ID: #" + str(ticket.id) + "\n"
            "Subject: " + ticket.subject + "\n\n"
            "Please login to the portal to review.\n\n" + SIGNATURE,
        )

    # The client gets the "being processed" email only the FIRST time the
    # ticket goes In Progress, not again after a return and re-pickup.
    in_progress_count = TicketHistory.objects.filter(ticket=ticket, status="In Progress").count()
    if in_progress_count <= 1:
        email_service.send_email(
            ticket.user.email,
            "Ticket Update — #" + str(ticket.id),
            "Dear " + ticket.user.full_name + ",\n\n"
            "Your ticket is now being processed.\n\n"
            "Ticket ID: #" + str(ticket.id) + "\n"
            "Subject: " + ticket.subject + "\n"
            "Status: In Progress\n\n"
            "Our ICT team will resolve your issue shortly.\n\n" + SIGNATURE,
        )

    ticket.save()
    return ticket


def update_ticket_status(ticket_id, status, resolution_note, officer):
    """Used to mark an In Progress ticket as Resolved."""
    ticket = get_ticket_by_id(ticket_id, not_found="Ticket Not Found")
    ticket.status = status
    has_note = _has_text(resolution_note)
    if has_note:
        ticket.resolution_note = resolution_note

    if status == "Resolved":
        if officer is not None:
            ticket.resolved_by = _name_with_unit(officer)
        resolved_by_name = ticket.resolved_by if ticket.resolved_by is not None else ticket.assigned_to
        resolved_by_name = _s(resolved_by_name)

        save_history(
            ticket,
            "Resolved",
            "Resolved by " + resolved_by_name + (" — " + resolution_note if has_note else ""),
        )

        email_service.send_email(
            ticket.user.email,
            "Ticket Resolved — #" + str(ticket.id),
            "Dear " + ticket.user.full_name + ",\n\n"
            "Your ticket has been resolved.\n\n"
            "Ticket ID: #" + str(ticket.id) + "\n"
            "Subject: " + ticket.subject + "\n"
            "Status: Resolved\n"
            "Resolved by: " + resolved_by_name + "\n"
            + ("Resolution: " + resolution_note + "\n" if has_note else "")
            + "\nThank you for contacting Sri Lanka Customs ICT Directorate.",
        )

        for admin in _admins():
            email_service.send_email(
                admin.email,
                "Ticket Resolved — #" + str(ticket.id),
                "Dear " + admin.full_name + ",\n\n"
                "A ticket has been resolved.\n\n"
                "Ticket ID: #" + str(ticket.id) + "\n"
                "Subject: " + ticket.subject + "\n"
                "Client: " + ticket.user.full_name + "\n"
                "Resolved by: " + resolved_by_name + "\n"
                + ("Resolution: " + resolution_note + "\n" if has_note else "")
                + "\n" + SIGNATURE,
            )

    ticket.save()
    return ticket


def return_ticket(ticket_id, reason, officer):
    """Officer gives the ticket back to the queue."""
    ticket = get_ticket_by_id(ticket_id)
    ticket.status = "Open"
    ticket.assigned_to = None
    ticket.assigned_to_name = None
    ticket.assigned_to_unit = None
    ticket.category = None
    ticket.priority = None
    ticket.return_reason = reason

    returned_by = _name_with_unit(officer) if officer is not None else "officer"
    save_history(ticket, "Open", "Returned by " + returned_by + " — " + _s(reason))

    for admin in _admins():
        email_service.send_email(
            admin.email,
            "Ticket Returned — #" + str(ticket.id),
            "Dear " + admin.full_name + ",\n\n"
            "A ticket has been returned by " + returned_by + ".\n\n"
            "Ticket ID: #" + str(ticket.id) + "\n"
            "Subject: " + ticket.subject + "\n"
            "Reason: " + _s(reason) + "\n\n"
            "Please reassign this ticket.\n\n" + SIGNATURE,
        )

    ticket.save()
    return ticket


def reject_ticket(ticket_id, reason, admin):
    """Admin cancels a ticket."""
    ticket = get_ticket_by_id(ticket_id)
    ticket.status = "Cancelled"
    ticket.cancel_reason = reason

    cancelled_by = _s(admin.full_name) if admin is not None else "admin"
    save_history(ticket, "Cancelled", "Cancelled by " + cancelled_by + " — " + _s(reason))

    email_service.send_email(
        ticket.user.email,
        "Ticket Cancelled — #" + str(ticket.id),
        "Dear " + ticket.user.full_name + ",\n\n"
        "Your ticket has been cancelled.\n\n"
        "Ticket ID: #" + str(ticket.id) + "\n"
        "Subject: " + ticket.subject + "\n"
        "Reason: " + _s(reason) + "\n\n"
        "Please contact the ICT Directorate for further assistance.\n\n" + SIGNATURE,
    )

    ticket.save()
    return ticket


def close_ticket(ticket_id, close_note, admin):
    ticket = get_ticket_by_id(ticket_id)
    if ticket.status != "Resolved":
        raise ServiceError("Only Resolved tickets can be closed")
    ticket.status = "Closed"
    has_note = _has_text(close_note)
    if has_note:
        ticket.close_note = close_note

    closed_by = _s(admin.full_name) if admin is not None else "admin"
    save_history(ticket, "Closed", "Closed by " + closed_by + (" — " + close_note if has_note else ""))

    email_service.send_email(
        ticket.user.email,
        "Ticket Closed — #" + str(ticket.id),
        "Dear " + ticket.user.full_name + ",\n\n"
        "Your ticket has been officially closed.\n\n"
        "Ticket ID: #" + str(ticket.id) + "\n"
        "Subject: " + ticket.subject + "\n"
        "Status: Closed\n"
        + ("Note: " + close_note + "\n" if has_note else "")
        + "\nThank you for using Sri Lanka Customs ICT Support Portal.\n\n" + SIGNATURE,
    )

    ticket.save()
    return ticket


# ---------------------------------------------------------------------------
# Attachments: each one saves the file and stores its name on the ticket
# ---------------------------------------------------------------------------
def upload_file(ticket_id, uploaded_file, field_name):
    """field_name is the ticket column to fill, e.g. "attachment_path"."""
    ticket = get_ticket_by_id(ticket_id)
    setattr(ticket, field_name, file_service.save_file(uploaded_file))
    ticket.save()
    return ticket


# ---------------------------------------------------------------------------
# Knowledge base: search past solved tickets
# ---------------------------------------------------------------------------
STANDARD_CATEGORIES = [
    "Hardware Issue", "Software Issue", "Printer Issue", "Network Issue",
    "Internet Issue", "Email Issue", "ASYCUDA World", "Website Issue",
    "Server Issue", "Security Incident", "User Account Request",
]


def search_knowledge_base(search, category):
    results = []
    needle = search.lower() if search else None
    for ticket in get_all_tickets():
        if ticket.status not in ("Resolved", "Closed"):
            continue
        if not ticket.resolution_note:
            continue
        if category and category != "All":
            if category == "Other":
                if ticket.category is None or ticket.category in STANDARD_CATEGORIES:
                    continue
            elif category != ticket.category:
                continue
        if needle:
            fields = (ticket.subject, ticket.description, ticket.resolution_note, ticket.category)
            if not any(f is not None and needle in f.lower() for f in fields):
                continue
        results.append(ticket)
    return results
