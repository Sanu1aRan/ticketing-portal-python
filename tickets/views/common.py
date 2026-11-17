"""
Small helpers shared by all the view files: reading the request body and the
"is this person allowed?" checks the Java controllers had as private methods.
"""

from django.conf import settings
from rest_framework.exceptions import ParseError

from ..security import ServiceError
from ..services import ticket_service


def body_param(request, key):
    """
    Reads one value from the JSON body, as text (or None if it is missing).
    Java read the body as Map<String, String>, so numbers also arrive as text.
    """
    data = request.data
    if data is None:
        return None
    if not hasattr(data, "get"):
        raise ParseError("Invalid request body")
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        raise ParseError("Invalid request body")
    return str(value)


def uploaded_file(request):
    """Returns the uploaded "file" part, enforcing the 10MB limit."""
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > settings.MAX_UPLOAD_BYTES:
        raise ServiceError("File is too large. Maximum size is 10MB", status=413)
    file = request.FILES.get("file")
    if file is None:
        raise ServiceError("File is required")
    if file.size > settings.MAX_UPLOAD_BYTES:
        raise ServiceError("File is too large. Maximum size is 10MB", status=413)
    return file


# ---------------------------------------------------------------------------
# Permission checks
# ---------------------------------------------------------------------------
def validate_role(user, required_role):
    if user.role != required_role:
        raise ServiceError("Unauthorized access")


def validate_admin(user):
    validate_role(user, "admin")


def validate_admin_or_officer(user):
    if user.role not in ("admin", "officer"):
        raise ServiceError("Unauthorized access")


def validate_ticket_owner(user, ticket_id):
    """Only the client who created the ticket may edit, delete or attach files to it."""
    ticket = ticket_service.get_ticket_by_id(ticket_id)
    if ticket.user.email != user.email:
        raise ServiceError("Access denied")
    return ticket


def validate_ticket_access(user, ticket_id):
    """Clients may only open their own tickets; officers and admins may open any."""
    ticket = ticket_service.get_ticket_by_id(ticket_id)
    if user.role == "client" and ticket.user.email != user.email:
        raise ServiceError("Access denied")
    return ticket
