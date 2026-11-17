"""
Turns database rows into the JSON the React app expects.

React was written against the Java API, which used camelCase names
(fullName, createdAt, assignedToUnit ...). Python uses snake_case, so these
functions do the renaming. The field lists match exactly what Java returned.
"""


def _dt(value):
    # Java sent LocalDateTime as "2026-11-17T11:44:05.123456" (no time zone)
    return value.isoformat() if value is not None else None


def user_json(user):
    # password and reset-token fields are never returned (Java: @JsonIgnore)
    return {
        "id": user.id,
        "fullName": user.full_name,
        "email": user.email,
        "company": user.company,
        "role": user.role,
        "active": bool(user.active),
        "deactivateReason": user.deactivate_reason,
        "deactivateAttachmentPath": user.deactivate_attachment_path,
    }


def unit_json(unit):
    return {"id": unit.id, "name": unit.name, "createdAt": _dt(unit.created_at)}


def ticket_json(ticket):
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "category": ticket.category,
        "priority": ticket.priority,
        "description": ticket.description,
        "status": ticket.status,
        "user": user_json(ticket.user),
        "createdAt": _dt(ticket.created_at),
        "assignedTo": ticket.assigned_to,
        "assignedToName": ticket.assigned_to_name,
        "assignedToUnit": ticket.assigned_to_unit,
        "resolvedBy": ticket.resolved_by,
        "resolutionNote": ticket.resolution_note,
        "attachmentPath": ticket.attachment_path,
        "resolutionAttachmentPath": ticket.resolution_attachment_path,
        "returnReason": ticket.return_reason,
        "returnAttachmentPath": ticket.return_attachment_path,
        "cancelReason": ticket.cancel_reason,
        "cancelAttachmentPath": ticket.cancel_attachment_path,
        "closeNote": ticket.close_note,
        "closeAttachmentPath": ticket.close_attachment_path,
    }


def tickets_json(tickets):
    return [ticket_json(t) for t in tickets]


def history_json(item, ticket_data):
    return {
        "id": item.id,
        "ticket": ticket_data,
        "status": item.status,
        "note": item.note,
        "changedAt": _dt(item.changed_at),
    }


def comment_json(comment, user):
    return {
        "id": comment.id,
        "message": comment.message,
        "createdAt": _dt(comment.created_at),
        "userName": user.full_name,
        "userRole": user.role,
        "userCompany": user.company,
    }
