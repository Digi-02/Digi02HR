import hmac
import mimetypes
from django.conf import settings
from django.core.paginator import EmptyPage, Paginator
from django.db.models import Count, Q
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import AttendanceRecord, Employee, Organization


SKILL_FIELDS = {
    "html_css": "skill_html_css",
    "javascript": "skill_javascript",
    "python": "skill_python",
    "java": "skill_java",
    "c_cpp": "skill_c_cpp",
    "django": "skill_django",
    "react": "skill_react",
    "nodejs": "skill_nodejs",
    "ui_ux": "skill_ui_ux",
    "networking": "skill_networking",
    "cybersecurity": "skill_cybersecurity",
    "other": "skill_other",
}
ORDERING = {
    "name": ("first_name", "last_name", "employee_id"),
    "-name": ("-first_name", "-last_name", "employee_id"),
    "employee_id": ("employee_id",),
    "-employee_id": ("-employee_id",),
    "department": ("department__name", "first_name", "last_name", "employee_id"),
    "-department": ("-department__name", "first_name", "last_name", "employee_id"),
    "position": ("position", "first_name", "last_name", "employee_id"),
    "-position": ("-position", "first_name", "last_name", "employee_id"),
    "updated_at": ("updated_at", "employee_id"),
    "-updated_at": ("-updated_at", "employee_id"),
}


def error_response(code, message, status, details=None):
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    return JsonResponse({"api_version": "v1", "error": error}, status=status)


def _positive_int(value, name, default, maximum=None):
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer.")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{name} must not exceed {maximum}.")
    return parsed


def _photo_url(request, employee):
    if not employee.profile_photo:
        return None
    return request.build_absolute_uri(reverse('technical_command_employee_photo', args=[employee.pk]))


@require_GET
def technical_command_employee_photo(request, employee_id):
    organization, auth_error = _authenticated_organization(request)
    if auth_error:
        return auth_error
    employee = get_object_or_404(Employee, pk=employee_id, organization=organization)
    if not employee.profile_photo:
        return error_response('photo_not_found', 'The profile photo is unavailable.', 404)
    try:
        file_object = employee.profile_photo.open('rb')
    except (OSError, ValueError):
        return error_response('photo_not_found', 'The profile photo is unavailable.', 404)
    response = FileResponse(file_object, content_type=mimetypes.guess_type(employee.profile_photo.name)[0] or 'application/octet-stream')
    response['Cache-Control'] = 'private, max-age=300'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _serialize_employee(request, employee):
    manager = employee.line_manager
    skills = {
        label: getattr(employee, field)
        for label, field in SKILL_FIELDS.items()
        if getattr(employee, field)
    }
    if employee.other_technical_skill:
        skills["other_name"] = employee.other_technical_skill
    return {
        "employee_id": employee.employee_id,
        "first_name": employee.first_name,
        "middle_name": employee.middle_name,
        "last_name": employee.last_name,
        "full_name": employee.full_name,
        "work_email": employee.email,
        "profile_photo_url": _photo_url(request, employee),
        "employment_category": {"code": employee.category.code, "name": employee.category.name},
        "employment_status": employee.employment_status,
        "department": (
            {"id": employee.department_id, "code": employee.department.code, "name": employee.department.name}
            if employee.department else None
        ),
        "position": employee.position,
        "line_manager": (
            {"employee_id": manager.employee_id, "full_name": manager.full_name} if manager else None
        ),
        "technical_skills": skills,
        "updated_at": employee.updated_at.isoformat(),
    }


def _authenticated_organization(request):
    configured_key = settings.TECHNICAL_COMMAND_API_KEY
    configured_slug = settings.TECHNICAL_COMMAND_ORGANIZATION_SLUG
    if not configured_key or not configured_slug:
        return None, error_response("integration_not_configured", "The integration is not configured.", 503)
    authorization = request.headers.get("Authorization", "")
    prefix = "Api-Key "
    if not authorization.startswith(prefix):
        return None, error_response("authentication_required", "A service API key is required.", 401)
    supplied_key = authorization[len(prefix):].strip()
    if not supplied_key or not hmac.compare_digest(supplied_key, configured_key):
        return None, error_response("invalid_api_key", "The service API key is invalid.", 403)
    try:
        return Organization.objects.get(slug=configured_slug, is_active=True), None
    except Organization.DoesNotExist:
        return None, error_response("organization_not_found", "The configured organisation is unavailable.", 503)


