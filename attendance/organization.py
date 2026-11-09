from .models import (
    Organization,
    OrganizationMembership,
    Category,
    Department,
    AttendanceExceptionType,
    AttendanceSettings,
    LeaveType,
)


DEFAULT_ORGANIZATION_NAME = 'Digi02TechSystem'
DEFAULT_ORGANIZATION_SLUG = 'digi02techsystem'
HR_ROLES = {'owner', 'hr_admin'}
PAYROLL_ROLES = {'owner', 'hr_admin', 'payroll_officer'}
MANAGER_ROLES = {'owner', 'hr_admin', 'manager'}
VIEWER_ROLES = {'owner', 'hr_admin', 'manager', 'payroll_officer', 'viewer'}
DEFAULT_CATEGORIES = [
    {'name': 'Staff', 'code': 'STAFF', 'icon': 'bi-person-badge', 'color': 'primary'},
    {'name': 'Management', 'code': 'MANAGEMENT', 'icon': 'bi-diagram-3', 'color': 'secondary'},
    {'name': 'Intern', 'code': 'INTERN', 'icon': 'bi-mortarboard', 'color': 'success'},
    {'name': 'Student', 'code': 'STUDENT', 'icon': 'bi-backpack', 'color': 'info'},
]


def get_default_organization():
    organization, _ = Organization.objects.get_or_create(
        slug=DEFAULT_ORGANIZATION_SLUG,
        defaults={'name': DEFAULT_ORGANIZATION_NAME},
    )
    return organization


def get_user_organizations(user):
    if not user.is_authenticated:
        return Organization.objects.none()
    return Organization.objects.filter(
        memberships__user=user,
        memberships__is_active=True,
        is_active=True,
    ).distinct().order_by('name')


def user_has_hr_access(user, organization=None):
    if not user.is_authenticated:
        return False
    memberships = user.organization_memberships.filter(
        is_active=True,
        organization__is_active=True,
        role__in=HR_ROLES,
    )
    if organization is not None:
        memberships = memberships.filter(organization=organization)
    return memberships.exists()


DIGIDOC_ROLES = {'owner', 'hr_admin', 'manager', 'payroll_officer', 'employee'}


def user_has_digidoc_access(user, organization=None):
    """DigiDoc access is granted only by an active, explicit membership."""
    if not user.is_authenticated:
        return False
    memberships = user.organization_memberships.filter(is_active=True, organization__is_active=True, role__in=DIGIDOC_ROLES)
    if organization is not None:
        memberships = memberships.filter(organization=organization)
    if memberships.filter(role__in=HR_ROLES).exists():
        return True
    return memberships.filter(organization__allow_staff_digidoc=True).exists()


def user_has_payroll_access(user, organization=None):
    if not user.is_authenticated:
        return False
    memberships = user.organization_memberships.filter(
        is_active=True,
        organization__is_active=True,
        role__in=PAYROLL_ROLES,
    )
    if organization is not None:
        memberships = memberships.filter(organization=organization)
    return memberships.exists()


def user_has_viewer_access(user, organization=None):
    if not user.is_authenticated:
        return False
    memberships = user.organization_memberships.filter(
        is_active=True,
        organization__is_active=True,
        role='viewer',
    )
    if organization is not None:
        memberships = memberships.filter(organization=organization)
    return memberships.exists()


def user_has_manager_access(user, organization=None):
    if not user.is_authenticated:
        return False
    if user_has_hr_access(user, organization):
        return True
    employee = getattr(user, 'employee_profile', None)
    if not employee:
        return False
    memberships = user.organization_memberships.filter(
        organization_id=employee.organization_id,
        is_active=True,
        organization__is_active=True,
        role='manager',
    )
    if organization is not None:
        memberships = memberships.filter(organization=organization)
    if not memberships.exists():
        return False
    direct_reports = employee.direct_reports.filter(is_active=True)
    if organization is not None:
        direct_reports = direct_reports.filter(organization=organization)
    return direct_reports.exists()


