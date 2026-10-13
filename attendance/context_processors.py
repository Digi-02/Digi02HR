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


def company_today(organization):
    """Current date in the company's timezone (falls back to server TZ)."""
    try:
        from zoneinfo import ZoneInfo
        tzname = getattr(organization, "timezone", "") or timezone.get_default_timezone_name()
        return timezone.now().astimezone(ZoneInfo(tzname)).date()
    except Exception:
        return timezone.localdate()


def company_greeting(organization):
    """Morning/afternoon/evening in the company's timezone."""
    try:
        from zoneinfo import ZoneInfo
        tzname = getattr(organization, "timezone", "") or timezone.get_default_timezone_name()
        hour = timezone.now().astimezone(ZoneInfo(tzname)).hour
    except Exception:
        hour = timezone.localtime().hour
    if hour < 12:
        return 'Good morning'
    if hour < 17:
        return 'Good afternoon'
    return 'Good evening'


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
                context["brand_accent"] = accent_vars(getattr(org, "brand_color", "#0A0A0A"))
                context["company_today"] = company_today(org)
                context["company_greeting"] = company_greeting(org)
            from .models import PlatformSettings
            ps = PlatformSettings.objects.filter(pk=1).first()
            if ps is not None and ps.announcement_active and ps.announcement:
                context["platform_announcement"] = ps.announcement
        except Exception:
            pass

    return context
