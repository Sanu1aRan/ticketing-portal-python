"""
Database tables. One class = one table, same 5 tables as the Java version:
users, units, tickets, ticket_comment, ticket_history.

Java name -> Python name:  fullName -> full_name  (the database column is
full_name in both, because Hibernate also stored it in snake_case).
"""

from django.db import models
from django.utils import timezone


class BitBooleanField(models.BooleanField):
    """
    A normal True/False column.

    Hibernate (Java) created the "active" column as BIT(1), and MySQL hands a
    BIT back as raw bytes. This reads those bytes correctly, so the same code
    works on a database made by Django or on one made by the Java version.
    """

    def from_db_value(self, value, expression, connection):
        if isinstance(value, (bytes, bytearray)):
            return any(value)
        return value


class User(models.Model):
    full_name = models.CharField(max_length=255)
    email = models.CharField(max_length=255, unique=True)
    password = models.CharField(max_length=255)  # BCrypt hash, never plain text
    company = models.CharField(max_length=255)
    role = models.CharField(max_length=255, default="client")  # client / officer / admin
    active = BitBooleanField(default=True)
    deactivate_reason = models.TextField(null=True, blank=True)
    deactivate_attachment_path = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(null=True, blank=True)
    reset_token_hash = models.CharField(max_length=255, null=True, blank=True)
    reset_token_expiry = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "users"

    # Java: @PrePersist / @PreUpdate
    def save(self, *args, **kwargs):
        now = timezone.now()
        if self.created_at is None:
            self.created_at = now
        self.updated_at = now
        super().save(*args, **kwargs)

    # Lets REST framework treat a logged-in User as "authenticated".
    @property
    def is_authenticated(self):
        return True

    def __str__(self):
        return self.email


class Unit(models.Model):
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        db_table = "units"

    def save(self, *args, **kwargs):
        if self.created_at is None:
            self.created_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Ticket(models.Model):
    subject = models.CharField(max_length=255)
    category = models.CharField(max_length=255, null=True, blank=True)
    priority = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField()
    # Open -> In Progress -> Resolved -> Closed   (or Cancelled)
    status = models.CharField(max_length=255, default="Open")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tickets")
    created_at = models.DateTimeField(null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(null=True, blank=True)
    assigned_to = models.CharField(max_length=255, null=True, blank=True)  # officer email
    assigned_to_name = models.CharField(max_length=255, null=True, blank=True)
    assigned_to_unit = models.CharField(max_length=255, null=True, blank=True)
    resolved_by = models.CharField(max_length=255, null=True, blank=True)
    resolution_note = models.TextField(null=True, blank=True)
    attachment_path = models.CharField(max_length=255, null=True, blank=True)
    resolution_attachment_path = models.CharField(max_length=255, null=True, blank=True)
    return_reason = models.TextField(null=True, blank=True)
    return_attachment_path = models.CharField(max_length=255, null=True, blank=True)
    cancel_reason = models.TextField(null=True, blank=True)
    cancel_attachment_path = models.CharField(max_length=255, null=True, blank=True)
    close_note = models.TextField(null=True, blank=True)
    close_attachment_path = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "tickets"

    def save(self, *args, **kwargs):
        now = timezone.now()
        if self.created_at is None:
            self.created_at = now
        self.updated_at = now
        super().save(*args, **kwargs)

    def __str__(self):
        return f"#{self.pk} {self.subject}"


class TicketComment(models.Model):
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, null=True, related_name="comments"
    )
    user = models.ForeignKey(User, on_delete=models.PROTECT, null=True)
    message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True, default=timezone.now)

    class Meta:
        db_table = "ticket_comment"


class TicketHistory(models.Model):
    """The timeline: one row every time something happens to a ticket."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="history")
    status = models.CharField(max_length=255)
    # Java used VARCHAR(255) here; a long resolution note did not fit. TEXT fits any length.
    note = models.TextField(null=True, blank=True)
    changed_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        db_table = "ticket_history"

    def save(self, *args, **kwargs):
        if self.changed_at is None:
            self.changed_at = timezone.now()
        super().save(*args, **kwargs)
