"""Application shell: role-aware navigation, favorites and global page search.

The shell deliberately keeps one source of truth for every navigable page so
sidebar links, the breadcrumb, favorites and search can never drift apart.
Only real, routed pages are registered here.
"""

from dataclasses import dataclass

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_POST

from .models import FavoritePage
from .organization import (
    get_active_organization,
    user_has_hr_access,
    user_has_manager_access,
    user_has_payroll_access,
)


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str
    url_name: str
    match: tuple
    access: tuple = ()
    keywords: str = ""
    external: bool = False


@dataclass(frozen=True)
class NavSection:
    key: str
    label: str
    items: tuple


NAV_SECTIONS = (
    NavSection(
        key="workspace",
        label="My workspace",
        items=(
            NavItem(
                key="my_dashboard",
                label="My dashboard",
                icon="bi-person-vcard",
                url_name="employee_self_service_dashboard",
                match=("employee_self_service_dashboard",),
                access=("self_service",),
                keywords="me home overview employee",
            ),
            NavItem(
                key="my_profile",
                label="My profile",
                icon="bi-person-lines-fill",
                url_name="employee_my_profile",
                match=("employee_my_profile",),
                access=("self_service",),
                keywords="me account details personal",
            ),
            NavItem(
                key="my_documents",
                label="My documents",
                icon="bi-folder2-open",
                url_name="employee_my_documents",
                match=("employee_my_documents",),
                access=("self_service",),
                keywords="me files uploads",
            ),
        ),
    ),
    NavSection(
        key="dashboards",
        label="Dashboards",
        items=(
            NavItem(
                key="overview",
                label="Overview",
                icon="bi-grid-1x2",
                url_name="dashboard",
                match=("dashboard", "category_dashboard"),
                access=("hr",),
                keywords="home dashboard overview",
            ),
            NavItem(
                key="manager_dashboard",
                label="Manager dashboard",
                icon="bi-kanban",
                url_name="manager_dashboard",
                match=("manager_dashboard",),
                access=("manager",),
                keywords="team manager overview",
            ),
        ),
    ),
    NavSection(
        key="people",
        label="People",
        items=(
            NavItem(
                key="employees",
                label="Employees",
                icon="bi-people",
                url_name="employee_list",
                match=(
                    "employee_list",
                    "employee_create",
                    "employee_detail",
                    "employee_edit",
                    "employee_delete",
                    "employee_account_create",
                ),
                access=("hr",),
                keywords="staff people team directory",
            ),
            NavItem(
                key="documents",
                label="Documents",
                icon="bi-folder2-open",
                url_name="employee_documents",
                match=(
                    "employee_documents",
                    "employee_document_upload",
                    "employee_document_upload_for_employee",
                    "employee_document_edit",
                    "employee_document_delete",
                ),
                access=("hr",),
                keywords="files records uploads",
            ),
            NavItem(
                key="digidoc",
                label="DigiDoc",
                icon="bi-journal-pen",
                url_name="digidoc_list",
                match=("digidoc_list", "digidoc_editor"),
                access=("hr",),
                keywords="documents editor letters reports",
            ),
            NavItem(
                key="onboarding",
                label="Onboarding",
                icon="bi-list-check",
                url_name="onboarding_tasks",
                match=(
                    "onboarding_tasks",
                    "applicant_invite",
                    "existing_employee_onboarding_invite",
                    "applicant_approve",
                    "applicant_reject",
                    "onboarding_stage_create",
                    "onboarding_stage_edit",
                    "onboarding_stage_delete",
                    "onboarding_participant_move",
                    "onboarding_task_create",
                    "onboarding_task_create_for_employee",
                    "onboarding_task_edit",
                    "onboarding_task_complete",
                    "onboarding_task_delete",
                ),
                access=("hr",),
                keywords="hiring tasks applicants stages",
            ),
            NavItem(
                key="manager_team",
                label="My team",
                icon="bi-people-fill",
                url_name="manager_team",
                match=("manager_team",),
                access=("manager",),
                keywords="direct reports team manager",
            ),
        ),
    ),
    NavSection(
        key="time",
        label="Time",
        items=(
            NavItem(
                key="attendance",
                label="Attendance",
                icon="bi-calendar-check",
                url_name="attendance_reports",
                match=(
                    "attendance_reports",
                    "manual_attendance_add",
                    "attendance_exception_types",
                ),
                access=("hr",),
                keywords="clock in out time records",
            ),
            NavItem(
                key="leave",
                label="Leave",
                icon="bi-calendar2-week",
                url_name="leave_requests",
                match=(
                    "leave_requests",
                    "employee_leave_detail",
                    "leave_request_detail",
                    "leave_request_create",
                    "leave_request_edit",
                    "leave_request_approve",
                    "leave_request_reject",
                    "leave_request_cancel",
                    "leave_request_delete",
                ),
                access=("hr",),
                keywords="time off holiday absence requests",
            ),
            NavItem(
                key="manager_leave",
                label="Team leave",
                icon="bi-calendar2-range",
                url_name="manager_leave_requests",
                match=("manager_leave_requests",),
                access=("manager",),
                keywords="approvals team time off manager",
            ),
        ),
    ),
    NavSection(
        key="communication",
        label="Communication",
        items=(
            NavItem(
                key="mail",
                label="Mail",
                icon="bi-envelope-paper",
                url_name="mail_dashboard",
                match=("mail_dashboard", "mail_compose", "mail_inbox_message"),
                access=("hr",),
                keywords="email inbox messages compose",
            ),
        ),
    ),
    NavSection(
        key="insights",
        label="Insights",
        items=(
            NavItem(
                key="admin_reports",
                label="Admin reports",
                icon="bi-journal-text",
                url_name="admin_reports",
                match=(
                    "admin_reports",
                    "admin_report_create",
                    "admin_report_detail",
                    "admin_report_edit",
                    "admin_report_delete",
                    "admin_report_set_status",
                ),
                access=("hr",),
                keywords="reports admin documents",
            ),
            NavItem(
                key="analytics",
                label="Analytics",
                icon="bi-graph-up",
                url_name="analytics",
                match=("analytics", "reports", "export_attendance_csv"),
                access=("hr",),
                keywords="reports charts trends analytics",
            ),
        ),
    ),
    NavSection(
        key="finance",
        label="Finance",
        items=(
            NavItem(
                key="finance",
                label="Finance overview",
                icon="bi-cash-stack",
                url_name="finance_dashboard",
                match=("finance_dashboard",),
                access=("payroll",),
                keywords="money payroll finance",
            ),
            NavItem(
                key="payroll",
                label="Payroll runs",
                icon="bi-receipt",
                url_name="payroll_runs",
                match=(
                    "payroll_runs",
                    "payroll_run_create",
                    "payroll_run_detail",
                    "payroll_run_generate",
                    "payroll_run_approve",
                    "payroll_run_mark_paid",
                    "payslip_detail",
                ),
                access=("payroll",),
                keywords="salary payslips payroll runs",
            ),
            NavItem(
                key="readiness",
                label="Payroll readiness",
                icon="bi-clipboard2-check",
                url_name="finance_payroll_readiness",
                match=("finance_payroll_readiness",),
                access=("payroll",),
                keywords="payroll checks readiness",
            ),
        ),
    ),
    NavSection(
        key="company",
        label="Company",
        items=(
            NavItem(
                key="organizations",
                label="Organizations",
                icon="bi-buildings",
                url_name="organization_list",
                match=("organization_list", "organization_create", "organization_edit"),
                access=("hr",),
                keywords="companies workspace switch",
            ),
            NavItem(
                key="settings",
                label="Settings",
                icon="bi-sliders",
                url_name="organization_settings",
                match=(
                    "organization_settings",
                    "organization_departments",
                    "organization_categories",
                    "organization_attendance_settings",
                    "organization_birthday_message_template",
                    "organization_leave_types",
                    "organization_leave_type_edit",
                    "organization_leave_type_delete",
                ),
                access=("hr",),
                keywords="configuration company preferences",
            ),
            NavItem(
                key="branding",
                label="Company branding",
                icon="bi-palette",
                url_name="organization_branding",
                match=("organization_branding",),
                access=("hr",),
                keywords="logo colour color theme navigation",
            ),
            NavItem(
                key="kiosk",
                label="Kiosk view",
                icon="bi-qr-code",
                url_name="organization_kiosk",
                match=(),
                access=("hr",),
                keywords="kiosk clock terminal",
                external=True,
            ),
        ),
    ),
)


