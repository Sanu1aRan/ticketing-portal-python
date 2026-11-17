"""
Automated tests: they call every API endpoint and check the answers match
what the Java backend returned.

Run them with:   python manage.py test
"""

import re
import shutil
import tempfile
import time
from datetime import timedelta

import jwt
from django.conf import settings
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Ticket, TicketComment, TicketHistory, Unit, User
from .security import check_password, generate_token, hash_password
from .services import auth_service

UPLOADS = tempfile.mkdtemp(prefix="ticket-test-uploads-")

TICKET_KEYS = {
    "id", "subject", "category", "priority", "description", "status", "user", "createdAt",
    "assignedTo", "assignedToName", "assignedToUnit", "resolvedBy", "resolutionNote",
    "attachmentPath", "resolutionAttachmentPath", "returnReason", "returnAttachmentPath",
    "cancelReason", "cancelAttachmentPath", "closeNote", "closeAttachmentPath",
}
USER_KEYS = {
    "id", "fullName", "email", "company", "role", "active",
    "deactivateReason", "deactivateAttachmentPath",
}


def make_user(email, role="client", name=None, company="Acme Shipping", password="secret123", active=True):
    return User.objects.create(
        full_name=name or email.split("@")[0].title(),
        email=email,
        password=hash_password(password),
        company=company,
        role=role,
        active=active,
    )


def png(name="shot.png", size=20):
    return SimpleUploadedFile(name, b"x" * size, content_type="image/png")


@override_settings(EMAIL_ASYNC=False, UPLOAD_DIR=UPLOADS, FRONTEND_URL="http://front.test")
class ApiTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(UPLOADS, ignore_errors=True)

    def setUp(self):
        auth_service.reset_memory()
        self.client_user = make_user("client@test.lk", "client", "Nimal Perera")
        self.other_client = make_user("other@test.lk", "client", "Other Client")
        self.officer = make_user("officer@test.lk", "officer", "Kamal Silva", "AsyHub")
        self.officer2 = make_user("officer2@test.lk", "officer", "Sunil Dias", "Functional")
        self.admin = make_user("admin@test.lk", "admin", "Admin Boss", "Administration")
        self.admin2 = make_user("admin2@test.lk", "admin", "Second Admin", "Administration")

    def api(self, user=None, token=None):
        client = APIClient()
        if user is not None:
            token = generate_token(user.email)
        if token is not None:
            client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
        return client

    def new_ticket(self, user=None, subject="Printer broken", description="It does not print"):
        user = user or self.client_user
        r = self.api(user).post("/api/tickets", {"subject": subject, "description": description}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        mail.outbox.clear()
        return r.json()["ticketId"]

    def to(self):
        return sorted(m.to[0] for m in mail.outbox)

    def assertMessage(self, response, status, message):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json(), {"message": message})


