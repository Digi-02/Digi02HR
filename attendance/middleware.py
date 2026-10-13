# attendance/middleware.py
from django.shortcuts import render


class SuspendedOrganizationMiddleware:
    """Users of a suspended company see a clear page instead of the app."""

    EXEMPT_PREFIXES = ('/platform/', '/logout', '/static/', '/media/', '/welcome/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            path = request.path or '/'
            if not path.startswith(self.EXEMPT_PREFIXES):
                try:
                    from .organization import get_user_organizations
                    orgs = list(get_user_organizations(request.user))
                    active_id = request.session.get('active_organization_id')
                    active = next((o for o in orgs if o.pk == active_id), None)
                    target = active or (orgs[0] if orgs else None)
                    if target is not None and target.is_suspended:
                        return render(request, 'attendance/suspended.html',
                                      {'organization': target}, status=403)
                except Exception:
                    pass
        return self.get_response(request)
