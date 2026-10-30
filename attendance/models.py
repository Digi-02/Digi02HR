# attendance/models.py

from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import uuid


def private_letterhead_path(instance, filename):
    """Ignore the client filename and store with a random, detected extension."""
    import uuid

    extension = 'jpg' if instance.image_format == 'jpeg' else 'png'
    return f"letterheads/{instance.organization_id}/{uuid.uuid4().hex}.{extension}"


def private_digidoc_image_path(instance, filename):
    extension = 'jpg' if instance.image_format == 'jpeg' else 'png'
    return f"digidoc_assets/{instance.organization_id}/{uuid.uuid4().hex}.{extension}"


def local_date_range_filter(field_name, target_date):
    current_tz = timezone.get_current_timezone()
    start_at = timezone.make_aware(datetime.combine(target_date, time.min), current_tz)
    end_at = timezone.make_aware(datetime.combine(target_date + timedelta(days=1), time.min), current_tz)
    return {
        f'{field_name}__gte': start_at,
        f'{field_name}__lt': end_at,
    }


def organization_timezone_name(organization):
    name = getattr(organization, 'timezone', '') if organization else ''
    if name:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(name)
            return name
        except Exception:
            pass
    return timezone.get_default_timezone_name()


def organization_now(organization):
    from zoneinfo import ZoneInfo
    return timezone.now().astimezone(ZoneInfo(organization_timezone_name(organization)))


def organization_today(organization):
    return organization_now(organization).date()


def organization_date_range_filter(field_name, target_date, organization):
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(organization_timezone_name(organization))
    start_at = timezone.make_aware(datetime.combine(target_date, time.min), tz)
    end_at = timezone.make_aware(datetime.combine(target_date + timedelta(days=1), time.min), tz)
    return {
        f'{field_name}__gte': start_at,
        f'{field_name}__lt': end_at,
    }


def validate_iana_timezone(value):
    from zoneinfo import ZoneInfo
    from django.core.exceptions import ValidationError
    try:
        ZoneInfo(value)
    except Exception:
        raise ValidationError('Enter a valid IANA timezone, e.g. Africa/Lagos.')


def employee_profile_photo_path(instance, filename):
    return f"employees/{instance.organization_id or 'pending'}/profile_photos/{filename}"


def employee_document_path(instance, filename):
    employee = instance.employee
    return f"employees/{employee.organization_id}/documents/{employee.employee_id}/{filename}"


from django.core.validators import RegexValidator


BRAND_COLOR_VALIDATOR = RegexValidator(
    regex=r'^#[0-9A-Fa-f]{6}$',
    message='Enter a valid hex color like #3B5BFF.',
)


def organization_logo_path(instance, filename):
    import uuid

    ext = (filename.rsplit('.', 1)[-1] if '.' in filename else 'png').lower()
    if ext not in {'png', 'jpg', 'jpeg', 'webp'}:
        ext = 'png'
    if ext == 'jpg':
        ext = 'jpeg'
    return f"organizations/{instance.pk or 'pending'}/logo_{uuid.uuid4().hex[:12]}.{ext}"


