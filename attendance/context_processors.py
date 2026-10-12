from django.utils import timezone
from .organization import (
    get_active_organization,
    get_user_organizations,
    is_employee_self_service_user,
    user_has_hr_access,
    user_has_manager_access,
    user_has_payroll_access,
    user_has_viewer_access,
)


def global_context(request):
    context = {
        "today": timezone.localdate(),
    }

    if request.user.is_authenticated:
        context["is_employee_self_service_only"] = is_employee_self_service_user(request.user)
        context["user_has_hr_access"] = user_has_hr_access(request.user)
        context["user_has_manager_access"] = user_has_manager_access(request.user)
        context["user_has_payroll_access"] = user_has_payroll_access(request.user)
        context["user_has_viewer_access"] = user_has_viewer_access(request.user)
        context["active_organization"] = get_active_organization(request)
        context["user_organizations"] = get_user_organizations(request.user)
        try:
            from .branding import accent_vars
            org = context.get("active_organization")
            if org is not None:
                context["brand_accent"] = accent_vars(getattr(org, "brand_color", "#3B5BFF"))
        except Exception:
            pass

    return context
