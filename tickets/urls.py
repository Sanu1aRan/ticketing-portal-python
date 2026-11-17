"""
Every API address in one place (40 endpoints, same addresses as the Java API).
All of them start with /api/ (see config/urls.py).

Fixed words like "stats" must come BEFORE "<int:ticket_id>", otherwise Django
would try to read "stats" as a ticket number.
"""

from django.urls import path

from .views import auth_views, ticket_views, unit_views, user_views

urlpatterns = [
    # --- Auth (login, register, forgot-password, reset-password are public) ---
    path("auth/login", auth_views.login),
    path("auth/register", auth_views.register),
    path("auth/change-password", auth_views.change_password),
    path("auth/forgot-password", auth_views.forgot_password),
    path("auth/reset-password", auth_views.reset_password),

    # --- Tickets: any logged-in user ---
    path("tickets", ticket_views.tickets),                                   # GET, POST
    path("tickets/stats", ticket_views.get_ticket_stats),
    path("tickets/recent", ticket_views.get_recent_tickets),
    path("tickets/knowledge-base", ticket_views.search_knowledge_base),
    path("tickets/uploads/<str:filename>", ticket_views.serve_file),

    # --- Tickets: officer ---
    path("tickets/officer/unit", ticket_views.get_unit_tickets),
    path("tickets/officer/open", ticket_views.get_open_unassigned_tickets),
    path("tickets/officer/<int:ticket_id>/pickup", ticket_views.pickup_ticket),
    path("tickets/officer/<int:ticket_id>/return", ticket_views.return_ticket),

    # --- Tickets: admin ---
    path("tickets/admin/all", ticket_views.get_all_tickets),
    path("tickets/admin/<int:ticket_id>/status", ticket_views.update_ticket_status),
    path("tickets/admin/<int:ticket_id>/assign", ticket_views.assign_ticket),
    path("tickets/admin/<int:ticket_id>/reject", ticket_views.reject_ticket),
    path("tickets/admin/<int:ticket_id>/close", ticket_views.close_ticket),

    # --- One ticket ---
    path("tickets/<int:ticket_id>", ticket_views.ticket_detail),             # GET, PUT, DELETE
    path("tickets/<int:ticket_id>/history", ticket_views.get_ticket_history),
    path("tickets/<int:ticket_id>/classify", ticket_views.classify_ticket),
    path("tickets/<int:ticket_id>/comments", ticket_views.comments),         # GET, POST
    path("tickets/<int:ticket_id>/attachment", ticket_views.upload_attachment),
    path("tickets/<int:ticket_id>/resolution-attachment", ticket_views.upload_resolution_attachment),
    path("tickets/<int:ticket_id>/return-attachment", ticket_views.upload_return_attachment),
    path("tickets/<int:ticket_id>/cancel-attachment", ticket_views.upload_cancel_attachment),
    path("tickets/<int:ticket_id>/close-attachment", ticket_views.upload_close_attachment),

    # --- Users (admin) ---
    path("users", user_views.users),                                         # GET, POST
    path("users/<int:user_id>/toggle", user_views.toggle_user),
    path("users/<int:user_id>/reset-password", user_views.reset_password),
    path("users/<int:user_id>/deactivate-attachment", user_views.upload_deactivate_attachment),

    # --- Units ---
    path("units", unit_views.units),                                         # GET, POST
    path("units/<int:unit_id>", unit_views.delete_unit),
]