class Organization(models.Model):
    """A company or institution using the HR platform."""

    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    industry = models.CharField(max_length=100, blank=True)
    company_size = models.CharField(max_length=30, blank=True)
    country = models.CharField(max_length=100, blank=True)
    logo = models.ImageField(upload_to=organization_logo_path, blank=True, null=True)
    logo_is_light = models.BooleanField(
        default=False,
        help_text='Whether the logo artwork is light (needs a dark tile). Set automatically on upload.',
    )
    brand_color = models.CharField(
        max_length=7, default='#0A0A0A', validators=[BRAND_COLOR_VALIDATOR]
    )
    DASHBOARD_APPEARANCE_CHOICES = [
        ('brand', 'DIGI HR brand'),
        ('white', 'White and neutral'),
    ]
    dashboard_appearance = models.CharField(
        max_length=12, choices=DASHBOARD_APPEARANCE_CHOICES, default='brand'
    )
    timezone = models.CharField(max_length=50, default='Africa/Lagos', validators=[validate_iana_timezone])
    NAV_STYLE_CHOICES = [
        ('clean', 'Clean'),
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('teal', 'Evergreen'),
        ('brand', 'Company Brand'),
        ('custom', 'Custom'),
    ]
    NAV_HIGHLIGHT_STYLE_CHOICES = [
        ('rounded_pill', 'Rounded Pill'),
        ('soft_pill', 'Soft Pill'),
        ('minimal', 'Minimal Indicator'),
        ('outline', 'Outline'),
        ('custom', 'Custom Highlight'),
    ]
    NAV_HIGHLIGHT_SOURCE_CHOICES = [
        ('auto', 'Default Black'),
        ('accent', 'Company Brand Colour'),
        ('custom', 'Custom Colour'),
    ]
    nav_style = models.CharField(max_length=20, choices=NAV_STYLE_CHOICES, default='clean')
    nav_bg_color = models.CharField(
        max_length=7, default='#0A0A0A', validators=[BRAND_COLOR_VALIDATOR]
    )
    nav_highlight_style = models.CharField(
        max_length=20, choices=NAV_HIGHLIGHT_STYLE_CHOICES, default='rounded_pill'
    )
    nav_highlight_source = models.CharField(
        max_length=20, choices=NAV_HIGHLIGHT_SOURCE_CHOICES, default='auto'
    )
    nav_highlight_color = models.CharField(
        max_length=7, default='#111111', validators=[BRAND_COLOR_VALIDATOR]
    )
    nav_unhovered_highlight_color = models.CharField(
        max_length=7, blank=True, default='', validators=[BRAND_COLOR_VALIDATOR]
    )
    nav_text_color = models.CharField(
        max_length=7, blank=True, default='', validators=[BRAND_COLOR_VALIDATOR]
    )
    nav_muted_color = models.CharField(
        max_length=7, blank=True, default='', validators=[BRAND_COLOR_VALIDATOR]
    )
    nav_hover_bg = models.CharField(
        max_length=7, blank=True, default='', validators=[BRAND_COLOR_VALIDATOR]
    )
    nav_hover_fg = models.CharField(
        max_length=7, blank=True, default='', validators=[BRAND_COLOR_VALIDATOR]
    )
    nav_active_icon_bg = models.CharField(
        max_length=7, blank=True, default='', validators=[BRAND_COLOR_VALIDATOR]
    )
    nav_active_icon_fg = models.CharField(
        max_length=7, blank=True, default='', validators=[BRAND_COLOR_VALIDATOR]
    )
    nav_customized = models.BooleanField(default=False)
    is_suspended = models.BooleanField(default=False)
    suspended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    # Setup wizard tracking. setup_completed=True means the company has finished
    # its initial setup and will not be redirected into the wizard.
    setup_completed = models.BooleanField(default=False)
    setup_completed_steps = models.JSONField(default=list, blank=True)
    setup_current_step = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class CompanyLetterhead(models.Model):
    """Private, re-encoded page artwork and its print layout settings."""

    FIT_CHOICES = [('fit', 'Fit to page'), ('fill', 'Fill page')]
    PAGE_MODE_CHOICES = [('every', 'Every page'), ('first', 'First page only')]

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name='letterhead'
    )
    from .storage import PrivateLetterheadStorage
    image = models.FileField(upload_to=private_letterhead_path, storage=PrivateLetterheadStorage())
    image_format = models.CharField(max_length=4, choices=[('png', 'PNG'), ('jpeg', 'JPEG')])
    image_width = models.PositiveIntegerField()
    image_height = models.PositiveIntegerField()
    scale_mode = models.CharField(max_length=4, choices=FIT_CHOICES, default='fit')
    default_page_mode = models.CharField(max_length=8, choices=PAGE_MODE_CHOICES, default='every')
    margin_top_mm = models.PositiveSmallIntegerField(default=40)
    margin_bottom_mm = models.PositiveSmallIntegerField(default=30)
    margin_left_mm = models.PositiveSmallIntegerField(default=20)
    margin_right_mm = models.PositiveSmallIntegerField(default=20)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.organization.name} letterhead"


class CompanyLetterheadUpload(models.Model):
    """Upload attempts for per-user rate limiting."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class DigiDocDocument(models.Model):
    """A company-scoped DigiDoc document stored as validated editor JSON."""

    PAGE_MODE_CHOICES = [('every', 'Every page'), ('first', 'First page only')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='digidoc_documents')
    title = models.CharField(max_length=200, default='Untitled document')
    content_json = models.JSONField(default=dict, blank=True)
    letterhead_enabled = models.BooleanField(default=False)
    letterhead_page_mode = models.CharField(max_length=8, choices=PAGE_MODE_CHOICES, default='every')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='digidoc_documents')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['organization', '-updated_at'])]

    def __str__(self):
        return self.title


class DigiDocImageAsset(models.Model):
    """Re-encoded, private company image used by DigiDoc image nodes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='digidoc_image_assets')
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='digidoc_image_assets')
    from .storage import PrivateLetterheadStorage
    image = models.FileField(upload_to=private_digidoc_image_path, storage=PrivateLetterheadStorage())
    image_format = models.CharField(max_length=4, choices=[('png', 'PNG'), ('jpeg', 'JPEG')])
    image_width = models.PositiveIntegerField()
    image_height = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class OrganizationMembership(models.Model):
    """Connects login users to the organizations they can manage."""

    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('hr_admin', 'HR Admin'),
        ('manager', 'Manager'),
        ('employee', 'Employee'),
        ('payroll_officer', 'Payroll Officer'),
        ('viewer', 'Viewer'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='organization_memberships')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='hr_admin')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'organization')
        ordering = ['organization__name', 'user__username']

    def __str__(self):
        return f"{self.user.username} - {self.organization.name}"