# ---------------------------------------------------------------------------
class SecurityTests(ApiTestCase):
    def test_no_token_is_403_with_empty_body(self):
        for method, url in [("get", "/api/tickets"), ("get", "/api/users"), ("get", "/api/units"),
                            ("put", "/api/auth/change-password"), ("get", "/api/tickets/uploads/a.png")]:
            r = getattr(self.api(), method)(url)
            self.assertEqual(r.status_code, 403, url)
            self.assertEqual(r.content, b"", url)

    def test_bad_token_is_401(self):
        self.assertMessage(self.api(token="not-a-token").get("/api/tickets"), 401, "Invalid token")

    def test_token_signed_with_other_secret_is_401(self):
        forged = jwt.encode({"sub": "admin@test.lk"}, "another-secret-another-secret-123456", algorithm="HS256")
        self.assertMessage(self.api(token=forged).get("/api/users"), 401, "Invalid token")

    def test_expired_token_is_401(self):
        with override_settings(JWT_EXPIRATION_HOURS=-1):
            token = generate_token(self.admin.email)
        self.assertMessage(self.api(token=token).get("/api/users"), 401, "Invalid token")

    def test_deactivated_or_deleted_user_is_401(self):
        token = generate_token(self.client_user.email)
        self.client_user.active = False
        self.client_user.save()
        self.assertMessage(self.api(token=token).get("/api/tickets"), 401, "Account deactivated or not found")
        ghost = generate_token("ghost@test.lk")
        self.assertMessage(self.api(token=ghost).get("/api/tickets"), 401, "Account deactivated or not found")

    def test_public_endpoints_ignore_a_stale_token(self):
        r = self.api(token="stale").post("/api/auth/login", {"email": "client@test.lk", "password": "secret123"}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_token_lifetime_is_seven_days_by_default(self):
        payload = jwt.decode(generate_token("a@b.lk"), settings.JWT_SECRET, algorithms=["HS256"])
        self.assertEqual(payload["exp"] - payload["iat"], 7 * 24 * 3600)
        self.assertEqual(payload["sub"], "a@b.lk")

    def test_cors_preflight(self):
        r = self.api().options("/api/tickets", HTTP_ORIGIN="http://localhost:5173",
                               HTTP_ACCESS_CONTROL_REQUEST_METHOD="PUT",
                               HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertIn("authorization", r["Access-Control-Allow-Headers"])
        r = self.api().get("/api/tickets", HTTP_ORIGIN="http://localhost:5173")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r["Access-Control-Allow-Origin"], "http://localhost:5173")
        r = self.api().get("/api/tickets", HTTP_ORIGIN="http://evil.example")
        self.assertNotIn("Access-Control-Allow-Origin", r)


# ---------------------------------------------------------------------------
class AuthTests(ApiTestCase):
    def login(self, email, password):
        return self.api().post("/api/auth/login", {"email": email, "password": password}, format="json")

    def test_login_success_shape(self):
        r = self.login("client@test.lk", "secret123")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), {"message", "token", "user"})
        self.assertEqual(body["message"], "Login successful")
        self.assertEqual(body["user"], {
            "id": self.client_user.id, "fullName": "Nimal Perera", "email": "client@test.lk",
            "company": "Acme Shipping", "role": "client",
        })
        self.assertEqual(self.api(token=body["token"]).get("/api/tickets").status_code, 200)

    def test_login_trims_email(self):
        self.assertEqual(self.login("  client@test.lk ", "secret123").status_code, 200)

    def test_login_failures(self):
        self.assertMessage(self.login("client@test.lk", "wrong"), 400, "Invalid email or password")
        self.assertMessage(self.login("nobody@test.lk", "secret123"), 400, "Invalid email or password")
        self.assertMessage(self.login("client@test.lk", ""), 400, "Invalid email or password")
        self.assertMessage(self.api().post("/api/auth/login", {}, format="json"), 400, "Invalid email or password")

    def test_deactivated_login(self):
        make_user("off@test.lk", active=False)
        self.assertMessage(self.login("off@test.lk", "secret123"), 400,
                           "Your account has been deactivated. Please contact admin.")

    def test_lockout_after_five_failures(self):
        for _ in range(5):
            self.assertMessage(self.login("client@test.lk", "wrong"), 400, "Invalid email or password")
        # even the right password is refused while locked
        self.assertMessage(self.login("client@test.lk", "secret123"), 400,
                           "Too many failed attempts. Try again in 15 minute(s).")
        self.assertMessage(self.login("CLIENT@test.lk", "secret123"), 400,
                           "Too many failed attempts. Try again in 15 minute(s).")
        # other accounts are not affected
        self.assertEqual(self.login("other@test.lk", "secret123").status_code, 200)

    def test_success_clears_failure_count(self):
        for _ in range(4):
            self.login("client@test.lk", "wrong")
        self.assertEqual(self.login("client@test.lk", "secret123").status_code, 200)
        for _ in range(4):
            self.login("client@test.lk", "wrong")
        self.assertEqual(self.login("client@test.lk", "secret123").status_code, 200)

    def test_lock_expires(self):
        for _ in range(5):
            self.login("client@test.lk", "wrong")
        auth_service._login_attempts["client@test.lk"]["locked_until"] = int(time.time() * 1000) - 1
        self.assertEqual(self.login("client@test.lk", "secret123").status_code, 200)

    def test_register(self):
        data = {"fullName": " New Person ", "email": " new@test.lk ", "password": "abcdef", "company": " NewCo "}
        self.assertMessage(self.api().post("/api/auth/register", data, format="json"), 201, "Account created successfully")
        user = User.objects.get(email="new@test.lk")
        self.assertEqual((user.full_name, user.company, user.role, user.active), ("New Person", "NewCo", "client", True))
        self.assertTrue(user.password.startswith("$2b$10$"))
        self.assertIsNotNone(user.created_at)
        self.assertEqual(self.login("new@test.lk", "abcdef").status_code, 200)

    def test_register_validation(self):
        post = lambda d: self.api().post("/api/auth/register", d, format="json")
        ok = {"fullName": "A B", "email": "x@test.lk", "password": "abcdef", "company": "Co"}
        self.assertMessage(post({**ok, "company": "  "}), 400, "All fields are required")
        self.assertMessage(post({k: v for k, v in ok.items() if k != "email"}), 400, "All fields are required")
        self.assertMessage(post({**ok, "email": "not-an-email"}), 400, "Invalid email address")
        self.assertMessage(post({**ok, "email": "a b@test.lk"}), 400, "Invalid email address")
        self.assertMessage(post({**ok, "password": "12345"}), 400, "Password must be at least 6 characters")
        self.assertMessage(post({**ok, "fullName": "x" * 101}), 400, "Input is too long")
        self.assertMessage(post({**ok, "email": "client@test.lk"}), 400, "Email already registered")

    def test_change_password(self):
        api = self.api(self.client_user)
        put = lambda cur, new: api.put("/api/auth/change-password", {"currentPassword": cur, "newPassword": new}, format="json")
        self.assertMessage(put("wrong", "newpass1"), 400, "Current password is incorrect")
        self.assertMessage(put("secret123", "123"), 400, "New password must be at least 6 characters")
        self.assertMessage(put("secret123", "secret123"), 400, "New password must be different from your current password")
        self.assertMessage(put("secret123", "newpass1"), 200, "Password changed successfully")
        self.assertEqual(self.login("client@test.lk", "newpass1").status_code, 200)
        self.assertMessage(self.login("client@test.lk", "secret123"), 400, "Invalid email or password")

    def test_forgot_and_reset_password(self):
        generic = "If the email is registered, a reset link has been sent"
        forgot = lambda e: self.api().post("/api/auth/forgot-password", {"email": e}, format="json")
        self.assertMessage(forgot("nobody@test.lk"), 200, generic)
        self.assertEqual(len(mail.outbox), 0)
        self.assertMessage(forgot("client@test.lk"), 200, generic)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.subject, "Password Reset — Sri Lanka Customs ICT Portal")
        self.assertEqual(email.to, ["client@test.lk"])
        self.assertIn("Dear Nimal Perera,", email.body)
        self.assertIn("expires in 30 minutes", email.body)
        token = re.search(r"http://front\.test/reset-password\?token=(\S+)", email.body).group(1)
        self.assertEqual(len(token), 43)
        # only a hash is stored
        self.client_user.refresh_from_db()
        self.assertNotEqual(self.client_user.reset_token_hash, token)
        self.assertEqual(len(self.client_user.reset_token_hash), 64)

        # cooldown: a second request within 2 minutes sends nothing
        self.assertMessage(forgot("client@test.lk"), 200, generic)
        self.assertEqual(len(mail.outbox), 1)

        reset = lambda t, p: self.api().post("/api/auth/reset-password", {"token": t, "newPassword": p}, format="json")
        self.assertMessage(reset("", "newpass1"), 400, "Invalid or expired reset link")
        self.assertMessage(reset("wrong-token", "newpass1"), 400, "Invalid or expired reset link")
        self.assertMessage(reset(token, "123"), 400, "New password must be at least 6 characters")
        self.assertMessage(reset(token, "secret123"), 400, "New password must be different from your current password")
        self.assertMessage(reset(token, "newpass1"), 200, "Password has been reset. You can now log in.")
        self.assertMessage(reset(token, "another1"), 400, "Invalid or expired reset link")  # one-time
        self.assertEqual(self.login("client@test.lk", "newpass1").status_code, 200)

    def test_reset_link_expires_and_clears_lockout(self):
        self.api().post("/api/auth/forgot-password", {"email": "client@test.lk"}, format="json")
        token = re.search(r"token=(\S+)", mail.outbox[0].body).group(1)
        reset = lambda: self.api().post("/api/auth/reset-password", {"token": token, "newPassword": "newpass1"}, format="json")
        User.objects.filter(pk=self.client_user.pk).update(reset_token_expiry=timezone.now() - timedelta(minutes=1))
        self.assertMessage(reset(), 400, "Invalid or expired reset link")
        User.objects.filter(pk=self.client_user.pk).update(reset_token_expiry=timezone.now() + timedelta(minutes=5))
        for _ in range(5):
            self.login("client@test.lk", "wrong")
        self.assertEqual(reset().status_code, 200)
        self.assertEqual(self.login("client@test.lk", "newpass1").status_code, 200)

    def test_forgot_password_for_deactivated_user_sends_nothing(self):
        make_user("off@test.lk", active=False)
        self.api().post("/api/auth/forgot-password", {"email": "off@test.lk"}, format="json")
        self.assertEqual(len(mail.outbox), 0)

    def test_java_bcrypt_hash_is_accepted(self):
        # "password" hashed by Spring Security (the sample hash from its own documentation)
        java_hash = "$2a$10$dXJ3SW6G7P50lGmMkkmwe.20cQQubK3.HZWzG3YB1tlRy.fqvM/BG"
        self.assertTrue(check_password("password", java_hash))
        self.assertFalse(check_password("Password", java_hash))