def is_employee_self_service_user(user):
    if not user.is_authenticated or not hasattr(user, 'employee_profile'):
        return False
    if not user.organization_memberships.filter(
        organization_id=user.employee_profile.organization_id,
        is_active=True,
        organization__is_active=True,
    ).exists():
        return False
    return not (
        user_has_hr_access(user)
        or user_has_payroll_access(user)
        or user_has_manager_access(user)
        or user_has_viewer_access(user)
    )


def ensure_default_membership(user):
    """Legacy helper: never provision company access from Django staff flags."""
    if not user.is_authenticated:
        return None
    return get_user_organizations(user).first()


def ensure_default_categories(organization):
    for category_data in DEFAULT_CATEGORIES:
        Category.objects.get_or_create(
            organization=organization,
            code=category_data['code'],
            defaults=category_data,
        )


def setup_default_organization_records(organization):
    ensure_default_categories(organization)

    departments = [
        {'name': 'Accounting', 'code': 'ACCT'},
        {'name': 'Administration', 'code': 'ADMIN'},
        {'name': 'IT', 'code': 'TECH'},
    ]
    for department_data in departments:
        Department.objects.get_or_create(
            organization=organization,
            code=department_data['code'],
            defaults=department_data,
        )

    exception_types = [
        ('authorized_absence', 'Authorized Absence', 'Approved time away from work.', 'info'),
        ('compassionate_leave', 'Compassionate Leave', 'Approved leave for bereavement or urgent family matters.', 'secondary'),
        ('half_day', 'Half Day', 'Approved half-day exception.', 'warning'),
        ('leave', 'Leave', 'Approved leave day or leave period.', 'success'),
        ('maternity_leave', 'Maternity Leave', 'Approved maternity leave period.', 'danger'),
        ('paternity_leave', 'Paternity Leave', 'Approved paternity leave period.', 'primary'),
        ('public_holiday', 'Public Holiday', 'Company-recognized public holiday.', 'info'),
        ('remote', 'Remote Work', 'Approved remote work day.', 'primary'),
        ('sick', 'Sick Day', 'Employee is unavailable due to illness.', 'danger'),
        ('study_leave', 'Study Leave', 'Approved leave for exams, study, or professional learning.', 'warning'),
        ('training', 'Training', 'Employee is away for training or development.', 'info'),
    ]
    for code, name, description, color in exception_types:
        AttendanceExceptionType.objects.get_or_create(
            organization=organization,
            code=code,
            defaults={
                'name': name,
                'description': description,
                'color': color,
                'is_active': True,
            },
        )

    leave_types = [
        ('annual_leave', 'Annual Leave', 21, 'success', False, True),
        ('sick_leave', 'Sick Leave', 10, 'danger', True, True),
        ('study_leave', 'Study Leave', 5, 'warning', False, True),
        ('compassionate_leave', 'Compassionate Leave', 5, 'secondary', False, True),
        ('maternity_leave', 'Maternity Leave', 90, 'danger', True, True),
        ('paternity_leave', 'Paternity Leave', 14, 'primary', False, True),
        ('unpaid_leave', 'Unpaid Leave', 0, 'secondary', False, False),
    ]
    for code, name, entitlement, color, requires_attachment, is_paid in leave_types:
        LeaveType.objects.get_or_create(
            organization=organization,
            code=code,
            defaults={
                'name': name,
                'annual_entitlement_days': entitlement,
                'color': color,
                'requires_attachment': requires_attachment,
                'is_paid': is_paid,
                'is_active': True,
            },
        )

    AttendanceSettings.objects.get_or_create(organization=organization)


def get_active_organization(request):
    if not request.user.is_authenticated or request.user.is_superuser:
        request.session.pop('active_organization_id', None)
        return None
    organizations = get_user_organizations(request.user)
    organization_id = request.session.get('active_organization_id')

    if organization_id:
        organization = organizations.filter(pk=organization_id).first()
        if organization:
            return organization
        request.session.pop('active_organization_id', None)

    organization = organizations.first()

    if organization:
        request.session['active_organization_id'] = organization.pk
    return organization
