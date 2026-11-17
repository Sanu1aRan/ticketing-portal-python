"""
Saving and finding uploaded files.  (saveFile() in TicketService.java and the
upload code in UserController.java)

Files go into the uploads/ folder. Only the file NAME is stored in the database.
"""

import os
import re
import time

from django.conf import settings

from ..security import ServiceError

ALLOWED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".pdf", ".doc", ".docx")

CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def save_file(uploaded_file):
    """Checks the file, saves it, and returns the stored file name."""
    original = uploaded_file.name
    # Use only the plain file name, never a folder path sent by the browser
    cleaned = None if original is None else original.replace("\\", "/").split("/")[-1]
    if not cleaned:
        raise ServiceError("Invalid file name")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", cleaned)
    cleaned = cleaned[-150:]  # the database column holds 255 characters
    if not cleaned.lower().endswith(ALLOWED_EXTENSIONS):
        raise ServiceError("File type not allowed. Use JPG, PNG, PDF, DOC or DOCX")

    upload_dir = settings.UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    file_name = str(int(time.time() * 1000)) + "_" + cleaned
    with open(os.path.join(upload_dir, file_name), "wb") as out:
        for chunk in uploaded_file.chunks():
            out.write(chunk)
    return file_name


def resolve_upload(filename):
    """
    Returns the full path of a stored file, or None if the name tries to
    escape the uploads folder (for example "..").
    """
    upload_dir = os.path.realpath(settings.UPLOAD_DIR)
    full_path = os.path.realpath(os.path.join(upload_dir, filename))
    if os.path.dirname(full_path) != upload_dir:
        return None
    return full_path


def content_type_for(filename):
    extension = os.path.splitext(filename)[1].lower()
    return CONTENT_TYPES.get(extension, "application/octet-stream")
