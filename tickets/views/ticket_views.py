"""
/api/tickets/...   (TicketController.java)

Each function is one endpoint. The pattern is always the same:
  1. check the caller is allowed (role / ownership)
  2. ask ticket_service to do the work
  3. return JSON
"""

import os

from django.http import FileResponse, HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models import TicketComment, User
from ..security import ServiceError
from ..serializers import comment_json, history_json, ticket_json, tickets_json
from ..services import email_service, file_service, ticket_service
from .common import (
    body_param,
    uploaded_file,
    validate_admin_or_officer,
    validate_role,
    validate_ticket_access,
    validate_ticket_owner,
)

SIGNATURE = "Sri Lanka Customs ICT Directorate"


# ---------------------------------------------------------------------------
# /api/tickets            GET = my tickets, POST = create a ticket
# ---------------------------------------------------------------------------
@api_view(["GET", "POST"])
def tickets(request):
    if request.method == "POST":
        return create_ticket(request)
    return get_tickets(request)


def create_ticket(request):
    ticket = ticket_service.create_ticket(
        body_param(request, "subject"), body_param(request, "description"), request.user
    )
    return Response({"message": "Ticket created successfully", "ticketId": ticket.id}, status=201)


def get_tickets(request):
    return Response(tickets_json(ticket_service.get_tickets_by_user(request.user)))


@api_view(["GET"])
def get_ticket_stats(request):
    return Response(ticket_service.get_ticket_stats(request.user))


@api_view(["GET"])
def get_recent_tickets(request):
    return Response(tickets_json(ticket_service.get_recent_tickets(request.user)))


# ---------------------------------------------------------------------------
# /api/tickets/{id}       GET = one ticket, PUT = edit, DELETE = delete
# ---------------------------------------------------------------------------
@api_view(["GET", "PUT", "DELETE"])
def ticket_detail(request, ticket_id):
    if request.method == "PUT":
        return update_ticket(request, ticket_id)
    if request.method == "DELETE":
        return delete_ticket(request, ticket_id)
    return get_ticket(request, ticket_id)


def get_ticket(request, ticket_id):
    user = request.user
    ticket = ticket_service.get_ticket_by_id(ticket_id)
    if user.role == "client" and ticket.user.email != user.email:
        return Response({"message": "Access denied"}, status=403)
    return Response(ticket_json(ticket))


def update_ticket(request, ticket_id):
    validate_ticket_owner(request.user, ticket_id)
    ticket = ticket_service.update_ticket(
        ticket_id, body_param(request, "subject"), body_param(request, "description")
    )
    return Response(ticket_json(ticket))


def delete_ticket(request, ticket_id):
    validate_ticket_owner(request.user, ticket_id)
    ticket_service.delete_ticket(ticket_id)
    return Response({"message": "Ticket deleted successfully"})


@api_view(["GET"])
def get_ticket_history(request, ticket_id):
    ticket = validate_ticket_access(request.user, ticket_id)
    ticket_data = ticket_json(ticket)
    history = ticket_service.get_ticket_history(ticket)
    return Response([history_json(item, ticket_data) for item in history])


# ---------------------------------------------------------------------------
# Officer endpoints
# ---------------------------------------------------------------------------
@api_view(["GET"])
def get_unit_tickets(request):
    validate_role(request.user, "officer")
    return Response(tickets_json(ticket_service.get_unit_tickets()))


@api_view(["GET"])
def get_open_unassigned_tickets(request):
    validate_role(request.user, "officer")
    return Response(tickets_json(ticket_service.get_open_unassigned_tickets()))


@api_view(["PUT"])
def pickup_ticket(request, ticket_id):
    validate_role(request.user, "officer")
    ticket = ticket_service.assign_ticket(ticket_id, request.user.email, True)
    return Response(ticket_json(ticket))


@api_view(["PUT"])
def return_ticket(request, ticket_id):
    validate_role(request.user, "officer")
    # Only a ticket that is being worked on can be returned
    current = ticket_service.get_ticket_by_id(ticket_id)
    if current.status != "In Progress":
        raise ServiceError("Only In Progress tickets can be returned")
    ticket = ticket_service.return_ticket(ticket_id, body_param(request, "reason"), request.user)
    return Response(ticket_json(ticket))


@api_view(["PUT"])
def classify_ticket(request, ticket_id):
    validate_admin_or_officer(request.user)
    ticket = ticket_service.classify_ticket(
        ticket_id, body_param(request, "category"), body_param(request, "priority"), request.user
    )
    return Response(ticket_json(ticket))


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------
@api_view(["GET"])
def get_all_tickets(request):
    validate_role(request.user, "admin")
    return Response(tickets_json(ticket_service.get_all_tickets()))


@api_view(["PUT"])
def update_ticket_status(request, ticket_id):
    """Resolve a ticket. Admin or officer."""
    validate_admin_or_officer(request.user)
    status = body_param(request, "status")
    # This endpoint is only for resolving a ticket that is being worked on
    if status != "Resolved":
        raise ServiceError("Only the Resolved status can be set here")
    current = ticket_service.get_ticket_by_id(ticket_id)
    if current.status != "In Progress":
        raise ServiceError("Only In Progress tickets can be resolved")
    ticket = ticket_service.update_ticket_status(
        ticket_id, status, body_param(request, "resolutionNote"), request.user
    )
    return Response(ticket_json(ticket))


