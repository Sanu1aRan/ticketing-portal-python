"""
Creates the first admin account (or resets an existing one).

    python manage.py create_admin admin@customs.gov.lk "Admin Name" MyPassword123

A fresh database has no users, and the Register page only creates clients,
so this is how the very first admin gets in.
"""

from django.core.management.base import BaseCommand, CommandError

from tickets.models import User
from tickets.security import hash_password


class Command(BaseCommand):
    help = "Create (or update) an admin user"

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("full_name")
        parser.add_argument("password")
        parser.add_argument("--company", default="ICT Directorate")
        parser.add_argument("--role", default="admin", choices=["admin", "officer", "client"])

    def handle(self, *args, **options):
        if len(options["password"]) < 6:
            raise CommandError("Password must be at least 6 characters")
        user = User.objects.filter(email=options["email"]).first() or User(email=options["email"])
        user.full_name = options["full_name"]
        user.company = options["company"]
        user.role = options["role"]
        user.active = True
        user.password = hash_password(options["password"])
        user.save()
        self.stdout.write(self.style.SUCCESS(f"{user.role} account ready: {user.email}"))