class FavoritePage(models.Model):
    """A page a user has starred inside one organisation."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='favorite_pages'
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='favorite_pages'
    )
    page_key = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'organization', 'page_key'],
                name='unique_favorite_page_per_user_org',
            )
        ]
        indexes = [
            models.Index(fields=['user', 'organization']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.organization.name} - {self.page_key}"


class AccessRequest(models.Model):
    """A landing-page request-access submission from a prospective company."""

    STATUS_CHOICES = [
        ('new', 'New'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    company_name = models.CharField(max_length=150, blank=True)
    contact_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    team_size = models.CharField(max_length=30, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_company = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='source_access_requests',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.company_name or self.contact_name} - {self.get_status_display()}"


class PlatformAuditLog(models.Model):
    """Who did what in the platform admin area."""

    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=80)
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='platform_audit_logs',
    )
    detail = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.action} - {self.created_at:%Y-%m-%d %H:%M}"


class PlatformSettings(models.Model):
    """Singleton row for platform-wide settings."""

    support_email = models.EmailField(default='support@digihr.example')
    announcement = models.CharField(max_length=255, blank=True)
    announcement_active = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return 'Platform Settings'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class AuditLog(models.Model):
    """Immutable record of sensitive actions in the HR platform."""

    AREA_CHOICES = [
        ('employee', 'Employee'),
        ('attendance', 'Attendance'),
        ('leave', 'Leave'),
        ('payroll', 'Payroll'),
        ('organization', 'Organization'),
        ('security', 'Security'),
        ('admin_report', 'Admin Report'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='audit_logs')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    area = models.CharField(max_length=30, choices=AREA_CHOICES)
    action = models.CharField(max_length=80)
    target_model = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    summary = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'area', 'created_at']),
            models.Index(fields=['target_model', 'target_id']),
        ]

    def __str__(self):
        return f"{self.get_area_display()} - {self.action} - {self.created_at:%Y-%m-%d %H:%M}"


class Category(models.Model):
    """User categories: Staff, Intern, Student"""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=10)
    icon = models.CharField(max_length=50, help_text="Bootstrap icon name (e.g., bi-person-badge)")
    color = models.CharField(max_length=20, help_text="Bootstrap color class (e.g., primary, success, info)")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']
        unique_together = (
            ('organization', 'code'),
            ('organization', 'name'),
        )
    
    def __str__(self):
        return self.name


class Department(models.Model):
    """Organization departments"""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='departments')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
        unique_together = ('organization', 'code')
    
    def __str__(self):
        return self.name


class Employee(models.Model):
    """Unified model for Staff, Interns, and Students"""
    
    GENDER_CHOICES = [
        ('MALE', 'Male'),
        ('FEMALE', 'Female'),
    ]
    
    TITLE_CHOICES = [
        ('Mr.', 'Mr.'),
        ('Ms', 'Ms'),
        ('Mrs.', 'Mrs.'),
        ('Engr.', 'Engr.'),
        ('Dr.', 'Dr.'),
        ('Prof.', 'Prof.'),
    ]

    MARITAL_STATUS_CHOICES = [
        ('single', 'Single'),
        ('married', 'Married'),
        ('divorced', 'Divorced'),
        ('widowed', 'Widowed'),
    ]

    BLOOD_GROUP_CHOICES = [
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
        ('O+', 'O+'),
        ('O-', 'O-'),
    ]

    GENOTYPE_CHOICES = [
        ('AA', 'AA'),
        ('AS', 'AS'),
        ('AC', 'AC'),
        ('SS', 'SS'),
        ('SC', 'SC'),
    ]

    INTERNSHIP_TYPE_CHOICES = [
        ('siwes', 'SIWES'),
        ('industrial_training', 'Industrial Training (IT)'),
        ('student_internship', 'Student Internship'),
        ('graduate_internship', 'Graduate Internship'),
        ('other', 'Other'),
    ]

    SKILL_LEVEL_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
    ]
    
    EMPLOYMENT_STATUS = [
        ('active', 'Active'),
        ('on_leave', 'On Leave'),
        ('terminated', 'Terminated'),
        ('completed', 'Completed'),  # For interns/students who finished
    ]
    
    # === Identification ===
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='employees')
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='employee_profile')
    employee_id = models.CharField(max_length=20, help_text="Auto-generated ID")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='employees')
    
    # === Personal Information ===
    profile_photo = models.ImageField(upload_to=employee_profile_photo_path, blank=True, null=True)
    title = models.CharField(max_length=10, choices=TITLE_CHOICES, blank=True)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(help_text="Work/primary email used for kiosk check-in")
    personal_email = models.EmailField(blank=True, null=True, help_text="Personal email (for interns/students)")
    phone = models.CharField(max_length=20)
    alternative_phone = models.CharField(max_length=20, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    date_of_birth = models.DateField(null=True, blank=True, help_text="Required for Staff only")
    nationality = models.CharField(max_length=100, blank=True)
    marital_status = models.CharField(max_length=20, choices=MARITAL_STATUS_CHOICES, blank=True)
    religion = models.CharField(max_length=100, blank=True)
    blood_group = models.CharField(max_length=5, choices=BLOOD_GROUP_CHOICES, blank=True)
    genotype = models.CharField(max_length=5, choices=GENOTYPE_CHOICES, blank=True)
    allergies_or_medical_conditions = models.TextField(
        blank=True,
        help_text="Only record emergency-relevant medical information where appropriate.",
    )
    emergency_medical_contact_name = models.CharField(max_length=150, blank=True)
    emergency_medical_contact_relationship = models.CharField(max_length=100, blank=True)
    emergency_medical_contact_phone = models.CharField(max_length=20, blank=True)

    residential_address = models.TextField(blank=True)
    permanent_address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    local_government = models.CharField(max_length=100, blank=True)

    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_relationship = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)

    next_of_kin_name = models.CharField(max_length=150, blank=True)
    next_of_kin_relationship = models.CharField(max_length=100, blank=True)
    next_of_kin_phone = models.CharField(max_length=20, blank=True)
    next_of_kin_email = models.EmailField(blank=True)
    next_of_kin_address = models.TextField(blank=True)
    
    # === Work Information ===
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    position = models.CharField(max_length=100, blank=True, help_text="Job title or role")
    line_manager = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='direct_reports',
        help_text="Line manager or reporting manager",
    )
    
    # === Dates ===
    hire_date = models.DateField(null=True, blank=True, help_text="Staff: Hire date. Intern/Student: Start date")
    end_date = models.DateField(null=True, blank=True, help_text="For interns/students: Expected end date")
    probation_end_date = models.DateField(null=True, blank=True)
    
    # === Intern/Student Specific ===
    institution = models.CharField(max_length=200, blank=True, help_text="University/School name")
    faculty = models.CharField(max_length=150, blank=True)
    academic_department = models.CharField(max_length=150, blank=True)
    qualification_obtained = models.CharField(max_length=150, blank=True)
    field_of_study = models.CharField(max_length=100, blank=True, help_text="Course or program")
    year_of_graduation = models.PositiveIntegerField(null=True, blank=True)
    class_of_degree = models.CharField(max_length=100, blank=True)
    student_id = models.CharField(max_length=50, blank=True, help_text="School ID number")
    current_level = models.CharField(max_length=50, blank=True)
    expected_graduation_date = models.DateField(null=True, blank=True)
    academic_supervisor_name = models.CharField(max_length=150, blank=True)
    academic_supervisor_phone = models.CharField(max_length=20, blank=True)
    academic_supervisor_email = models.EmailField(blank=True)
    internship_type = models.CharField(max_length=30, choices=INTERNSHIP_TYPE_CHOICES, blank=True)
    internship_type_other = models.CharField(max_length=100, blank=True)
    area_of_interest = models.TextField(blank=True)
    area_of_interest_other = models.CharField(max_length=120, blank=True)
    preferred_department = models.CharField(max_length=150, blank=True)
    skill_html_css = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    skill_javascript = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    skill_python = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    skill_java = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    skill_c_cpp = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    skill_django = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    skill_react = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    skill_nodejs = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    skill_ui_ux = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    skill_networking = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    skill_cybersecurity = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    other_technical_skill = models.CharField(max_length=150, blank=True)
    skill_other = models.CharField(max_length=20, choices=SKILL_LEVEL_CHOICES, blank=True)
    relevant_skills_projects = models.TextField(blank=True)
    supervisor = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, 
                                   related_name='supervisees', help_text="Supervising staff member")

    nin_number = models.CharField(max_length=20, blank=True)
    passport_number = models.CharField(max_length=30, blank=True)
    passport_expiry_date = models.DateField(null=True, blank=True)
    tin_number = models.CharField(max_length=30, blank=True)
    drivers_license_number = models.CharField(max_length=50, blank=True)
    work_permit_number = models.CharField(max_length=50, blank=True)
    work_permit_expiry_date = models.DateField(null=True, blank=True)

    # === Payroll Information ===
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_name = models.CharField(max_length=150, blank=True)
    bank_account_number = models.CharField(max_length=30, blank=True)
    bank_branch = models.CharField(max_length=120, blank=True)
    pension_rsa_pin = models.CharField(max_length=50, blank=True)
    pension_fund_administrator = models.CharField(max_length=150, blank=True)
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_allowances = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pension_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # === Status ===
    employment_status = models.CharField(max_length=20, choices=EMPLOYMENT_STATUS, default='active')
    is_active = models.BooleanField(default=True, help_text="Uncheck to disable kiosk access")
    
    # === Metadata ===
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['category', 'first_name', 'last_name']
        unique_together = (
            ('organization', 'employee_id'),
            ('organization', 'email'),
        )
    
    def __str__(self):
        return f"[{self.category.code}] {self.full_name}"
    
    def save(self, *args, **kwargs):
        # Auto-generate employee_id if not set
        if not self.employee_id:
            prefix = self.category.code if self.category else 'USR'
            year = timezone.now().year
            last_emp = Employee.objects.filter(
                organization=self.organization,
                employee_id__startswith=f"{prefix}-{year}"
            ).order_by('-employee_id').first()
            
            if last_emp:
                last_num = int(last_emp.employee_id.split('-')[-1])
                new_num = str(last_num + 1).zfill(3)
            else:
                new_num = '001'
            
            self.employee_id = f"{prefix}-{year}-{new_num}"
        
        # Auto-set title based on gender if not provided
        if not self.title:
            if self.gender == 'MALE':
                self.title = 'Mr.'
            elif self.gender == 'FEMALE':
                self.title = 'Ms'
        
        super().save(*args, **kwargs)
    
    @property
    def full_name(self):
        return " ".join(
            part for part in [self.first_name, self.middle_name, self.last_name] if part
        ).strip()
    
    @property
    def display_name(self):
        """Returns formatted name with title"""
        if self.title:
            return f"{self.title} {self.full_name}"
        return self.full_name
    
    @property
    def is_staff(self):
        return self.category.code == 'STAFF' if self.category else False
    
    @property
    def is_intern(self):
        return self.category.code == 'INTERN' if self.category else False
    
    @property
    def is_student(self):
        return self.category.code == 'STUDENT' if self.category else False
    
    @property
    def is_checked_in_today(self):
        """Check if employee has an open attendance record today (company timezone)"""
        today = organization_today(self.organization)
        return self.attendance_records.filter(
            **organization_date_range_filter('check_in_time', today, self.organization),
            check_out_time__isnull=True
        ).exists()

    @property
    def today_attendance(self):
        """Get today's attendance record if it exists (company timezone)"""
        today = organization_today(self.organization)
        return self.attendance_records.filter(
            **organization_date_range_filter('check_in_time', today, self.organization)
        ).first()
    
    @property
    def work_anniversary_today(self):
        """Check if today is work anniversary (Staff only)"""
        if not self.hire_date or self.category.code != 'STAFF':
            return False
        today = date.today()
        return self.hire_date.month == today.month and self.hire_date.day == today.day
    
    @property
    def years_of_service(self):
        """Calculate years of service (Staff only)"""
        if not self.hire_date:
            return None
        today = date.today()
        years = today.year - self.hire_date.year
        if today.month < self.hire_date.month or (
            today.month == self.hire_date.month and today.day < self.hire_date.day
        ):
            years -= 1
        return years
    
    def get_anniversary_this_week(self):
        """Check if work anniversary is in the next 7 days"""
        if not self.hire_date or self.category.code != 'STAFF':
            return None
        
        today = date.today()
        anniversary_this_year = date(today.year, self.hire_date.month, self.hire_date.day)
        
        days_until = (anniversary_this_year - today).days
        
        if 0 <= days_until <= 7:
            return {
                'date': anniversary_this_year,
                'days_until': days_until,
                'years': self.years_of_service
            }
        return None

    @property
    def gross_pay(self):
        return self.basic_salary + self.housing_allowance + self.transport_allowance + self.other_allowances

    @property
    def total_deductions(self):
        return self.tax_deduction + self.pension_deduction + self.other_deductions

    @property
    def net_pay(self):
        return self.gross_pay - self.total_deductions