@api_view(["PUT"])
def assign_ticket(request, ticket_id):
    validate_role(request.user, "admin")
    ticket = ticket_service.assign_ticket(ticket_id, body_param(request, "assignedTo"), False)
    return Response(ticket_json(ticket))


@api_view(["PUT"])
def reject_ticket(request, ticket_id):
    validate_role(request.user, "admin")
    ticket = ticket_service.reject_ticket(ticket_id, body_param(request, "reason"), request.user)
    return Response(ticket_json(ticket))


@api_view(["PUT"])
def close_ticket(request, ticket_id):
    validate_role(request.user, "admin")
    ticket = ticket_service.close_ticket(ticket_id, body_param(request, "closeNote"), request.user)
    return Response(ticket_json(ticket))


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
@api_view(["GET"])
def serve_file(request, filename):
    """Download / view an uploaded file. A valid token is required."""
    full_path = file_service.resolve_upload(filename)
    if full_path is None:
        return HttpResponse(status=403)  # tried to leave the uploads folder
    if not os.path.isfile(full_path):
        return HttpResponse(status=404)
    response = FileResponse(open(full_path, "rb"), content_type=file_service.content_type_for(filename))
    response["Content-Disposition"] = 'inline; filename="' + filename + '"'
    return response


def _upload(request, ticket_id, field_name):
    ticket = ticket_service.upload_file(ticket_id, uploaded_file(request), field_name)
    return Response(ticket_json(ticket))


@api_view(["POST"])
def upload_attachment(request, ticket_id):
    validate_ticket_owner(request.user, ticket_id)
    return _upload(request, ticket_id, "attachment_path")


@api_view(["POST"])
def upload_resolution_attachment(request, ticket_id):
    validate_role(request.user, "officer")
    return _upload(request, ticket_id, "resolution_attachment_path")


@api_view(["POST"])
def upload_return_attachment(request, ticket_id):
    validate_role(request.user, "officer")
    return _upload(request, ticket_id, "return_attachment_path")


@api_view(["POST"])
def upload_cancel_attachment(request, ticket_id):
    validate_role(request.user, "admin")
    return _upload(request, ticket_id, "cancel_attachment_path")


@api_view(["POST"])
def upload_close_attachment(request, ticket_id):
    validate_role(request.user, "admin")
    return _upload(request, ticket_id, "close_attachment_path")


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------
@api_view(["GET"])
def search_knowledge_base(request):
    validate_admin_or_officer(request.user)
    results = ticket_service.search_knowledge_base(
        request.query_params.get("search"), request.query_params.get("category")
    )
    return Response(tickets_json(results))


# ---------------------------------------------------------------------------
# Comments: /api/tickets/{id}/comments   GET = list, POST = add
# ---------------------------------------------------------------------------
@api_view(["GET", "POST"])
def comments(request, ticket_id):
    if request.method == "POST":
        return add_comment(request, ticket_id)
    return get_comments(request, ticket_id)


def get_comments(request, ticket_id):
    ticket = validate_ticket_access(request.user, ticket_id)
    rows = (
        TicketComment.objects.select_related("user")
        .filter(ticket=ticket)
        .order_by("created_at", "id")
    )
    return Response([comment_json(c, c.user) for c in rows])


def add_comment(request, ticket_id):
    user = request.user
    ticket = validate_ticket_access(user, ticket_id)

    # Comments are for client-officer conversation; admin is read-only
    if user.role == "admin":
        raise ServiceError("Admins cannot comment")
    # No comments on finished tickets
    if ticket.status in ("Closed", "Cancelled"):
        raise ServiceError("Comments are closed for this ticket")
    message = body_param(request, "message")
    if message is None or message.strip() == "":
        raise ServiceError("Comment cannot be empty")

    comment = TicketComment.objects.create(ticket=ticket, user=user, message=message)

    if user.role == "client":
        # Client wrote -> tell the officer working on the ticket (if any)
        officer = None
        if ticket.assigned_to is not None:
            officer = User.objects.filter(email=ticket.assigned_to).first()
        if officer is not None:
            email_service.send_email(
                officer.email,
                "New Comment on Ticket #" + str(ticket.id),
                "Dear " + officer.full_name + ",\n\n"
                + user.full_name + " commented on ticket #" + str(ticket.id) + ":\n\n"
                '"' + message + '"\n\n'
                "Subject: " + ticket.subject + "\n\n" + SIGNATURE,
            )
    else:
        # Officer wrote -> tell the client
        email_service.send_email(
            ticket.user.email,
            "New Comment on Ticket #" + str(ticket.id),
            "Dear " + ticket.user.full_name + ",\n\n"
            + user.full_name + " commented on your ticket #" + str(ticket.id) + ":\n\n"
            '"' + message + '"\n\n'
            "Subject: " + ticket.subject + "\n\n" + SIGNATURE,
        )

    return Response(comment_json(comment, user))
