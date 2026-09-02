from django.db.utils import OperationalError
from django.http import JsonResponse


class DatabaseUnavailableMiddleware:
    """Turn Neon DNS / connect failures into a short 503 instead of a 500 traceback."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except OperationalError:
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"detail": "Database is temporarily unreachable. Please retry."},
                    status=503,
                )
            raise