class EmployeeEducation(models.Model):
    """Repeatable educational qualifications for an employee."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='educations')
    qualification_obtained = models.CharField(max_length=150)
    institution = models.CharField(max_length=200, blank=True)
    field_of_study = models.CharField(max_length=150, blank=True)
    year_of_graduation = models.PositiveIntegerField(null=True, blank=True)
    class_of_degree = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-year_of_graduation', 'qualification_obtained', 'institution']

    def __str__(self):
        return f"{self.employee.full_name} - {self.qualification_obtained}"


class EmployeeCertification(models.Model):
    """Repeatable professional certifications for an employee."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='certifications')
    certification_name = models.CharField(max_length=150)
    issuing_body = models.CharField(max_length=150, blank=True)
    date_obtained = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_obtained', 'certification_name']

    def __str__(self):
        return f"{self.employee.full_name} - {self.certification_name}"


class EmployeeWorkExperience(models.Model):
    """Repeatable pre-employment work history for an employee."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='work_experiences')
    employer_name = models.CharField(max_length=200)
    job_title = models.CharField(max_length=150, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    reason_for_leaving = models.TextField(blank=True)
    skills_and_competence = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-end_date', '-start_date', 'employer_name']

    def __str__(self):
        return f"{self.employee.full_name} - {self.employer_name}"


class EmployeeDocument(models.Model):
    """Repeatable uploaded documents for an employee profile."""

    DOCUMENT_TYPE_CHOICES = [
        ('contract', 'Employment Contract'),
        ('id', 'Identification Document'),
        ('certificate', 'Certificate / Qualification'),
        ('passport', 'Passport'),
        ('work_permit', 'Work Permit / Visa'),
        ('medical', 'Medical Document'),
        ('payroll', 'Payroll Document'),
        ('other', 'Other'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default='other')
    title = models.CharField(max_length=150)
    file = models.FileField(upload_to=employee_document_path)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at', 'title']

    def __str__(self):
        return f"{self.employee.full_name} - {self.title}"


class OnboardingStage(models.Model):
    """A configurable lane in the HR onboarding pipeline."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='onboarding_stages')
    title = models.CharField(max_length=120)
    code = models.SlugField(max_length=80)
    description = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    color = models.CharField(max_length=20, default='primary', help_text="Bootstrap color class, e.g. primary, warning, info")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'title']
        unique_together = ('organization', 'code')
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['organization', 'order']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.code:
            base_code = slugify(self.title) or 'stage'
            code = base_code
            counter = 2
            existing = OnboardingStage.objects.filter(
                organization=self.organization,
                code=code,
            )
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            while existing.exists():
                code = f'{base_code}-{counter}'
                counter += 1
                existing = OnboardingStage.objects.filter(
                    organization=self.organization,
                    code=code,
                )
                if self.pk:
                    existing = existing.exclude(pk=self.pk)
            self.code = code
        super().save(*args, **kwargs)