def _access_flags(user, organization):
    return {
        "self_service": bool(
            getattr(user, "employee_profile", None)
            and (
                organization is None
                or user.employee_profile.organization_id == organization.pk
            )
        ),
        "hr": user_has_hr_access(user, organization),
        "manager": user_has_manager_access(user, organization),
        "payroll": user_has_payroll_access(user, organization),
    }


def _item_url(item, organization):
    if item.url_name == "organization_kiosk":
        if organization is not None:
            return reverse("organization_kiosk", args=[organization.slug])
        return reverse("kiosk")
    return reverse(item.url_name)


def build_navigation(user, organization):
    """Return visible nav sections and a flat page map for the current user."""
    flags = _access_flags(user, organization)
    sections = []
    page_map = {}
    for section in NAV_SECTIONS:
        visible_items = []
        for item in section.items:
            if item.access and not any(flags.get(access) for access in item.access):
                continue
            try:
                url = _item_url(item, organization)
            except NoReverseMatch:
                continue
            page = {
                "key": item.key,
                "label": item.label,
                "group": section.label,
                "group_key": section.key,
                "icon": item.icon,
                "url": url,
                "keywords": item.keywords,
                "external": item.external,
                "match": item.match,
            }
            page_map[item.key] = page
            visible_items.append(page)
        if visible_items:
            sections.append(
                {
                    "key": section.key,
                    "label": section.label,
                    "items": visible_items,
                }
            )
    return sections, page_map


