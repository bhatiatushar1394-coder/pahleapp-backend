from rest_framework.permissions import BasePermission

from .models import User

OFFICER_ROLES = {
    User.Role.ADMIN,
    User.Role.SALES_OFFICER,
    User.Role.ENGINEERING_OFFICER,
    User.Role.DO_OFFICER,
}


class IsOfficer(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in OFFICER_ROLES)