class OnboardingTask(models.Model):
    """Checklist item for onboarding a staff member, intern, or student."""

    CATEGORY_CHOICES = [
        ('hr', 'HR'),
        ('it', 'IT / Access'),
        ('documents', 'Documents'),
        ('training', 'Training'),
        ('equipment', 'Equipment'),
        ('manager', 'Manager'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('waived', 'Waived'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='onboarding_tasks')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='onboarding_tasks')
    stage = models.ForeignKey(OnboardingStage, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='hr')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_onboarding_tasks')
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='completed_onboarding_tasks')
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', 'due_date', 'employee__first_name', 'title']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['employee', 'status']),
            models.Index(fields=['stage', 'status']),
            models.Index(fields=['due_date']),
        ]

    def __str__(self):
        return f"{self.employee.full_name} - {self.title}"

    @property
    def is_overdue(self):
        return self.due_date and self.due_date < timezone.localdate() and self.status not in ['completed', 'waived']


class Applicant(models.Model):
    """Pre-employment application record before HR converts a person to employee."""

    STATUS_CHOICES = [
        ('invited', 'Invited'),
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('converted', 'Converted to Employee'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='applicants')
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    gender = models.CharField(max_length=10, choices=Employee.GENDER_CHOICES, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='applicants')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='applicants')
    position = models.CharField(max_length=100, blank=True)
    cover_note = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='invited')
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='invited_applicants')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_applicants')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    employee = models.OneToOneField(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='source_application')
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('organization', 'email')
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return f"{self.full_name} - {self.get_status_display()}"

    @property
    def full_name(self):
        return " ".join(
            part for part in [self.first_name, self.middle_name, self.last_name] if part
        ).strip()