# ---------------------------------------------------------------------------
class ClientTicketTests(ApiTestCase):
    def test_create_ticket(self):
        r = self.api(self.client_user).post("/api/tickets", {"subject": "No internet", "description": "Since morning"}, format="json")
        self.assertEqual(r.status_code, 201)
        ticket = Ticket.objects.get()
        self.assertEqual(r.json(), {"message": "Ticket created successfully", "ticketId": ticket.id})
        self.assertEqual((ticket.status, ticket.category, ticket.priority, ticket.assigned_to), ("Open", None, None, None))
        self.assertEqual(list(ticket.history.values_list("status", "note")), [("Open", "Ticket submitted")])
        self.assertEqual(self.to(), ["admin2@test.lk", "admin@test.lk", "client@test.lk"])
        client_mail = next(m for m in mail.outbox if m.to == ["client@test.lk"])
        self.assertEqual(client_mail.subject, f"Ticket Submitted — #{ticket.id}")
        self.assertEqual(client_mail.body, (
            "Dear Nimal Perera,\n\nYour ticket has been submitted successfully.\n\n"
            f"Ticket ID: #{ticket.id}\nSubject: No internet\nStatus: Open\n\n"
            "We will get back to you shortly.\n\nSri Lanka Customs ICT Directorate"))
        admin_mail = next(m for m in mail.outbox if m.to == ["admin@test.lk"])
        self.assertEqual(admin_mail.subject, f"New Ticket Submitted — #{ticket.id}")
        self.assertIn("Client: Nimal Perera\n", admin_mail.body)

    def test_create_ticket_needs_subject_and_description(self):
        r = self.api(self.client_user).post("/api/tickets", {"subject": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_too_long_text_is_a_clean_400(self):
        api = self.api(self.client_user)
        r = api.post("/api/tickets", {"subject": "x" * 256, "description": "d"}, format="json")
        self.assertMessage(r, 400, "Subject is too long (maximum 255 characters)")
        self.assertEqual(api.post("/api/tickets", {"subject": "x" * 255, "description": "d" * 20000}, format="json").status_code, 201)
        tid = Ticket.objects.get().id
        r = api.put(f"/api/tickets/{tid}", {"subject": "y" * 300, "description": "d"}, format="json")
        self.assertMessage(r, 400, "Subject is too long (maximum 255 characters)")
        r = self.api(self.officer).put(f"/api/tickets/{tid}/classify", {"category": "c" * 256, "priority": "High"}, format="json")
        self.assertMessage(r, 400, "Category is too long (maximum 255 characters)")
        emoji = api.post("/api/tickets", {"subject": "Printer \U0001F5A8 සිංහල", "description": "தமிழ்"}, format="json")
        self.assertEqual(emoji.status_code, 201)
        self.assertEqual(Ticket.objects.get(pk=emoji.json()["ticketId"]).subject, "Printer \U0001F5A8 සිංහල")

    def test_list_stats_recent(self):
        ids = [self.new_ticket(subject=f"T{i}") for i in range(4)]
        self.new_ticket(self.other_client, "Not mine")
        Ticket.objects.filter(pk=ids[0]).update(status="In Progress")
        Ticket.objects.filter(pk=ids[1]).update(status="Resolved")
        api = self.api(self.client_user)

        listing = api.get("/api/tickets").json()
        self.assertEqual([t["id"] for t in listing], ids[::-1])  # newest first
        self.assertEqual(set(listing[0]), TICKET_KEYS)
        self.assertEqual(set(listing[0]["user"]), USER_KEYS)
        self.assertEqual(listing[0]["user"]["fullName"], "Nimal Perera")
        self.assertRegex(listing[0]["createdAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?$")

        self.assertEqual(api.get("/api/tickets/stats").json(),
                         {"total": 4, "open": 2, "inProgress": 1, "resolved": 1, "closed": 0, "cancelled": 0})
        self.assertEqual([t["id"] for t in api.get("/api/tickets/recent").json()], ids[::-1][:3])

    def test_get_ticket_access(self):
        tid = self.new_ticket()
        self.assertEqual(self.api(self.client_user).get(f"/api/tickets/{tid}").json()["subject"], "Printer broken")
        self.assertMessage(self.api(self.other_client).get(f"/api/tickets/{tid}"), 403, "Access denied")
        self.assertEqual(self.api(self.officer).get(f"/api/tickets/{tid}").status_code, 200)
        self.assertEqual(self.api(self.admin).get(f"/api/tickets/{tid}").status_code, 200)
        self.assertMessage(self.api(self.client_user).get("/api/tickets/99999"), 400, "Ticket not found")

    def test_update_ticket(self):
        tid = self.new_ticket()
        body = {"subject": "New subject", "description": "New description"}
        self.assertMessage(self.api(self.other_client).put(f"/api/tickets/{tid}", body, format="json"), 400, "Access denied")
        self.assertMessage(self.api(self.admin).put(f"/api/tickets/{tid}", body, format="json"), 400, "Access denied")
        r = self.api(self.client_user).put(f"/api/tickets/{tid}", body, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["subject"], r.json()["description"]), ("New subject", "New description"))
        Ticket.objects.filter(pk=tid).update(status="In Progress")
        self.assertMessage(self.api(self.client_user).put(f"/api/tickets/{tid}", body, format="json"), 400, "Only Open tickets can be edited")

    def test_delete_ticket_removes_comments_and_history(self):
        tid = self.new_ticket()
        self.api(self.client_user).post(f"/api/tickets/{tid}/comments", {"message": "hello"}, format="json")
        self.assertMessage(self.api(self.other_client).delete(f"/api/tickets/{tid}"), 400, "Access denied")
        self.assertMessage(self.api(self.client_user).delete(f"/api/tickets/{tid}"), 200, "Ticket deleted successfully")
        self.assertEqual((Ticket.objects.count(), TicketComment.objects.count(), TicketHistory.objects.count()), (0, 0, 0))
        self.assertMessage(self.api(self.client_user).delete(f"/api/tickets/{tid}"), 400, "Ticket not found")

    def test_history(self):
        tid = self.new_ticket()
        r = self.api(self.client_user).get(f"/api/tickets/{tid}/history")
        item = r.json()[0]
        self.assertEqual(set(item), {"id", "ticket", "status", "note", "changedAt"})
        self.assertEqual((item["status"], item["note"], item["ticket"]["id"]), ("Open", "Ticket submitted", tid))
        self.assertMessage(self.api(self.other_client).get(f"/api/tickets/{tid}/history"), 400, "Access denied")
        self.assertEqual(self.api(self.officer).get(f"/api/tickets/{tid}/history").status_code, 200)


# ---------------------------------------------------------------------------
class WorkflowTests(ApiTestCase):
    def test_role_checks_return_400_unauthorized(self):
        tid = self.new_ticket()
        client, officer, admin = self.api(self.client_user), self.api(self.officer), self.api(self.admin)
        denied = [
            client.get("/api/tickets/officer/unit"), admin.get("/api/tickets/officer/open"),
            client.put(f"/api/tickets/officer/{tid}/pickup"), admin.put(f"/api/tickets/officer/{tid}/pickup"),
            admin.put(f"/api/tickets/officer/{tid}/return", {"reason": "x"}, format="json"),
            client.put(f"/api/tickets/{tid}/classify", {"category": "x"}, format="json"),
            client.get("/api/tickets/admin/all"), officer.get("/api/tickets/admin/all"),
            client.put(f"/api/tickets/admin/{tid}/status", {"status": "Resolved"}, format="json"),
            officer.put(f"/api/tickets/admin/{tid}/assign", {"assignedTo": "officer@test.lk"}, format="json"),
            officer.put(f"/api/tickets/admin/{tid}/reject", {"reason": "x"}, format="json"),
            officer.put(f"/api/tickets/admin/{tid}/close", {}, format="json"),
            client.get("/api/tickets/knowledge-base"),
            client.get("/api/users"), officer.post("/api/users", {}, format="json"),
            officer.post("/api/units", {"name": "X"}, format="json"), client.delete("/api/units/1"),
        ]
        for r in denied:
            self.assertMessage(r, 400, "Unauthorized access")

    def test_full_lifecycle(self):
        tid = self.new_ticket()
        officer, admin = self.api(self.officer), self.api(self.admin)

        # pickup pool
        self.assertEqual([t["id"] for t in officer.get("/api/tickets/officer/open").json()], [tid])
        self.assertEqual(officer.get("/api/tickets/officer/unit").json(), [])

        # pickup
        r = officer.put(f"/api/tickets/officer/{tid}/pickup", {}, format="json")
        t = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(t), TICKET_KEYS)
        self.assertEqual((t["status"], t["assignedTo"], t["assignedToName"], t["assignedToUnit"]),
                         ("In Progress", "officer@test.lk", "Kamal Silva (AsyHub)", "AsyHub"))
        self.assertEqual(self.to(), ["admin2@test.lk", "admin@test.lk", "client@test.lk"])
        self.assertEqual({m.subject for m in mail.outbox}, {f"Ticket Picked Up — #{tid}", f"Ticket Update — #{tid}"})
        self.assertIn("Kamal Silva (AsyHub) has picked up a ticket.", mail.outbox[0].body)
        self.assertEqual(officer.get("/api/tickets/officer/open").json(), [])
        self.assertEqual([x["id"] for x in self.api(self.officer2).get("/api/tickets/officer/unit").json()], [tid])
        mail.outbox.clear()

        # classify
        r = officer.put(f"/api/tickets/{tid}/classify", {"category": "Printer Issue", "priority": "High"}, format="json")
        self.assertEqual((r.json()["category"], r.json()["priority"]), ("Printer Issue", "High"))
        self.assertEqual(len(mail.outbox), 0)

        # return (by another officer: any officer may act on any ticket)
        r = self.api(self.officer2).put(f"/api/tickets/officer/{tid}/return", {"reason": "Need admin"}, format="json")
        t = r.json()
        self.assertEqual((t["status"], t["assignedTo"], t["assignedToName"], t["assignedToUnit"], t["category"],
                          t["priority"], t["returnReason"]), ("Open", None, None, None, None, None, "Need admin"))
        self.assertEqual(self.to(), ["admin2@test.lk", "admin@test.lk"])
        self.assertEqual(mail.outbox[0].subject, f"Ticket Returned — #{tid}")
        self.assertIn("A ticket has been returned by Sunil Dias (Functional).", mail.outbox[0].body)
        self.assertIn("Reason: Need admin\n", mail.outbox[0].body)
        self.assertMessage(officer.put(f"/api/tickets/officer/{tid}/return", {"reason": "again"}, format="json"),
                           400, "Only In Progress tickets can be returned")
        mail.outbox.clear()

        # admin assigns: officer is told, client is NOT emailed a second time
        r = admin.put(f"/api/tickets/admin/{tid}/assign", {"assignedTo": "officer@test.lk"}, format="json")
        t = r.json()
        self.assertEqual((t["status"], t["assignedTo"], t["returnReason"]), ("In Progress", "officer@test.lk", None))
        self.assertEqual(self.to(), ["officer@test.lk"])
        self.assertEqual(mail.outbox[0].subject, f"New Ticket Assigned — #{tid}")
        mail.outbox.clear()

        # resolve
        bad = officer.put(f"/api/tickets/admin/{tid}/status", {"status": "Closed"}, format="json")
        self.assertMessage(bad, 400, "Only the Resolved status can be set here")
        r = officer.put(f"/api/tickets/admin/{tid}/status", {"status": "Resolved", "resolutionNote": "Replaced toner"}, format="json")
        t = r.json()
        self.assertEqual((t["status"], t["resolvedBy"], t["resolutionNote"]), ("Resolved", "Kamal Silva (AsyHub)", "Replaced toner"))
        self.assertEqual(self.to(), ["admin2@test.lk", "admin@test.lk", "client@test.lk"])
        client_mail = next(m for m in mail.outbox if m.to == ["client@test.lk"])
        self.assertEqual(client_mail.body, (
            "Dear Nimal Perera,\n\nYour ticket has been resolved.\n\n"
            f"Ticket ID: #{tid}\nSubject: Printer broken\nStatus: Resolved\n"
            "Resolved by: Kamal Silva (AsyHub)\nResolution: Replaced toner\n"
            "\nThank you for contacting Sri Lanka Customs ICT Directorate."))
        self.assertMessage(officer.put(f"/api/tickets/admin/{tid}/status", {"status": "Resolved"}, format="json"),
                           400, "Only In Progress tickets can be resolved")
        mail.outbox.clear()

        # close
        r = admin.put(f"/api/tickets/admin/{tid}/close", {"closeNote": "Confirmed"}, format="json")
        self.assertEqual((r.json()["status"], r.json()["closeNote"]), ("Closed", "Confirmed"))
        self.assertEqual(self.to(), ["client@test.lk"])
        self.assertIn("Status: Closed\nNote: Confirmed\n\nThank you for using", mail.outbox[0].body)
        self.assertMessage(admin.put(f"/api/tickets/admin/{tid}/close", {}, format="json"), 400, "Only Resolved tickets can be closed")

        # timeline
        history = admin.get(f"/api/tickets/{tid}/history").json()
        self.assertEqual([(h["status"], h["note"]) for h in history], [
            ("Open", "Ticket submitted"),
            ("In Progress", "Kamal Silva (AsyHub) picked up this ticket"),
            ("In Progress", "Classified by Kamal Silva (AsyHub) — Category: Printer Issue, Priority: High"),
            ("Open", "Returned by Sunil Dias (Functional) — Need admin"),
            ("In Progress", "Assigned to Kamal Silva (AsyHub)"),
            ("Resolved", "Resolved by Kamal Silva (AsyHub) — Replaced toner"),
            ("Closed", "Closed by Admin Boss — Confirmed"),
        ])
        self.assertEqual([t["id"] for t in admin.get("/api/tickets/admin/all").json()], [tid])

    def test_first_assignment_by_admin_emails_client_once(self):
        tid = self.new_ticket()
        admin = self.api(self.admin)
        admin.put(f"/api/tickets/admin/{tid}/assign", {"assignedTo": "officer@test.lk"}, format="json")
        self.assertEqual(self.to(), ["client@test.lk", "officer@test.lk"])
        mail.outbox.clear()
        # unassign with an empty value -> back to the queue, no emails
        r = admin.put(f"/api/tickets/admin/{tid}/assign", {"assignedTo": ""}, format="json")
        self.assertEqual((r.json()["status"], r.json()["assignedTo"]), ("Open", None))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(TicketHistory.objects.filter(ticket_id=tid).last().note, "Ticket unassigned — returned to queue")
        self.assertMessage(admin.put(f"/api/tickets/admin/{tid}/assign", {"assignedTo": "x@nowhere.lk"}, format="json"),
                           400, "Officer not found")

    def test_resolve_and_close_without_notes(self):
        tid = self.new_ticket()
        self.api(self.officer).put(f"/api/tickets/officer/{tid}/pickup", {}, format="json")
        mail.outbox.clear()
        # React sends resolutionNote: null
        r = self.api(self.admin).put(f"/api/tickets/admin/{tid}/status", {"status": "Resolved", "resolutionNote": None}, format="json")
        self.assertEqual((r.json()["resolvedBy"], r.json()["resolutionNote"]), ("Admin Boss (Administration)", None))
        self.assertNotIn("Resolution:", mail.outbox[0].body)
        r = self.api(self.admin).put(f"/api/tickets/admin/{tid}/close", {"closeNote": None}, format="json")
        self.assertEqual((r.json()["status"], r.json()["closeNote"]), ("Closed", None))
        notes = list(TicketHistory.objects.filter(ticket_id=tid).order_by("id").values_list("note", flat=True))
        self.assertEqual(notes[-2:], ["Resolved by Admin Boss (Administration)", "Closed by Admin Boss"])

    def test_long_resolution_note_fits_in_history(self):
        tid = self.new_ticket()
        self.api(self.officer).put(f"/api/tickets/officer/{tid}/pickup", {}, format="json")
        note = "Detailed steps. " * 60
        r = self.api(self.officer).put(f"/api/tickets/admin/{tid}/status", {"status": "Resolved", "resolutionNote": note}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(TicketHistory.objects.filter(ticket_id=tid).last().note.endswith(note))

    def test_reject(self):
        tid = self.new_ticket()
        r = self.api(self.admin).put(f"/api/tickets/admin/{tid}/reject", {"reason": "Duplicate"}, format="json")
        self.assertEqual((r.json()["status"], r.json()["cancelReason"]), ("Cancelled", "Duplicate"))
        self.assertEqual(self.to(), ["client@test.lk"])
        self.assertEqual(mail.outbox[0].subject, f"Ticket Cancelled — #{tid}")
        self.assertIn("Reason: Duplicate\n", mail.outbox[0].body)
        self.assertEqual(TicketHistory.objects.filter(ticket_id=tid).last().note, "Cancelled by Admin Boss — Duplicate")

    def test_classify_keeps_old_value_when_blank(self):
        tid = self.new_ticket()
        admin = self.api(self.admin)
        admin.put(f"/api/tickets/{tid}/classify", {"category": "Network Issue", "priority": ""}, format="json")
        t = Ticket.objects.get(pk=tid)
        self.assertEqual((t.category, t.priority, t.status), ("Network Issue", None, "Open"))
        self.assertEqual(TicketHistory.objects.filter(ticket_id=tid).last().note,
                         "Classified by Admin Boss (Administration) — Category: Network Issue, Priority: null")
        admin.put(f"/api/tickets/{tid}/classify", {"category": "", "priority": "Low"}, format="json")
        t.refresh_from_db()
        self.assertEqual((t.category, t.priority), ("Network Issue", "Low"))


# ---------------------------------------------------------------------------
class CommentTests(ApiTestCase):
    def test_comments(self):
        tid = self.new_ticket()
        client, officer = self.api(self.client_user), self.api(self.officer)
        url = f"/api/tickets/{tid}/comments"

        # unassigned ticket: client comment notifies nobody
        r = client.post(url, {"message": "Any update?"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {"id", "message", "createdAt", "userName", "userRole", "userCompany"})
        self.assertEqual((r.json()["message"], r.json()["userName"], r.json()["userRole"], r.json()["userCompany"]),
                         ("Any update?", "Nimal Perera", "client", "Acme Shipping"))
        self.assertEqual(len(mail.outbox), 0)

        officer.put(f"/api/tickets/officer/{tid}/pickup", {}, format="json")
        mail.outbox.clear()

        officer.post(url, {"message": "Checking now"}, format="json")
        self.assertEqual(self.to(), ["client@test.lk"])
        self.assertEqual(mail.outbox[0].subject, f"New Comment on Ticket #{tid}")
        self.assertEqual(mail.outbox[0].body, (
            f"Dear Nimal Perera,\n\nKamal Silva commented on your ticket #{tid}:\n\n"
            "\"Checking now\"\n\nSubject: Printer broken\n\nSri Lanka Customs ICT Directorate"))
        mail.outbox.clear()

        client.post(url, {"message": "Thanks"}, format="json")
        self.assertEqual(self.to(), ["officer@test.lk"])
        self.assertIn(f"Nimal Perera commented on ticket #{tid}:", mail.outbox[0].body)

        listing = self.api(self.admin).get(url).json()
        self.assertEqual([c["message"] for c in listing], ["Any update?", "Checking now", "Thanks"])
        self.assertEqual(listing[1]["userRole"], "officer")

        self.assertMessage(self.api(self.admin).post(url, {"message": "hi"}, format="json"), 400, "Admins cannot comment")
        self.assertMessage(client.post(url, {"message": "   "}, format="json"), 400, "Comment cannot be empty")
        self.assertMessage(self.api(self.other_client).post(url, {"message": "hi"}, format="json"), 400, "Access denied")
        self.assertMessage(self.api(self.other_client).get(url), 400, "Access denied")

        Ticket.objects.filter(pk=tid).update(status="Closed")
        self.assertMessage(client.post(url, {"message": "late"}, format="json"), 400, "Comments are closed for this ticket")
        Ticket.objects.filter(pk=tid).update(status="Cancelled")
        self.assertMessage(officer.post(url, {"message": "late"}, format="json"), 400, "Comments are closed for this ticket")


# ---------------------------------------------------------------------------
class KnowledgeBaseTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        def solved(subject, category, note, status="Resolved"):
            return Ticket.objects.create(subject=subject, description="desc " + subject, user=self.client_user,
                                         status=status, category=category, resolution_note=note)
        self.printer = solved("Printer jam", "Printer Issue", "Cleared the roller")
        self.vpn = solved("VPN down", "Network Issue", "Restarted the gateway", "Closed")
        self.custom = solved("Scanner", "Barcode Scanner", "Updated driver")
        solved("No note", "Printer Issue", None)
        solved("Empty note", "Printer Issue", "")
        solved("Still open", "Printer Issue", "note", "In Progress")

    def search(self, **params):
        r = self.api(self.officer).get("/api/tickets/knowledge-base", params)
        self.assertEqual(r.status_code, 200)
        return {t["subject"] for t in r.json()}

    def test_search(self):
        self.assertEqual(self.search(), {"Printer jam", "VPN down", "Scanner"})
        self.assertEqual(self.search(category="All"), {"Printer jam", "VPN down", "Scanner"})
        self.assertEqual(self.search(category="Printer Issue"), {"Printer jam"})
        self.assertEqual(self.search(category="Other"), {"Scanner"})
        self.assertEqual(self.search(search="GATEWAY"), {"VPN down"})       # resolution note, any case
        self.assertEqual(self.search(search="desc printer"), {"Printer jam"})  # description
        self.assertEqual(self.search(search="barcode"), {"Scanner"})        # category
        self.assertEqual(self.search(search="roller", category="Network Issue"), set())
        self.assertEqual(self.api(self.admin).get("/api/tickets/knowledge-base").status_code, 200)


# ---------------------------------------------------------------------------
class UploadTests(ApiTestCase):
    def test_client_attachment_and_download(self):
        tid = self.new_ticket()
        client = self.api(self.client_user)
        r = client.post(f"/api/tickets/{tid}/attachment", {"file": png("my screen (1).PNG", 30)}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        stored = r.json()["attachmentPath"]
        self.assertRegex(stored, r"^\d{13}_my_screen__1_\.PNG$")
        self.assertEqual(set(r.json()), TICKET_KEYS)

        r = self.api(self.officer).get(f"/api/tickets/uploads/{stored}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertEqual(r["Content-Disposition"], f'inline; filename="{stored}"')
        self.assertEqual(b"".join(r.streaming_content), b"x" * 30)

        self.assertEqual(self.api(self.officer).get("/api/tickets/uploads/missing.png").status_code, 404)
        self.assertEqual(self.api(self.officer).get("/api/tickets/uploads/..").status_code, 403)
        self.assertEqual(self.api().get(f"/api/tickets/uploads/{stored}").status_code, 403)
        self.assertEqual(self.api(token="bad").get(f"/api/tickets/uploads/{stored}").status_code, 401)

    def test_file_rules(self):
        tid = self.new_ticket()
        client = self.api(self.client_user)
        url = f"/api/tickets/{tid}/attachment"
        bad = lambda name: client.post(url, {"file": png(name)}, format="multipart")
        self.assertMessage(bad("virus.exe"), 400, "File type not allowed. Use JPG, PNG, PDF, DOC or DOCX")
        self.assertMessage(bad("page.html"), 400, "File type not allowed. Use JPG, PNG, PDF, DOC or DOCX")
        self.assertMessage(client.post(url, {}, format="multipart"), 400, "File is required")
        for name in ["a.jpg", "a.jpeg", "a.png", "a.pdf", "a.doc", "a.DOCX"]:
            self.assertEqual(bad(name).status_code, 200, name)
        self.assertMessage(self.api(self.other_client).post(url, {"file": png()}, format="multipart"), 400, "Access denied")
        self.assertMessage(self.api(self.officer).post(url, {"file": png()}, format="multipart"), 400, "Access denied")

    def test_very_long_file_name_is_shortened(self):
        tid = self.new_ticket()
        r = self.api(self.client_user).post(f"/api/tickets/{tid}/attachment", {"file": png("n" * 400 + ".png")}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        stored = r.json()["attachmentPath"]
        self.assertLessEqual(len(stored), 255)
        self.assertTrue(stored.endswith(".png"))
        self.assertEqual(self.api(self.client_user).get(f"/api/tickets/uploads/{stored}").status_code, 200)

    def test_too_large(self):
        tid = self.new_ticket()
        big = png("big.png", settings.MAX_UPLOAD_BYTES + 1)
        r = self.api(self.client_user).post(f"/api/tickets/{tid}/attachment", {"file": big}, format="multipart")
        self.assertMessage(r, 413, "File is too large. Maximum size is 10MB")

    def test_staff_attachments(self):
        tid = self.new_ticket()
        officer, admin, client = self.api(self.officer), self.api(self.admin), self.api(self.client_user)
        cases = [
            ("resolution-attachment", "resolutionAttachmentPath", officer, [admin, client]),
            ("return-attachment", "returnAttachmentPath", officer, [admin, client]),
            ("cancel-attachment", "cancelAttachmentPath", admin, [officer, client]),
            ("close-attachment", "closeAttachmentPath", admin, [officer, client]),
        ]
        for path, key, allowed, denied in cases:
            r = allowed.post(f"/api/tickets/{tid}/{path}", {"file": png("proof.pdf")}, format="multipart")
            self.assertEqual(r.status_code, 200, path)
            self.assertTrue(r.json()[key].endswith("_proof.pdf"), path)
            for other in denied:
                self.assertMessage(other.post(f"/api/tickets/{tid}/{path}", {"file": png()}, format="multipart"),
                                   400, "Unauthorized access")
        self.assertMessage(admin.post("/api/tickets/99999/close-attachment", {"file": png()}, format="multipart"),
                           400, "Ticket not found")
        r = admin.get("/api/tickets/uploads/" + Ticket.objects.get(pk=tid).close_attachment_path)
        self.assertEqual(r["Content-Type"], "application/pdf")


# ---------------------------------------------------------------------------
class UserAdminTests(ApiTestCase):
    def test_list_users(self):
        r = self.api(self.admin).get("/api/users")
        self.assertEqual(r.status_code, 200)
        users = r.json()
        self.assertEqual(len(users), 6)
        for u in users:
            self.assertEqual(set(u), USER_KEYS)  # no password, no reset token
        self.assertEqual(users[0]["email"], "admin2@test.lk")  # newest first
        self.assertIs(users[0]["active"], True)

    def test_add_user_and_welcome_link(self):
        admin = self.api(self.admin)
        data = {"fullName": " New Officer ", "email": " newofficer@test.lk ", "company": "Audit", "role": "Officer"}
        self.assertMessage(admin.post("/api/users", data, format="json"), 201, "User created successfully")
        user = User.objects.get(email="newofficer@test.lk")
        self.assertEqual((user.full_name, user.company, user.role, user.active), ("New Officer", "Audit", "officer", True))

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual((email.subject, email.to), ("Welcome to Sri Lanka Customs ICT Portal", ["newofficer@test.lk"]))
        token = re.search(r"http://front\.test/reset-password\?token=(\S+)", email.body).group(1)
        self.assertEqual(email.body, (
            "Dear New Officer,\n\nYour account has been created.\n\nEmail: newofficer@test.lk\n\n"
            "Click the link below to set your password. The link works once and expires in 24 hours:\n\n"
            f"http://front.test/reset-password?token={token}\n\nSri Lanka Customs ICT Directorate"))

        # the new user sets a password through the link, then logs in
        r = self.api().post("/api/auth/reset-password", {"token": token, "newPassword": "officer123"}, format="json")
        self.assertEqual(r.status_code, 200)
        r = self.api().post("/api/auth/login", {"email": "newofficer@test.lk", "password": "officer123"}, format="json")
        self.assertEqual(r.json()["user"]["role"], "officer")

    def test_add_user_validation(self):
        post = lambda d: self.api(self.admin).post("/api/users", d, format="json")
        ok = {"fullName": "A B", "email": "x@test.lk", "company": "Co", "role": "client"}
        self.assertMessage(post({**ok, "role": ""}), 400, "All fields are required")
        self.assertMessage(post({**ok, "email": "bad"}), 400, "Invalid email address")
        self.assertMessage(post({**ok, "role": "superuser"}), 400, "Invalid role")
        self.assertMessage(post({**ok, "company": "c" * 101}), 400, "Input is too long")
        self.assertMessage(post({**ok, "email": "client@test.lk"}), 400, "Email already registered")
        self.assertEqual(len(mail.outbox), 0)

    def test_toggle_user(self):
        admin = self.api(self.admin)
        uid = self.client_user.id
        token = generate_token(self.client_user.email)

        self.assertMessage(admin.put(f"/api/users/{self.admin.id}/toggle", {"reason": None}, format="json"),
                           400, "You cannot deactivate your own account")
        self.assertMessage(admin.put("/api/users/99999/toggle", {}, format="json"), 400, "User not found")

        self.assertMessage(admin.put(f"/api/users/{uid}/toggle", {"reason": " Left the company "}, format="json"), 200, "User deactivated")
        self.client_user.refresh_from_db()
        self.assertEqual((self.client_user.active, self.client_user.deactivate_reason), (False, "Left the company"))
        self.assertEqual(mail.outbox[0].subject, "Account Deactivated — Sri Lanka Customs ICT Portal")
        self.assertEqual(mail.outbox[0].body, (
            "Dear Nimal Perera,\n\nYour account has been deactivated.\nReason: Left the company\n"
            "\nPlease contact the ICT Directorate for further assistance.\n\nSri Lanka Customs ICT Directorate"))
        # their old token stops working at once
        self.assertMessage(self.api(token=token).get("/api/tickets"), 401, "Account deactivated or not found")
        self.assertMessage(admin.put(f"/api/users/{uid}/reset-password", {}, format="json"), 400,
                           "Cannot reset the password of a deactivated user")

        r = admin.post(f"/api/users/{uid}/deactivate-attachment", {"file": png("letter.pdf")}, format="multipart")
        self.assertMessage(r, 200, "Attachment uploaded successfully")
        listed = next(u for u in admin.get("/api/users").json() if u["id"] == uid)
        self.assertEqual((listed["active"], listed["deactivateReason"]), (False, "Left the company"))
        self.assertTrue(listed["deactivateAttachmentPath"].endswith("_letter.pdf"))
        self.assertEqual(admin.get("/api/tickets/uploads/" + listed["deactivateAttachmentPath"]).status_code, 200)
        mail.outbox.clear()

        self.assertMessage(admin.put(f"/api/users/{uid}/toggle", {"reason": None}, format="json"), 200, "User activated")
        self.client_user.refresh_from_db()
        self.assertEqual((self.client_user.active, self.client_user.deactivate_reason,
                          self.client_user.deactivate_attachment_path), (True, None, None))
        self.assertEqual(mail.outbox[0].subject, "Account Activated — Sri Lanka Customs ICT Portal")
        self.assertEqual(self.api(token=token).get("/api/tickets").status_code, 200)

    def test_json_null_body_is_treated_as_empty(self):
        r = self.api(self.admin).put(f"/api/users/{self.officer2.id}/toggle", data="null", content_type="application/json")
        self.assertMessage(r, 200, "User deactivated")

    def test_toggle_without_body(self):
        r = self.api(self.admin).put(f"/api/users/{self.officer.id}/toggle")
        self.assertMessage(r, 200, "User deactivated")
        self.assertNotIn("Reason:", mail.outbox[0].body)

    def test_admin_reset_password_sends_link_only(self):
        old_hash = self.officer.password
        r = self.api(self.admin).put(f"/api/users/{self.officer.id}/reset-password", {}, format="json")
        self.assertMessage(r, 200, "Reset link sent to the user's email")
        self.officer.refresh_from_db()
        self.assertEqual(self.officer.password, old_hash)  # password untouched until the link is used
        self.assertEqual(mail.outbox[0].subject, "Password Reset — Sri Lanka Customs ICT Portal")
        self.assertIn("Your administrator has requested a password reset for your account.", mail.outbox[0].body)
        self.assertIn("expires in 60 minutes", mail.outbox[0].body)
        self.assertMessage(self.api(self.admin).put("/api/users/99999/reset-password", {}, format="json"), 400, "User not found")

    def test_deactivate_attachment_rules(self):
        admin = self.api(self.admin)
        url = f"/api/users/{self.officer.id}/deactivate-attachment"
        self.assertMessage(admin.post(url, {"file": png("x.exe")}, format="multipart"), 400,
                           "File type not allowed. Use JPG, PNG, PDF, DOC or DOCX")
        self.assertMessage(self.api(self.officer).post(url, {"file": png()}, format="multipart"), 400, "Unauthorized access")


# ---------------------------------------------------------------------------
class UnitTests(ApiTestCase):
    def test_units(self):
        admin = self.api(self.admin)
        r = admin.post("/api/units", {"name": "  Statistics "}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["message"], "Unit added successfully")
        self.assertEqual(set(r.json()["unit"]), {"id", "name", "createdAt"})
        self.assertEqual(r.json()["unit"]["name"], "Statistics")
        admin.post("/api/units", {"name": "AsyHub"}, format="json")

        self.assertMessage(admin.post("/api/units", {"name": "AsyHub"}, format="json"), 400, "Unit already exists")
        self.assertMessage(admin.post("/api/units", {"name": "  "}, format="json"), 400, "Unit name is required")
        self.assertMessage(admin.post("/api/units", {}, format="json"), 400, "Unit name is required")
        self.assertMessage(admin.post("/api/units", {"name": "u" * 101}, format="json"), 400, "Unit name is too long")

        # every logged-in role can read the list, sorted by name
        for user in (self.client_user, self.officer, self.admin):
            self.assertEqual([u["name"] for u in self.api(user).get("/api/units").json()], ["AsyHub", "Statistics"])

        unit_id = Unit.objects.get(name="AsyHub").id
        self.assertMessage(admin.delete(f"/api/units/{unit_id}"), 200, "Unit deleted successfully")
        self.assertMessage(admin.delete(f"/api/units/{unit_id}"), 400, "Unit not found")
        self.assertEqual(Unit.objects.count(), 1)
