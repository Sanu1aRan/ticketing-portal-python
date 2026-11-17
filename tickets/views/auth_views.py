"""
/api/auth/...   (AuthController.java)

login, register, forgot-password and reset-password are the 4 PUBLIC
endpoints: no token needed. change-password needs a logged-in user.
"""

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..services import auth_service
from .common import body_param


@api_view(["POST"])
@authentication_classes([])  # public: an old token in the browser cannot break it
@permission_classes([AllowAny])
def login(request):
    token, user = auth_service.login(body_param(request, "email"), body_param(request, "password"))
    return Response({
        "message": "Login successful",
        "token": token,
        "user": {
            "id": user.id,
            "fullName": user.full_name,
            "email": user.email,
            "company": user.company,
            "role": user.role,
        },
    })


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    message = auth_service.register(
        body_param(request, "fullName"),
        body_param(request, "email"),
        body_param(request, "password"),
        body_param(request, "company"),
    )
    return Response({"message": message}, status=201)


@api_view(["PUT"])
def change_password(request):
    auth_service.change_password(
        request.user,
        body_param(request, "currentPassword"),
        body_param(request, "newPassword"),
    )
    return Response({"message": "Password changed successfully"})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def forgot_password(request):
    auth_service.forgot_password(body_param(request, "email"))
    # Same answer whether or not the email exists, so nobody can test for accounts
    return Response({"message": "If the email is registered, a reset link has been sent"})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def reset_password(request):
    # Public: the secret token in the emailed link is the proof of identity
    auth_service.reset_password(body_param(request, "token"), body_param(request, "newPassword"))
    return Response({"message": "Password has been reset. You can now log in."})