class OnboardingInvitation(models.Model):
    """Secure email invitation for applicants or existing employee setup."""

    INVITATION_TYPE_CHOICES = [
        ('application', 'Application'),
        ('employee_setup', 'Employee Setup'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('opened', 'Opened'),
        ('submitted', 'Submitted'),
        ('accepted', 'Accepted'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='onboarding_invitations')
    invitation_type = models.CharField(max_length=30, choices=INVITATION_TYPE_CHOICES)
    applicant = models.ForeignKey(Applicant, on_delete=models.CASCADE, null=True, blank=True, related_name='invitations')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, null=True, blank=True, related_name='onboarding_invitations')
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='draft')
    message = models.TextField(blank=True)
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_onboarding_invitations')
    sent_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'invitation_type', 'status']),
            models.Index(fields=['token']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return f"{self.get_invitation_type_display()} invitation to {self.email}"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = get_random_string(48)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=14)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return bool(self.expires_at and timezone.now() > self.expires_at)

    @property
    def recipient_name(self):
        if self.applicant:
            return self.applicant.full_name
        if self.employee:
            return self.employee.full_name
        return self.email


class OnboardingParticipant(models.Model):
    """A person moving through the onboarding pipeline."""

    PARTICIPANT_TYPE_CHOICES = [
        ('applicant', 'Applicant'),
        ('employee', 'Employee'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='onboarding_participants')
    stage = models.ForeignKey(OnboardingStage, on_delete=models.PROTECT, related_name='participants')
    applicant = models.OneToOneField(
        Applicant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='onboarding_participant',
    )
    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='onboarding_participant',
    )
    invitation = models.ForeignKey(
        OnboardingInvitation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='participants',
    )
    participant_type = models.CharField(max_length=20, choices=PARTICIPANT_TYPE_CHOICES)
    joining_date = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    moved_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['stage__order', 'created_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['stage', 'status']),
            models.Index(fields=['participant_type']),
        ]

    def __str__(self):
        return f"{self.display_name} - {self.stage.title}"

    @property
    def display_name(self):
        if self.employee:
            return self.employee.full_name
        if self.applicant:
            return self.applicant.full_name
        return 'Unknown participant'

    @property
    def email(self):
        if self.employee:
            return self.employee.email
        if self.applicant:
            return self.applicant.email
        return self.invitation.email if self.invitation else ''

    @property
    def phone(self):
        if self.employee:
            return self.employee.phone
        if self.applicant:
            return self.applicant.phone
        return ''

    @property
    def role(self):
        if self.employee:
            return self.employee.position
        if self.applicant:
            return self.applicant.position
        return ''

    @property
    def source_status(self):
        if self.applicant:
            return self.applicant.get_status_display()
        if self.invitation:
            return self.invitation.get_status_display()
        return self.get_status_display()