def active_page_for(request, page_map):
    match = getattr(request, "resolver_match", None)
    url_name = getattr(match, "url_name", None)
    if not url_name:
        return None
    for page in page_map.values():
        if url_name in page["match"]:
            return page
    return None


def _favorites(user, organization, page_map):
    if organization is None:
        return []
    rows = (
        FavoritePage.objects.filter(user=user, organization=organization)
        .order_by("-created_at")
        .values_list("page_key", flat=True)
    )
    favorites = []
    seen = set()
    for key in rows:
        if key in page_map and key not in seen:
            seen.add(key)
            favorites.append(page_map[key])
    return favorites


def _display_name(user):
    employee = getattr(user, "employee_profile", None)
    if employee is not None:
        full_name = getattr(employee, "full_name", "") or ""
        if full_name.strip():
            return full_name.strip()
    full_name = (user.get_full_name() or "").strip()
    return full_name or user.username


def _initials(display_name, username):
    parts = [part for part in display_name.replace(".", " ").split() if part]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return (username or "?")[:2].upper()


def shell_context(request, organization=None):
    """Template context for the app shell. Safe to call without an organisation."""
    if organization is None:
        organization = get_active_organization(request)
    sections, page_map = build_navigation(request.user, organization)
    active_page = active_page_for(request, page_map)
    favorites = _favorites(request.user, organization, page_map)
    display_name = _display_name(request.user)
    profile_url = reverse("employee_my_profile") if getattr(
        request.user, "employee_profile", None
    ) else ""
    home_page = page_map.get("overview") or next(iter(page_map.values()), None)

    return {
        "shell_sections": sections,
        "shell_page_map": page_map,
        "shell_active_page": active_page,
        "shell_home_url": home_page["url"] if home_page else "/",
        "shell_favorites": favorites,
        "shell_is_favorite": bool(
            active_page and any(
                favorite["key"] == active_page["key"] for favorite in favorites
            )
        ),
        "shell_user_name": display_name,
        "shell_user_initials": _initials(display_name, request.user.username),
        "shell_organization_initials": _initials(
            organization.name if organization is not None else "DIGI HR", ""
        ),
        "shell_profile_url": profile_url,
        "shell_recent_storage_key": "digi02hr:recent:%s"
        % (organization.pk if organization is not None else "global"),
        "shell_unread_notifications": 0,
    }


@login_required
def global_search(request):
    """Search the visible page registry. Returns at most eight real pages."""
    query = (request.GET.get("q") or "").strip()[:80]
    organization = get_active_organization(request)
    _, page_map = build_navigation(request.user, organization)

    results = []
    if len(query) >= 2:
        tokens = [token for token in query.lower().split() if token]
        scored = []
        for order, page in enumerate(page_map.values()):
            label = page["label"].lower()
            group = page["group"].lower()
            haystack = " ".join(
                (label, group, page["key"].replace("_", " "), page["keywords"])
            ).lower()
            if not all(token in haystack for token in tokens):
                continue
            score = 0
            if label == query.lower():
                score += 100
            elif label.startswith(query.lower()):
                score += 60
            elif tokens and label.startswith(tokens[0]):
                score += 30
            if all(token in label for token in tokens):
                score += 20
            if all(token in group for token in tokens):
                score += 10
            scored.append((score, order, page))
        scored.sort(key=lambda row: (-row[0], row[1]))
        results = [
            {
                "key": page["key"],
                "label": page["label"],
                "group": page["group"],
                "icon": page["icon"],
                "url": page["url"],
            }
            for _, _, page in scored[:8]
        ]

    return JsonResponse(
        {
            "query": query,
            "results": results,
            "min_length": 2,
        }
    )


@login_required
@require_POST
def toggle_favorite(request):
    """Add or remove the current page from the signed-in user's favorites."""
    organization = get_active_organization(request)
    if organization is None:
        return JsonResponse({"error": "No active organisation."}, status=400)

    page_key = (request.POST.get("page_key") or "").strip()
    if not page_key:
        return JsonResponse({"error": "Missing page."}, status=400)

    _, page_map = build_navigation(request.user, organization)
    page = page_map.get(page_key)
    if page is None:
        return JsonResponse({"error": "Unknown page."}, status=404)

    favorite, created = FavoritePage.objects.get_or_create(
        user=request.user,
        organization=organization,
        page_key=page_key,
    )
    if not created:
        favorite.delete()

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "favorited": created,
                "page_key": page_key,
                "label": page["label"],
                "icon": page["icon"],
                "group": page["group"],
                "url": page["url"],
            }
        )

    if created:
        messages.success(request, f"{page['label']} added to favorites.")
    else:
        messages.info(request, f"{page['label']} removed from favorites.")
    return redirect(page["url"])