@require_GET
def technical_command_people_api(request):
    organization, auth_error = _authenticated_organization(request)
    if auth_error:
        return auth_error

    try:
        page_number = _positive_int(request.GET.get("page"), "page", 1)
        page_size = _positive_int(
            request.GET.get("page_size"),
            "page_size",
            settings.TECHNICAL_COMMAND_API_DEFAULT_PAGE_SIZE,
            settings.TECHNICAL_COMMAND_API_MAX_PAGE_SIZE,
        )
    except ValueError as exc:
        return error_response("invalid_query", str(exc), 400)

    ordering = request.GET.get("ordering", "name")
    if ordering not in ORDERING:
        return error_response(
            "invalid_query", "Unsupported ordering value.", 400,
            {"ordering": sorted(ORDERING)},
        )

    base = Employee.objects.filter(
        organization=organization, is_active=True, employment_status="active"
    ).select_related("category", "department", "line_manager")
    summary = {
        "total_active_people": base.count(),
        "by_department": list(
            base.values("department_id", "department__code", "department__name")
            .annotate(count=Count("id")).order_by("department__name")
        ),
        "by_category": list(
            base.values("category__code", "category__name")
            .annotate(count=Count("id")).order_by("category__name")
        ),
    }

    queryset = base
    search = request.GET.get("search", "").strip()
    if search:
        queryset = queryset.filter(
            Q(employee_id__icontains=search) | Q(first_name__icontains=search)
            | Q(middle_name__icontains=search) | Q(last_name__icontains=search)
            | Q(email__icontains=search) | Q(position__icontains=search)
        )
    department = request.GET.get("department", "").strip()
    if department:
        department_filter = Q(department__code__iexact=department)
        if department.isdigit():
            department_filter |= Q(department_id=int(department))
        queryset = queryset.filter(department_filter)
    queryset = queryset.order_by(*ORDERING[ordering])

    paginator = Paginator(queryset, page_size)
    try:
        page = paginator.page(page_number)
    except EmptyPage:
        return error_response("invalid_query", "Requested page does not exist.", 400)

    def page_url(number):
        if number is None:
            return None
        params = request.GET.copy()
        params["page"] = number
        return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

    return JsonResponse({
        "api_version": "v1",
        "organization": {"slug": organization.slug, "name": organization.name},
        "summary": summary,
        "pagination": {
            "page": page.number, "page_size": page_size, "total_pages": paginator.num_pages,
            "total_results": paginator.count,
            "next": page_url(page.next_page_number()) if page.has_next() else None,
            "previous": page_url(page.previous_page_number()) if page.has_previous() else None,
        },
        "results": [_serialize_employee(request, employee) for employee in page.object_list],
    })


@require_GET
def technical_command_attendance_today_api(request):
    organization, auth_error = _authenticated_organization(request)
    if auth_error:
        return auth_error

    today = timezone.localdate()
    employees = Employee.objects.filter(
        organization=organization, is_active=True, employment_status="active"
    ).select_related("department").order_by("first_name", "last_name", "employee_id")
    records = AttendanceRecord.objects.filter(
        organization=organization, employee__in=employees, check_in_time__date=today
    ).select_related("employee").order_by("employee_id", "-check_in_time")
    latest_by_employee = {}
    late_employee_ids = set()
    for record in records:
        latest_by_employee.setdefault(record.employee_id, record)
        if record.is_late:
            late_employee_ids.add(record.employee_id)

    results = []
    checked_in = checked_out = late = 0
    for employee in employees:
        record = latest_by_employee.get(employee.id)
        if employee.id in late_employee_ids:
            late += 1
        if record is None:
            status = "not_checked_in"
        elif record.check_out_time is not None:
            status = "checked_out"
            checked_out += 1
        elif employee.id in late_employee_ids:
            status = "late"
            checked_in += 1
        else:
            status = "checked_in"
            checked_in += 1
        results.append({
            "employee_id": employee.employee_id,
            "full_name": employee.full_name,
            "department": employee.department.name if employee.department else None,
            "status": status,
            "check_in_time": timezone.localtime(record.check_in_time).isoformat() if record else None,
            "check_out_time": timezone.localtime(record.check_out_time).isoformat() if record and record.check_out_time else None,
            "hours_worked": record.hours_worked if record else None,
            "is_late": employee.id in late_employee_ids,
        })

    total = len(results)
    return JsonResponse({
        "api_version": "v1",
        "organization": {"slug": organization.slug, "name": organization.name},
        "date": today.isoformat(),
        "summary": {
            "total_active_people": total,
            "checked_in": checked_in,
            "checked_out": checked_out,
            "late": late,
            "not_checked_in": total - checked_in - checked_out,
        },
        "results": results,
        "updated_at": timezone.now().isoformat(),
    })