class AdminReport(models.Model):
    """Narrative HR/admin feedback report about a person, event, or observation."""

    REPORT_TYPE_CHOICES = [
        ('event', 'Event Report'),
        ('staff_feedback', 'Staff Feedback'),
        ('work_observation', 'Work Observation'),
        ('incident', 'Incident Report'),
        ('commendation', 'Commendation'),
        ('general', 'General Report'),
    ]

    TONE_CHOICES = [
        ('positive', 'Positive'),
        ('neutral', 'Neutral'),
        ('concern', 'Concern'),
        ('urgent', 'Urgent'),
    ]

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('reviewed', 'Reviewed'),
        ('closed', 'Closed'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='admin_reports')
    title = models.CharField(max_length=180)
    report_type = models.CharField(max_length=30, choices=REPORT_TYPE_CHOICES, default='general')
    tone = models.CharField(max_length=20, choices=TONE_CHOICES, default='neutral')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    event_date = models.DateField(default=timezone.localdate)
    related_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_reports',
    )
    related_department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_reports',
    )
    body = models.TextField()
    action_taken = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_admin_reports')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_admin_reports')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-event_date', '-created_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['organization', 'report_type']),
            models.Index(fields=['event_date']),
        ]

    def __str__(self):
        return self.title


class BirthdayMessageLog(models.Model):
    """Tracks yearly birthday messages sent by HR."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='birthday_message_logs')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='birthday_message_logs')
    birthday_year = models.PositiveIntegerField()
    recipient_email = models.EmailField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']
        unique_together = ('organization', 'employee', 'birthday_year')
        indexes = [
            models.Index(fields=['organization', 'birthday_year']),
            models.Index(fields=['employee', 'birthday_year']),
        ]

    def __str__(self):
        return f'{self.employee.full_name} birthday message - {self.birthday_year}'


class AttendanceExceptionType(models.Model):
    """Configurable attendance exception labels managed by HR."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='attendance_exception_types')
    code = models.SlugField(max_length=50)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=20, default='primary', help_text="Bootstrap color class, e.g. primary, warning, info")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = ('organization', 'code')

    def __str__(self):
        return self.name


class AttendanceException(models.Model):
    """Day-based attendance exceptions like leave, sick days, and approved absences."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='attendance_exceptions')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_exceptions')
    exception_type = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date', '-end_date', 'employee__first_name']
        indexes = [
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['employee', 'start_date']),
        ]

    def __str__(self):
        return f"{self.employee.full_name} - {self.get_exception_type_display()}"

    def get_exception_type_display(self):
        exception_type = AttendanceExceptionType.objects.filter(
            organization=self.organization,
            code=self.exception_type,
        ).first()
        if exception_type:
            return exception_type.name
        return self.exception_type.replace('_', ' ').title()

    @property
    def exception_type_color(self):
        exception_type = AttendanceExceptionType.objects.filter(
            organization=self.organization,
            code=self.exception_type,
        ).first()
        return exception_type.color if exception_type else 'primary'

    @property
    def day_count(self):
        return (self.end_date - self.start_date).days + 1


class LeaveType(models.Model):
    """Configurable leave policies for each organization."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='leave_types')
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=50)
    annual_entitlement_days = models.PositiveSmallIntegerField(default=0)
    color = models.CharField(max_length=20, default='success', help_text="Bootstrap color class, e.g. success, warning, info")
    requires_attachment = models.BooleanField(default=False)
    is_paid = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = ('organization', 'code')

    def __str__(self):
        return self.name


