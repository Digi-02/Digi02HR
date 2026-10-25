# attendance/middleware.py
from django.shortcuts import render, redirect


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


class SetupWizardMiddleware:
    """Redirect owner / hr_admin into the setup wizard until setup is complete.

    Exempt paths: logout, password reset/change, static/media, /platform/,
    kiosk, login, welcome, set-password.
    """

    EXEMPT_PREFIXES = (
        '/platform/',
        '/logout',
        '/static/',
        '/media/',
        '/welcome/',
        '/login/',
        '/password-reset',
        '/reset/',
        '/password-change',
        '/set-password/',
        '/o/',
    )
    EXEMPT_EXACT = {'/', '/setup/wizard/', '/setup/complete/'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            path = request.path or '/'
            is_exempt = path in self.EXEMPT_EXACT or any(
                path.startswith(p) for p in self.EXEMPT_PREFIXES
            )
            if not is_exempt:
                try:
                    from .organization import get_active_organization
                    from .models import OrganizationMembership
                    org = get_active_organization(request)
                    if org is not None and not org.setup_completed:
                        is_owner_or_hr = OrganizationMembership.objects.filter(
                            user=request.user, organization=org,
                            role__in=('owner', 'hr_admin'), is_active=True,
                        ).exists()
                        if is_owner_or_hr:
                            return redirect('setup_wizard')
                except Exception:
                    pass
        return self.get_response(request)
