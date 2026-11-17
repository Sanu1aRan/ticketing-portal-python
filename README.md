ICT Help Desk Ticketing System — Backend (Python)

REST API for the Sri Lanka Customs ICT Help Desk, written in Python with Django. It is a full port of the Java Spring Boot backend: the same 40 endpoints, the same JSON, the same emails and the same rules, so the existing React frontend works with it without any change.

Tech Stack

Python 3.13, Django 5.2, Django REST Framework, PyJWT, BCrypt, MySQL / MariaDB

Running It

XAMPP MySQL needs to be running.

    venv\Scripts\activate
    python manage.py runserver 8080

Runs at http://localhost:8080 — the same address the Java backend used, so the frontend `.env` stays `VITE_API_URL=http://localhost:8080`. Start the frontend as before with `npm run dev`.

First-Time Setup

1. Start XAMPP with MySQL
2. Create a database called customs_ticketing_py (in phpMyAdmin, or `CREATE DATABASE customs_ticketing_py CHARACTER SET utf8mb4;`)
3. Create and activate a virtual environment, then install the packages:

        python -m venv venv
        venv\Scripts\activate
        pip install -r requirements.txt

4. Copy config/local_settings.example.py to config/local_settings.py and fill in your values (database password, JWT secret, mail account)
5. Create the tables:

        python manage.py migrate

6. Create the first admin (the Register page only creates clients):

        python manage.py create_admin admin@example.com "Admin Name" YourPassword

7. Run it: `python manage.py runserver 8080`

config/local_settings.py (not in GitHub)

This is the Python version of application.properties. See config/local_settings.example.py for every setting. The main ones:

    DB_NAME = "customs_ticketing_py"
    DB_USER = "root"
    DB_PASSWORD = ""
    JWT_SECRET = "your-strong-secret-key"
    FRONTEND_URL = "http://localhost:5173"
    EMAIL_HOST_USER = "your-email@gmail.com"
    EMAIL_HOST_PASSWORD = "your-app-password"

If EMAIL_HOST_USER is left empty, emails are printed in the terminal instead of being sent. That is handy for testing: reset and welcome links appear in the terminal.

What It Does

Full ticket lifecycle: create, assign, classify, resolve, return, cancel, close. Every status change is logged in ticket_history with who did it and when. Emails go out automatically at each step. The client gets only one "being processed" email per ticket, even after return and re-pickup.

Comment system: clients and officers talk on tickets. Client comments notify the assigned officer, officer comments notify the client. Admin is read-only. Comments are closed on Closed and Cancelled tickets.

Knowledge base: officers and admins search resolved and closed tickets by keyword across subject, description, resolution note and category.

Security

 4 public endpoints: login, register, forgot-password, reset-password. Everything else needs a JWT token.
 Every request with a token is checked; deactivated or deleted users are rejected at once.
 Role checks (admin, officer) and ownership checks (a client only sees and edits their own tickets).
 Passwords are hashed with BCrypt and never returned by the API.
 Password reset uses a one-time link that expires in 30 minutes. Only a hash of the link token is stored.
 Login lockout: 5 failed attempts lock that email for 15 minutes (kept in memory, resets on restart).
 File uploads allow only JPG, JPEG, PNG, PDF, DOC and DOCX, up to 10MB. File names are cleaned.
 An admin cannot deactivate their own account.

Known limits (same as the Java version): tokens are not revoked on logout, no per-IP rate limiting, uploads are not content-scanned, HTTPS is not set up yet. The login lockout is kept per server process, so run one process (the commands below do).

Where Things Are

    Java                                  Python
    model/*.java                          tickets/models.py
    repository/*.java                     not needed (Django's ORM does the queries)
    controller/AuthController.java        tickets/views/auth_views.py
    controller/TicketController.java      tickets/views/ticket_views.py
    controller/UserController.java        tickets/views/user_views.py
    controller/UnitController.java        tickets/views/unit_views.py
    service/AuthService.java              tickets/services/auth_service.py
    service/TicketService.java            tickets/services/ticket_service.py
    service/EmailService.java             tickets/services/email_service.py
    security/JwtUtil.java, JwtAuthFilter  tickets/security.py
    security/SecurityConfig.java          config/settings.py
    application.properties                config/local_settings.py
    pom.xml                               requirements.txt

All 40 API addresses are listed in tickets/urls.py. tickets/serializers.py turns database rows into the JSON the frontend expects.

Tests

    python manage.py test

53 automated tests call every endpoint and check the answers, the emails and the permission rules.

Database

The same 5 tables as the Java version: users, tickets, ticket_history, ticket_comment, units (plus django_migrations, which Django uses to remember that the tables exist). `python manage.py migrate` creates them.

Works with MySQL 8 and MariaDB 10.4 or newer (XAMPP ships MariaDB 10.4).

Optional — reuse the data from the Java version: the table and column names are the same and the password hashes are compatible, so this backend can run on a copy of the Java database. Make a copy of customs_ticketing first, point DB_NAME at the copy, and run `python manage.py migrate --fake-initial` (this tells Django the tables already exist). Always work on a copy, never on the only one.

Running in Production

`runserver` is for development only. On the server use a real application server:

    Windows:  pip install waitress
              waitress-serve --port=8080 config.wsgi:application

    Linux:    pip install gunicorn
              gunicorn --workers 1 --threads 8 --bind 0.0.0.0:8080 config.wsgi

Production Checklist

Set DEBUG = False and ALLOWED_HOSTS in config/local_settings.py
Set FRONTEND_URL and CORS_ALLOWED_ORIGINS to the real frontend address
Use a new random JWT_SECRET (never reuse the development one)
Set JWT_EXPIRATION_HOURS = 8
Set up HTTPS
Create the uploads/ folder with write permission
Switch to the organisation's mail server
Set up database backups
