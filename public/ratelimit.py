"""Simple per-IP rate limiting for the public form.

The IP address is only used as a hashed cache key for one hour; it is never stored
with the registration.
"""

import hashlib

from django.conf import settings
from django.core.cache import cache

WINDOW_SECONDS = 3600


def client_ip(request):
    if settings.TRUST_X_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _key(request):
    digest = hashlib.sha256((settings.SECRET_KEY + client_ip(request)).encode()).hexdigest()[:32]
    return f"register-rate:{digest}"


def is_limited(request, limit):
    return cache.get(_key(request), 0) >= limit


def record_hit(request):
    key = _key(request)
    if cache.add(key, 1, WINDOW_SECONDS):
        return
    try:
        cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, WINDOW_SECONDS)