class LeaveRequest(models.Model):
    """Employee leave request with a lightweight HR approval workflow."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    MANAGER_APPROVAL_CHOICES = [
        ('pending', 'Pending Manager Review'),
        ('approved', 'Manager Approved'),
        ('rejected', 'Manager Rejected'),
        ('not_required', 'Not Required'),
    ]

    DAY_PART_CHOICES = [
        ('full_day', 'Full Day'),
        ('first_half', 'First Half'),
        ('second_half', 'Second Half'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='leave_requests')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='leave_requests')
    start_date = models.DateField()
    end_date = models.DateField()
    day_part = models.CharField(max_length=20, choices=DAY_PART_CHOICES, default='full_day')
    reason = models.TextField(blank=True)
    manager_approval_status = models.CharField(max_length=20, choices=MANAGER_APPROVAL_CHOICES, default='not_required')
    manager_reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='manager_reviewed_leave_requests')
    manager_reviewed_at = models.DateTimeField(null=True, blank=True)
    manager_review_note = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_leave_requests')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['employee', 'start_date']),
        ]

    def __str__(self):
        return f"{self.employee.full_name} - {self.leave_type.name}"

    @property
    def day_count(self):
        days = (self.end_date - self.start_date).days + 1
        if self.day_part != 'full_day' and days == 1:
            return 0.5
        return days


class PayrollRun(models.Model):
    """A monthly payroll batch for an organization."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('processed', 'Processed'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='payroll_runs')
    title = models.CharField(max_length=150)
    payroll_month = models.DateField(help_text="Use the first day of the payroll month.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_payroll_runs')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_payroll_runs')
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payroll_month', '-created_at']
        unique_together = ('organization', 'payroll_month')

    def __str__(self):
        return f"{self.organization.name} - {self.payroll_month:%B %Y}"

    @property
    def total_gross(self):
        return sum((payslip.gross_pay for payslip in self.payslips.all()), 0)

    @property
    def total_deductions(self):
        return sum((payslip.total_deductions for payslip in self.payslips.all()), 0)

    @property
    def total_net(self):
        return sum((payslip.net_pay for payslip in self.payslips.all()), 0)


class Payslip(models.Model):
    """Generated salary snapshot for one employee in a payroll run."""

    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='payslips')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payslips')
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_allowances = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pension_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_name = models.CharField(max_length=150, blank=True)
    bank_account_number = models.CharField(max_length=30, blank=True)
    pension_rsa_pin = models.CharField(max_length=50, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['employee__first_name', 'employee__last_name']
        unique_together = ('payroll_run', 'employee')

    def __str__(self):
        return f"{self.employee.full_name} - {self.payroll_run.payroll_month:%B %Y}"

    @property
    def gross_pay(self):
        return self.basic_salary + self.housing_allowance + self.transport_allowance + self.other_allowances

    @property
    def total_deductions(self):
        return self.tax_deduction + self.pension_deduction + self.other_deductions

    @property
    def net_pay(self):
        return self.gross_pay - self.total_deductions


class AttendanceRecord(models.Model):
    """Check-in and check-out records for all users"""
    
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='attendance_records')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_records')
    check_in_time = models.DateTimeField()
    check_out_time = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-check_in_time']
        indexes = [
            models.Index(fields=['check_in_time']),
            models.Index(fields=['employee', 'check_in_time']),
        ]
    
    def __str__(self):
        return f"{self.employee.display_name} - {self.check_in_time.strftime('%Y-%m-%d %H:%M')}"
    
    @property
    def hours_worked(self):
        """Calculate hours worked for this record"""
        if self.check_out_time:
            delta = self.check_out_time - self.check_in_time
            return round(delta.total_seconds() / 3600, 2)
        return None
    
    @property
    def is_active(self):
        """Check if this record is still open (no check-out)"""
        return self.check_out_time is None
    
    @property
    def is_late(self):
        """Check if check-in was after the configured late threshold (company timezone)."""
        local_check_in = self.check_in_time.astimezone(
            ZoneInfo(organization_timezone_name(self.organization))
        )
        threshold = AttendanceSettings.get_solo(self.organization).late_threshold
        return local_check_in.time() >= threshold
    
    @property
    def status(self):
        """Return status label"""
        if self.is_active:
            if self.is_late:
                return 'late'
            return 'active'
        return 'completed'


class AttendanceSettings(models.Model):
    """Singleton-like settings for attendance behavior and reminders."""

    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name='attendance_settings')
    workday_start = models.TimeField(default=time(8, 0), help_text="Official workday start time.")
    late_threshold = models.TimeField(default=time(8, 30), help_text="Check-ins at or after this time are marked late.")
    birthday_reminder_days = models.PositiveSmallIntegerField(default=7)
    internship_reminder_days = models.PositiveSmallIntegerField(default=14)
    birthday_message_subject = models.CharField(
        max_length=180,
        default='Happy Birthday, {first_name}! From everyone at {organization_name}',
    )
    birthday_message_body = models.TextField(
        default=(
            'Dear {display_name},\n\n'
            'Happy birthday from all of us at {organization_name}.\n\n'
            'Today, we celebrate you and the value you bring to the team. We hope your day is filled with joy, '
            'good health, and the kind of moments that remind you how appreciated you are.\n\n'
            'Thank you for being part of {organization_name}. We wish you a wonderful birthday and a year ahead '
            'filled with growth, fulfilment, and success.\n\n'
            'Warm regards,\n'
            'HR Team\n'
            '{organization_name}'
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Attendance Settings"
        verbose_name_plural = "Attendance Settings"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def __str__(self):
        return "Attendance Settings"

    @classmethod
    def get_solo(cls, organization=None):
        if organization:
            settings_obj, _ = cls.objects.get_or_create(organization=organization)
            return settings_obj
        settings_obj = cls.objects.first()
        if settings_obj:
            return settings_obj
        default_org, _ = Organization.objects.get_or_create(
            slug='digi02techsystem',
            defaults={'name': 'Digi02TechSystem'},
        )
        return cls.objects.create(organization=default_org)
