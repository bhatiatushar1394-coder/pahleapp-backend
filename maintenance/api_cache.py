"""Per-user GET cache for authenticated JSON APIs.

Does not use the Django session table (that would add more Neon round-trips).
Responses are stored in Django's cache, keyed by user id + path + query, so
User A never receives User B's tickets. Writes clear the cache immediately.
"""

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

SKIP_PREFIXES = (
    "/api/health/",
    "/api/auth/login/",
    "/api/auth/register/",
    "/api/notifications",
)

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _user_scope(request) -> str:
    header = request.META.get("HTTP_AUTHORIZATION") or ""
    if not header.startswith("Bearer "):
        return "anon"
    raw = header.split(" ", 1)[1].strip()
    if not raw:
        return "anon"
    try:
        token = AccessToken(raw)
    except (InvalidToken, TokenError, ValueError, KeyError):
        return "anon"
    return str(token.get("user_id") or "anon")


def _cache_key(request) -> str:
    query = request.META.get("QUERY_STRING", "")
    return f"pahle:api:{_user_scope(request)}:{request.path}?{query}"


def _should_skip(request) -> bool:
    path = request.path
    if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
        return True
    if path.startswith("/api/reports/") and "csv" in (request.GET.get("format") or "").lower():
        return True
    return False


class ApiGetCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.ttl = int(getattr(settings, "API_CACHE_SECONDS", 60))

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        if request.method == "GET" and not _should_skip(request):
            hit = cache.get(_cache_key(request))
            if hit is not None:
                response = HttpResponse(hit, content_type="application/json")
                response["X-PAHLE-Cache"] = "HIT"
                return response

        response = self.get_response(request)

        if request.method in MUTATING and 200 <= response.status_code < 400:
            cache.clear()
            return response

        if (
            request.method == "GET"
            and response.status_code == 200
            and not _should_skip(request)
            and not getattr(response, "streaming", False)
            and "application/json" in (response.get("Content-Type") or "")
        ):
            cache.set(_cache_key(request), response.content, self.ttl)
            response["X-PAHLE-Cache"] = "MISS"

        return response
