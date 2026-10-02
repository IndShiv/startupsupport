"""Settings for the test suite: local SQLite, debug defaults, fast hashing."""

import os

os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")

from .settings import *  # noqa: E402,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
MEDIA_ROOT = BASE_DIR / ".test-media"  # noqa: F405
