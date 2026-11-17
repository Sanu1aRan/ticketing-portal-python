"""
/api/users/...   (UserController.java)   Admin only.

List users, add a user, activate / deactivate, send a password reset link.
"""

import secrets

from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models import User
from ..security import ServiceError, hash_password
from ..serializers import user_json
from ..services import auth_service, email_service, file_service
from ..services.auth_service import EMAIL_PATTERN, is_blank
from .common import body_param, uploaded_file, validate_admin

ALLOWED_ROLES = {"client", "officer", "admin"}
SIGNATURE = "Sri Lanka Customs ICT Directorate"


@api_view(["GET", "POST"])
def users(request):
    if request.method == "POST":
        return add_user(request)
    return get_all_users(request)


def get_all_users(request):
    validate_admin(request.user)
    all_users = User.objects.order_by("-created_at", "-id")
    return Response([user_json(u) for u in all_users])


def add_user(request):
    validate_admin(request.user)

    full_name = body_param(request, "fullName")
    email = body_param(request, "email")
    company = body_param(request, "company")
    role = body_param(request, "role")

    if is_blank(full_name) or is_blank(email) or is_blank(company) or is_blank(role):
        raise ServiceError("All fields are required")
    email = email.strip()
    role = role.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        raise ServiceError("Invalid email address")
    if role not in ALLOWED_ROLES:
        raise ServiceError("Invalid role")
    if len(full_name) > 100 or len(company) > 100 or len(email) > 150:
        raise ServiceError("Input is too long")
    if User.objects.filter(email=email).exists():
        raise ServiceError("Email already registered")

    # Random password nobody knows; the user sets their own through the emailed link
    unusable_password = secrets.token_urlsafe(32)
    user = User.objects.create(
        full_name=full_name.strip(),
        email=email,
        password=hash_password(unusable_password),
        company=company.strip(),
        role=role,
        active=True,
    )

    auth_service.send_password_link(
        user,
        "Welcome to Sri Lanka Customs ICT Portal",
        "Your account has been created.\n\nEmail: " + user.email,
        24 * 60,
    )
    return Response({"message": "User created successfully"}, status=201)


@api_view(["PUT"])
def reset_password(request, user_id):
    """Sends the user a link. It does not change the password itself."""
    validate_admin(request.user)
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        raise ServiceError("User not found")
    if not user.active:
        raise ServiceError("Cannot reset the password of a deactivated user")

    auth_service.send_password_link(
        user,
        "Password Reset — Sri Lanka Customs ICT Portal",
        "Your administrator has requested a password reset for your account.",
        60,
    )
    return Response({"message": "Reset link sent to the user's email"})


@api_view(["PUT"])
def toggle_user(request, user_id):
    """Switch a user between active and deactivated."""
    admin = request.user
    validate_admin(admin)
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        raise ServiceError("User not found")
    if user.email.lower() == admin.email.lower():
        raise ServiceError("You cannot deactivate your own account")

    user.active = not user.active

    reason = body_param(request, "reason")
    has_reason = reason is not None and reason.strip() != ""

    if not user.active:
        if has_reason:
            user.deactivate_reason = reason.strip()
    else:
        user.deactivate_reason = None
        user.deactivate_attachment_path = None

    # Save first, so a mail problem cannot undo the change
    user.save()

    if not user.active:
        email_service.send_email(
            user.email,
            "Account Deactivated — Sri Lanka Customs ICT Portal",
            "Dear " + user.full_name + ",\n\n"
            "Your account has been deactivated.\n"
            + ("Reason: " + reason.strip() + "\n" if has_reason else "")
            + "\nPlease contact the ICT Directorate for further assistance.\n\n" + SIGNATURE,
        )
    else:
        email_service.send_email(
            user.email,
            "Account Activated — Sri Lanka Customs ICT Portal",
            "Dear " + user.full_name + ",\n\n"
            "Your account has been reactivated.\n\n"
            "You can now login to the portal.\n\n" + SIGNATURE,
        )

    return Response({"message": "User activated" if user.active else "User deactivated"})


@api_view(["POST"])
def upload_deactivate_attachment(request, user_id):
    validate_admin(request.user)
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        raise ServiceError("User not found")
    user.deactivate_attachment_path = file_service.save_file(uploaded_file(request))
    user.save()
    return Response({"message": "Attachment uploaded successfully"})
