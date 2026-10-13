# attendance/views.py - Complete fixed version

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.db.models.deletion import ProtectedError
from email.header import decode_header
from email.utils import parseaddr
from html.parser import HTMLParser
from datetime import datetime, time, timedelta, date
from functools import wraps
import csv
import imaplib
import email
import html
import re

from .models import (
    Employee,
    EmployeeDocument,
    Applicant,
    AdminReport,
    AuditLog,
    AttendanceRecord,
    Category,
    Department,
    AttendanceSettings,
    AttendanceException,
    AttendanceExceptionType,
    LeaveType,
    LeaveRequest,
    OnboardingStage,
    OnboardingParticipant,
    OnboardingTask,
    OnboardingInvitation,
    PayrollRun,
    Payslip,
    Organization,
    OrganizationMembership,
)
from .forms import (
    EmployeeForm,
    ManualAttendanceForm,
    DateFilterForm,
    EmployeeDocumentForm,
    EmployeeEducationFormSet,
    EmployeeCertificationFormSet,
    EmployeeWorkExperienceFormSet,
    EmployeeDocumentFormSet,
    AttendanceExceptionTypeForm,
    OrganizationForm,
    DepartmentForm,
    CategoryForm,
    AttendanceSettingsForm,
    BirthdayMessageTemplateForm,
    LeaveTypeForm,
    LeaveRequestForm,
    LeaveReviewForm,
    OnboardingStageForm,
    OnboardingTaskForm,
    EmployeeAccountForm,
    ApplicantInvitationForm,
    ExistingEmployeeOnboardingInviteForm,
    ApplicantApplicationForm,
    EmployeeOnboardingSetupForm,
    AdminReportForm,
    PayrollRunForm,
)
from .organization import (
    ensure_default_categories,
    get_active_organization,
    get_default_organization,
    get_user_organizations,
    is_employee_self_service_user,
    setup_default_organization_records,
    user_has_hr_access,
    user_has_manager_access,
    user_has_payroll_access,
)


# ==================== AUTHENTICATION VIEWS ====================

def write_audit_log(request, *, organization, area, action, summary, target=None, metadata=None):
    target_model = ''
    target_id = ''
    if target is not None:
        target_model = target.__class__.__name__
        target_id = str(getattr(target, 'pk', '') or '')
    AuditLog.objects.create(
        organization=organization,
        actor=request.user if request.user.is_authenticated else None,
        area=area,
        action=action,
        target_model=target_model,
        target_id=target_id,
        summary=summary,
        metadata=metadata or {},
    )


def send_onboarding_invitation_email(request, invitation):
    invite_url = request.build_absolute_uri(
        reverse('public_onboarding_invitation', kwargs={'token': invitation.token})
    )
    subject = f"{invitation.organization.name} onboarding invitation"
    if invitation.invitation_type == 'application':
        subject = f"{invitation.organization.name} application invitation"
        action_text = 'submit your application'
    else:
        action_text = 'set up your employee profile'

    message_lines = [
        f"Hello {invitation.recipient_name},",
        "",
        f"{invitation.organization.name} has invited you to {action_text}.",
    ]
    if invitation.message:
        message_lines.extend(["", invitation.message])
    message_lines.extend([
        "",
        f"Open this secure link: {invite_url}",
        "",
        "This link is personal to you. Please do not forward it.",
    ])
    send_mail(
        subject,
        "\n".join(message_lines),
        getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
        [invitation.email],
        fail_silently=False,
    )
    invitation.status = 'sent'
    invitation.sent_at = timezone.now()
    invitation.save(update_fields=['status', 'sent_at', 'updated_at'])


def decode_email_header(value):
    if not value:
        return ''
    decoded_parts = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(encoding or 'utf-8', errors='replace'))
        else:
            decoded_parts.append(part)
    return ''.join(decoded_parts)


def format_email_address(value):
    decoded_value = decode_email_header(value)
    name, address = parseaddr(decoded_value)
    name = name.strip().strip('"')
    if name and address and name.lower() != address.lower():
        return f'{name} <{address}>'
    return address or decoded_value


class EmailHTMLTextExtractor(HTMLParser):
    block_tags = {'br', 'div', 'p', 'tr', 'table', 'li', 'ul', 'ol', 'blockquote'}

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.block_tags:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self.block_tags:
            self.parts.append('\n')

    def handle_data(self, data):
        if data:
            self.parts.append(data)

    def text(self):
        text = html.unescape(''.join(self.parts))
        text = re.sub(r'[ \t\r\f\v]+', ' ', text)
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        return text.strip()


def html_to_text(value):
    extractor = EmailHTMLTextExtractor()
    extractor.feed(value or '')
    extractor.close()
    return extractor.text()


def decode_message_part(part):
    payload = part.get_payload(decode=True)
    if not payload:
        return ''
    charset = part.get_content_charset() or 'utf-8'
    return payload.decode(charset, errors='replace').strip()


def message_text_preview(message):
    html_body = ''
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == 'text/plain' and not part.get_content_disposition():
                text_body = decode_message_part(part)
                if text_body:
                    return text_body
            if part.get_content_type() == 'text/html' and not part.get_content_disposition():
                html_body = html_body or decode_message_part(part)
        return html_to_text(html_body)

    body = decode_message_part(message)
    if message.get_content_type() == 'text/html':
        return html_to_text(body)
    return body


def close_imap_mailbox(mail):
    if mail is None:
        return
    try:
        mail.logout()
    except (imaplib.IMAP4.error, OSError, TimeoutError):
        pass


def open_imap_mailbox():
    if not settings.IMAP_HOST or not settings.IMAP_HOST_USER or not settings.IMAP_HOST_PASSWORD:
        return None, 'IMAP is not configured yet.'

    try:
        if settings.IMAP_USE_SSL:
            mail = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT, timeout=settings.IMAP_TIMEOUT)
        else:
            mail = imaplib.IMAP4(settings.IMAP_HOST, settings.IMAP_PORT, timeout=settings.IMAP_TIMEOUT)
        mail.login(settings.IMAP_HOST_USER, settings.IMAP_HOST_PASSWORD)
        status, _ = mail.select(settings.IMAP_MAILBOX, readonly=True)
        if status != 'OK':
            close_imap_mailbox(mail)
            return None, f'Could not open mailbox {settings.IMAP_MAILBOX}.'
        return mail, ''
    except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
        return None, f'Inbox connection failed: {exc}'


def fetch_recent_mail(limit=10):
    mail, error = open_imap_mailbox()
    if error:
        return [], error

    try:
        status, data = mail.uid('search', None, 'ALL')
        if status != 'OK' or not data or not data[0]:
            return [], ''

        message_ids = data[0].split()[-limit:]
        inbox_messages = []
        for message_id in reversed(message_ids):
            status, message_data = mail.uid('fetch', message_id, '(RFC822)')
            if status != 'OK' or not message_data or not message_data[0]:
                continue
            raw_message = message_data[0][1]
            message = email.message_from_bytes(raw_message)
            preview = message_text_preview(message)
            inbox_messages.append({
                'uid': message_id.decode('ascii', errors='ignore'),
                'from': format_email_address(message.get('From')),
                'subject': decode_email_header(message.get('Subject')) or '(No subject)',
                'date': message.get('Date', ''),
                'preview': preview[:220],
            })
        return inbox_messages, ''
    except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
        return [], f'Inbox connection failed: {exc}'
    finally:
        close_imap_mailbox(mail)


def fetch_mail_message(uid):
    mail, error = open_imap_mailbox()
    if error:
        return None, error

    try:
        status, message_data = mail.uid('fetch', str(uid).encode('ascii'), '(RFC822)')
        if status != 'OK' or not message_data or not message_data[0]:
            return None, 'Message could not be found.'
        message = email.message_from_bytes(message_data[0][1])
        return {
            'uid': uid,
            'from': format_email_address(message.get('From')),
            'to': format_email_address(message.get('To')),
            'subject': decode_email_header(message.get('Subject')) or '(No subject)',
            'date': message.get('Date', ''),
            'body': message_text_preview(message),
        }, ''
    except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
        return None, f'Inbox connection failed: {exc}'
    finally:
        close_imap_mailbox(mail)


def paginate_queryset(request, queryset, *, per_page=25, page_param='page'):
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(request.GET.get(page_param))
    query_params = request.GET.copy()
    query_params.pop(page_param, None)
    return page_obj, query_params.urlencode()


DEFAULT_ONBOARDING_STAGES = [
    {'code': 'invitation_sent', 'title': 'Invitation Sent', 'order': 10, 'color': 'secondary'},
    {'code': 'application_submitted', 'title': 'Application Submitted', 'order': 20, 'color': 'warning'},
    {'code': 'hr_review', 'title': 'HR Review', 'order': 30, 'color': 'info'},
    {'code': 'profile_setup', 'title': 'Profile Setup', 'order': 40, 'color': 'primary'},
    {'code': 'pre_arrival', 'title': 'Pre Arrival', 'order': 50, 'color': 'success'},
    {'code': 'first_day', 'title': 'First Day', 'order': 60, 'color': 'dark'},
    {'code': 'documents_training', 'title': 'Documents & Training', 'order': 70, 'color': 'primary'},
    {'code': 'completed', 'title': 'Completed', 'order': 80, 'color': 'success'},
    {'code': 'rejected', 'title': 'Rejected', 'order': 90, 'color': 'danger'},
]


def ensure_default_onboarding_stages(organization):
    for stage_data in DEFAULT_ONBOARDING_STAGES:
        OnboardingStage.objects.get_or_create(
            organization=organization,
            code=stage_data['code'],
            defaults={
                'title': stage_data['title'],
                'order': stage_data['order'],
                'color': stage_data['color'],
                'is_active': True,
            },
        )
    return OnboardingStage.objects.filter(
        organization=organization,
        is_active=True,
    ).order_by('order', 'title')


def get_onboarding_stage(organization, code):
    ensure_default_onboarding_stages(organization)
    return OnboardingStage.objects.get(organization=organization, code=code)


def participant_status_for_stage(stage):
    if stage.code == 'completed':
        return 'completed'
    if stage.code == 'rejected':
        return 'rejected'
    return 'active'


def sync_onboarding_participant(
    organization,
    *,
    stage_code,
    applicant=None,
    employee=None,
    invitation=None,
    joining_date=None,
    note='',
    update_existing=True,
):
    if not applicant and not employee:
        return None

    stage = get_onboarding_stage(organization, stage_code)
    participant_type = 'employee' if employee else 'applicant'
    lookup = {'organization': organization, 'applicant': applicant} if applicant else {'organization': organization, 'employee': employee}
    participant, created = OnboardingParticipant.objects.get_or_create(
        **lookup,
        defaults={
            'stage': stage,
            'employee': employee,
            'invitation': invitation,
            'participant_type': participant_type,
            'joining_date': joining_date,
            'note': note,
            'status': participant_status_for_stage(stage),
            'completed_at': timezone.now() if stage.code == 'completed' else None,
        },
    )

    if not created and update_existing:
        participant.stage = stage
        participant.participant_type = participant_type
        if employee and not participant.employee:
            participant.employee = employee
        if invitation:
            participant.invitation = invitation
        if joining_date:
            participant.joining_date = joining_date
        if note:
            participant.note = note
        participant.status = participant_status_for_stage(stage)
        participant.moved_at = timezone.now()
        participant.completed_at = timezone.now() if stage.code == 'completed' else None
        participant.save(update_fields=[
            'stage',
            'employee',
            'invitation',
            'participant_type',
            'joining_date',
            'note',
            'status',
            'moved_at',
            'completed_at',
            'updated_at',
        ])
    return participant


def applicant_stage_code(applicant):
    return {
        'invited': 'invitation_sent',
        'submitted': 'application_submitted',
        'under_review': 'hr_review',
        'approved': 'profile_setup',
        'converted': 'pre_arrival',
        'rejected': 'rejected',
    }.get(applicant.status, 'invitation_sent')


def invitation_stage_code(invitation):
    if invitation.status == 'accepted':
        return 'pre_arrival'
    if invitation.status == 'submitted':
        return 'application_submitted'
    if invitation.status in ['expired', 'cancelled']:
        return 'rejected'
    return 'profile_setup' if invitation.invitation_type == 'employee_setup' else 'invitation_sent'


def sync_existing_onboarding_participants(organization):
    stages = ensure_default_onboarding_stages(organization)
    applicants = Applicant.objects.filter(
        organization=organization,
    ).select_related('employee').prefetch_related('invitations')
    for applicant in applicants:
        invitation = applicant.invitations.order_by('-created_at').first()
        sync_onboarding_participant(
            organization,
            stage_code=applicant_stage_code(applicant),
            applicant=applicant,
            employee=applicant.employee,
            invitation=invitation,
            joining_date=applicant.employee.hire_date if applicant.employee else None,
            update_existing=False,
        )

    employee_invitations = OnboardingInvitation.objects.filter(
        organization=organization,
        invitation_type='employee_setup',
        employee__isnull=False,
    ).select_related('employee')
    for invitation in employee_invitations:
        sync_onboarding_participant(
            organization,
            stage_code=invitation_stage_code(invitation),
            employee=invitation.employee,
            invitation=invitation,
            joining_date=invitation.employee.hire_date,
            update_existing=False,
        )
    return stages


def hr_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        organization = get_active_organization(request)
        if organization and user_has_hr_access(request.user, organization):
            return view_func(request, *args, **kwargs)
        messages.warning(request, 'You do not have access to the HR admin area.')
        if hasattr(request.user, 'employee_profile'):
            return redirect('employee_self_service_dashboard')
        return redirect('login')
    return wrapper


def manager_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        organization = get_active_organization(request)
        if organization and user_has_manager_access(request.user, organization):
            return view_func(request, *args, **kwargs)
        messages.warning(request, 'You do not have access to manager approvals.')
        if hasattr(request.user, 'employee_profile'):
            return redirect('employee_self_service_dashboard')
        return redirect('login')
    return wrapper


def payroll_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        organization = get_active_organization(request)
        if organization and user_has_payroll_access(request.user, organization):
            return view_func(request, *args, **kwargs)
        messages.warning(request, 'You do not have access to payroll or finance tools.')
        if hasattr(request.user, 'employee_profile'):
            return redirect('employee_self_service_dashboard')
        return redirect('login')
    return wrapper

def login_view(request):
    """Custom login view"""
    if request.user.is_authenticated:
        if is_employee_self_service_user(request.user):
            return redirect('employee_self_service_dashboard')
        if user_has_payroll_access(request.user) and not user_has_hr_access(request.user):
            return redirect('finance_dashboard')
        if user_has_manager_access(request.user) and not user_has_hr_access(request.user):
            return redirect('manager_dashboard')
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            if is_employee_self_service_user(user):
                return redirect('employee_self_service_dashboard')
            if user_has_payroll_access(user) and not user_has_hr_access(user):
                return redirect('finance_dashboard')
            if user_has_manager_access(user) and not user_has_hr_access(user):
                return redirect('manager_dashboard')
            return redirect('dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'registration/login.html')


def logout_view(request):
    """Custom logout view"""
    logout(request)
    return redirect('login')


# ==================== ORGANIZATION VIEWS ====================

@login_required
@hr_required
def organization_list(request):
    organizations = get_user_organizations(request.user)
    active_organization = get_active_organization(request)
    organizations_page, organizations_pagination_query = paginate_queryset(
        request,
        organizations.order_by('name'),
        per_page=20,
        page_param='organizations_page',
    )

    context = {
        'organizations': organizations_page,
        'organizations_page_obj': organizations_page,
        'organizations_pagination_query': organizations_pagination_query,
        'active_organization': active_organization,
        'page_title': 'Organizations',
    }
    return render(request, 'attendance/organization_list.html', context)


@login_required
@hr_required
def organization_create(request):
    if request.method == 'POST':
        form = OrganizationForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                organization = form.save()
                OrganizationMembership.objects.get_or_create(
                    user=request.user,
                    organization=organization,
                    defaults={'role': 'owner', 'is_active': True},
                )
                setup_default_organization_records(organization)
                request.session['active_organization_id'] = organization.pk
            messages.success(request, f'{organization.name} has been created and selected.')
            return redirect('dashboard')
    else:
        form = OrganizationForm(initial={'is_active': True})

    context = {
        'form': form,
        'page_title': 'Create Organization',
        'action': 'Create',
    }
    return render(request, 'attendance/organization_form.html', context)


@login_required
@hr_required
def organization_edit(request, pk):
    organization = get_object_or_404(get_user_organizations(request.user), pk=pk)

    if request.method == 'POST':
        form = OrganizationForm(request.POST, instance=organization)
        if form.is_valid():
            organization = form.save()
            messages.success(request, f'{organization.name} has been updated.')
            return redirect('organization_list')
    else:
        form = OrganizationForm(instance=organization)

    context = {
        'form': form,
        'organization': organization,
        'page_title': f'Edit {organization.name}',
        'action': 'Update',
    }
    return render(request, 'attendance/organization_form.html', context)


@login_required
@hr_required
def organization_switch(request, pk):
    organization = get_object_or_404(get_user_organizations(request.user), pk=pk)
    request.session['active_organization_id'] = organization.pk
    messages.success(request, f'Switched to {organization.name}.')
    return redirect('dashboard')


@login_required
@hr_required
def organization_settings(request):
    organization = get_active_organization(request)
    settings_obj = get_attendance_settings(organization)

    context = {
        'organization': organization,
        'settings_obj': settings_obj,
        'departments': Department.objects.filter(organization=organization).order_by('name'),
        'categories': Category.objects.filter(organization=organization).order_by('name'),
        'exception_types': AttendanceExceptionType.objects.filter(organization=organization).order_by('name'),
        'leave_types': LeaveType.objects.filter(organization=organization).order_by('name'),
        'kiosk_url': request.build_absolute_uri(reverse('organization_kiosk', kwargs={'org_slug': organization.slug})),
        'page_title': 'Organization Settings',
    }
    return render(request, 'attendance/organization_settings.html', context)


@login_required
@hr_required
def organization_departments(request):
    organization = get_active_organization(request)

    if request.method == 'POST':
        form = DepartmentForm(request.POST, organization=organization)
        if form.is_valid():
            department = form.save()
            messages.success(request, f'{department.name} department has been added.')
            return redirect('organization_departments')
    else:
        form = DepartmentForm(initial={'is_active': True}, organization=organization)
    departments_page, departments_pagination_query = paginate_queryset(
        request,
        Department.objects.filter(organization=organization).order_by('name'),
        per_page=20,
        page_param='departments_page',
    )

    context = {
        'form': form,
        'organization': organization,
        'departments': departments_page,
        'departments_page_obj': departments_page,
        'departments_pagination_query': departments_pagination_query,
        'page_title': 'Departments',
    }
    return render(request, 'attendance/organization_departments.html', context)


@login_required
@hr_required
def organization_categories(request):
    organization = get_active_organization(request)

    if request.method == 'POST':
        form = CategoryForm(request.POST, organization=organization)
        if form.is_valid():
            category = form.save()
            messages.success(request, f'{category.name} category has been added.')
            return redirect('organization_categories')
    else:
        form = CategoryForm(initial={'icon': 'bi-person', 'color': 'primary'}, organization=organization)
    categories_page, categories_pagination_query = paginate_queryset(
        request,
        Category.objects.filter(organization=organization).order_by('name'),
        per_page=20,
        page_param='categories_page',
    )

    context = {
        'form': form,
        'organization': organization,
        'categories': categories_page,
        'categories_page_obj': categories_page,
        'categories_pagination_query': categories_pagination_query,
        'page_title': 'Employee Categories',
    }
    return render(request, 'attendance/organization_categories.html', context)


@login_required
@hr_required
def organization_attendance_settings(request):
    organization = get_active_organization(request)
    settings_obj = get_attendance_settings(organization)

    if request.method == 'POST':
        form = AttendanceSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Attendance settings have been updated.')
            return redirect('organization_attendance_settings')
    else:
        form = AttendanceSettingsForm(instance=settings_obj)

    context = {
        'form': form,
        'organization': organization,
        'page_title': 'Attendance Settings',
    }
    return render(request, 'attendance/organization_attendance_settings.html', context)


@login_required
@hr_required
def organization_birthday_message_template(request):
    organization = get_active_organization(request)
    settings_obj = get_attendance_settings(organization)

    if request.method == 'POST':
        form = BirthdayMessageTemplateForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Birthday message template has been updated.')
            return redirect('organization_birthday_message_template')
    else:
        form = BirthdayMessageTemplateForm(instance=settings_obj)

    context = {
        'form': form,
        'organization': organization,
        'placeholders': [
            '{first_name}',
            '{last_name}',
            '{full_name}',
            '{display_name}',
            '{employee_id}',
            '{organization_name}',
        ],
        'page_title': 'Birthday Message Template',
    }
    return render(request, 'attendance/birthday_message_template.html', context)


@login_required
@hr_required
def organization_leave_types(request):
    organization = get_active_organization(request)

    if request.method == 'POST':
        form = LeaveTypeForm(request.POST, organization=organization)
        if form.is_valid():
            leave_type = form.save()
            messages.success(request, f'{leave_type.name} leave type has been added.')
            return redirect('organization_leave_types')
    else:
        form = LeaveTypeForm(
            initial={
                'annual_entitlement_days': 0,
                'color': 'success',
                'requires_attachment': False,
                'is_paid': True,
                'is_active': True,
            },
            organization=organization,
        )
    leave_types_page, leave_types_pagination_query = paginate_queryset(
        request,
        LeaveType.objects.filter(organization=organization).order_by('name'),
        per_page=20,
        page_param='leave_types_page',
    )

    context = {
        'form': form,
        'organization': organization,
        'leave_types': leave_types_page,
        'leave_types_page_obj': leave_types_page,
        'leave_types_pagination_query': leave_types_pagination_query,
        'page_title': 'Leave Types',
    }
    return render(request, 'attendance/leave_types.html', context)


@login_required
@hr_required
def organization_leave_type_edit(request, pk):
    organization = get_active_organization(request)
    leave_type = get_object_or_404(LeaveType, organization=organization, pk=pk)

    if request.method == 'POST':
        form = LeaveTypeForm(request.POST, organization=organization, instance=leave_type)
        if form.is_valid():
            leave_type = form.save()
            messages.success(request, f'{leave_type.name} leave type has been updated.')
            return redirect('organization_leave_types')
    else:
        form = LeaveTypeForm(organization=organization, instance=leave_type)

    context = {
        'form': form,
        'organization': organization,
        'leave_type': leave_type,
        'page_title': f'Edit Leave Type: {leave_type.name}',
        'action': 'Update',
    }
    return render(request, 'attendance/leave_type_form.html', context)


@login_required
@hr_required
def organization_leave_type_delete(request, pk):
    organization = get_active_organization(request)
    leave_type = get_object_or_404(LeaveType, organization=organization, pk=pk)
    request_count = LeaveRequest.objects.filter(organization=organization, leave_type=leave_type).count()

    if request.method == 'POST':
        name = leave_type.name
        try:
            leave_type.delete()
        except ProtectedError:
            messages.warning(
                request,
                f'{name} is already used by leave requests, so it cannot be deleted. You can mark it inactive instead.',
            )
            return redirect('organization_leave_types')
        messages.success(request, f'{name} leave type has been deleted.')
        return redirect('organization_leave_types')

    context = {
        'organization': organization,
        'leave_type': leave_type,
        'request_count': request_count,
        'page_title': f'Delete Leave Type: {leave_type.name}',
    }
    return render(request, 'attendance/leave_type_confirm_delete.html', context)


# ==================== PUBLIC VIEWS ====================

def kiosk_view(request, org_slug=None):
    """Public kiosk page for check-in/out - no login required"""
    if org_slug:
        organization = get_object_or_404(Organization, slug=org_slug, is_active=True)
    else:
        organization = get_default_organization()
    
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        action = request.POST.get('action')
        
        if not email:
            messages.error(request, 'Please enter your email address.')
            return redirect('kiosk')
        
        try:
            employee = Employee.objects.get(organization=organization, email=email, is_active=True)
        except Employee.DoesNotExist:
            messages.error(request, f'Email "{email}" not found. Please contact HR.')
            return redirect('organization_kiosk', org_slug=organization.slug)
        
        now = timezone.now()
        local_now = timezone.localtime(now)
        today = local_now.date()
        
        if action == 'check_in':
            if employee.is_checked_in_today:
                record = employee.today_attendance
                record_local_in = timezone.localtime(record.check_in_time) if record else None
                messages.warning(
                    request, 
                    f'{employee.first_name}, you are already checked in since {record_local_in.strftime("%H:%M")}.'
                )
                return redirect('organization_kiosk', org_slug=organization.slug)
            
            AttendanceRecord.objects.create(
                organization=organization,
                employee=employee,
                check_in_time=now
            )
            messages.success(
                request, 
                f'Welcome, {employee.first_name}! You checked in at {local_now.strftime("%H:%M")}.'
            )
            
        elif action == 'check_out':
            record = employee.today_attendance
            
            if not record or not record.is_active:
                messages.error(
                    request, 
                    f'{employee.first_name}, you have not checked in today.'
                )
                return redirect('organization_kiosk', org_slug=organization.slug)
            
            record.check_out_time = now
            record.save()
            
            hours = record.hours_worked
            messages.success(
                request, 
                f'Goodbye, {employee.first_name}! You checked out at {local_now.strftime("%H:%M")}. '
                f'Hours worked: {hours} hrs.'
            )
        
        return redirect('organization_kiosk', org_slug=organization.slug)
    
    context = {
        'current_time': timezone.now(),
        'organization': organization,
    }
    return render(request, 'attendance/kiosk.html', context)


# ==================== DASHBOARD VIEWS ====================

@login_required
@hr_required
def dashboard_view(request):
    """Main HR Dashboard"""
    
    organization = get_active_organization(request)
    ensure_default_categories(organization)
    today = timezone.localdate()
    settings_obj = get_attendance_settings(organization)
    late_threshold = settings_obj.late_threshold
    workday_start = settings_obj.workday_start
    attendance_status = request.GET.get('attendance_status', '').strip().lower()
    if attendance_status not in ['present', 'late', 'absent']:
        attendance_status = ''
    
    # Statistics
    active_employees = Employee.objects.filter(
        organization=organization,
        is_active=True,
    ).select_related('category', 'department')
    total_employees = active_employees.count()
    
    todays_records = AttendanceRecord.objects.filter(
        organization=organization,
        **local_date_range_filter('check_in_time', today),
    ).select_related('employee__category', 'employee__department')
    
    present_count = todays_records.values('employee_id').distinct().count()
    checked_in_count = todays_records.filter(check_out_time__isnull=True).count()
    checked_out_count = todays_records.filter(check_out_time__isnull=False).count()
    late_count = count_distinct_late_employees(todays_records)
    absent_count = max(total_employees - present_count, 0)
    
    # Recent activity
    recent_attendance = todays_records.order_by('-check_in_time')[:5]

    attendance_people = []
    latest_records_by_employee = {}
    late_employee_ids = set()
    for record in todays_records.order_by('-check_in_time'):
        latest_records_by_employee.setdefault(record.employee_id, record)
        if record.is_late:
            late_employee_ids.add(record.employee_id)

    if attendance_status in ['present', 'late']:
        selected_employee_ids = set(latest_records_by_employee.keys())
        if attendance_status == 'late':
            selected_employee_ids = late_employee_ids
        for employee in active_employees.filter(pk__in=selected_employee_ids).order_by('first_name', 'last_name'):
            record = latest_records_by_employee.get(employee.pk)
            attendance_people.append({
                'employee': employee,
                'record': record,
                'status_label': 'Late' if employee.pk in late_employee_ids else 'Present',
                'status_color': 'warning' if employee.pk in late_employee_ids else 'success',
            })
    elif attendance_status == 'absent':
        present_employee_ids = set(latest_records_by_employee.keys())
        for employee in active_employees.exclude(pk__in=present_employee_ids).order_by('first_name', 'last_name'):
            attendance_people.append({
                'employee': employee,
                'record': None,
                'status_label': 'Absent',
                'status_color': 'danger',
            })

    # Birthdays this week
    birthdays_this_week = get_upcoming_birthdays(organization=organization)
    internship_endings = get_upcoming_internship_endings(organization=organization)

    # Work anniversaries this week (Staff only)
    anniversaries_this_week = []
    staff_employees = active_employees.filter(category__code='STAFF', hire_date__isnull=False)
    for employee in staff_employees:
        info = employee.get_anniversary_this_week()
        if info:
            anniversaries_this_week.append({
                'employee': employee,
                **info,
            })
    anniversaries_this_week.sort(key=lambda x: x['days_until'])

    # Per-category breakdown
    category_stats = []
    for category in Category.objects.filter(organization=organization).order_by('name'):
        total_in_category = active_employees.filter(category=category).count()
        present_in_category = todays_records.filter(employee__category=category).values('employee_id').distinct().count()
        late_in_category = count_distinct_late_employees(todays_records.filter(employee__category=category))
        category_stats.append({
            'category': category,
            'total': total_in_category,
            'present': present_in_category,
            'late': late_in_category,
            'absent': max(total_in_category - present_in_category, 0),
        })
    
    show_checklist = (total_employees == 0)
    late_today = []
    for employee in active_employees.filter(pk__in=late_employee_ids).order_by('first_name', 'last_name')[:10]:
        late_today.append({
            'employee': employee,
            'record': latest_records_by_employee.get(employee.pk),
        })
    checklist = {
        'profile_done': bool((organization.email or '').strip() or (organization.address or '').strip()),
        'hours_done': bool(
            workday_start.strftime('%H:%M') != '08:00'
            or late_threshold.strftime('%H:%M') != '08:30'
        ),
        'invite_done': OnboardingInvitation.objects.filter(organization=organization).exists(),
    }
    context = {
        'today': today,
        'total_employees': total_employees,
        'present_count': present_count,
        'checked_in_count': checked_in_count,
        'checked_out_count': checked_out_count,
        'late_count': late_count,
        'absent_count': absent_count,
        'recent_attendance': recent_attendance,
        'birthdays_this_week': birthdays_this_week,
        'internship_endings': internship_endings,
        'anniversaries_this_week': anniversaries_this_week,
        'category_stats': category_stats,
        'attendance_people': attendance_people,
        'attendance_status': attendance_status,
        'organization': organization,
        'kiosk_url': request.build_absolute_uri(reverse('organization_kiosk', kwargs={'org_slug': organization.slug})),
        'late_threshold': late_threshold,
        'workday_start': workday_start,
        'show_checklist': show_checklist,
        'checklist': checklist,
        'late_today': late_today,
        'page_title': 'Dashboard',
    }
    
    return render(request, 'attendance/dashboard.html', context)


@login_required
@hr_required
def category_dashboard(request, code):
    """Dashboard view scoped to a single employee category."""

    organization = get_active_organization(request)
    today = timezone.localdate()
    category = get_object_or_404(Category, organization=organization, code=code.upper())

    category_employees = Employee.objects.filter(
        organization=organization,
        category=category,
    ).select_related('department', 'category')
    active_category_employees = category_employees.filter(is_active=True)

    search_query = request.GET.get('search', '').strip()
    department_id = request.GET.get('department', '')
    status = request.GET.get('status', '')

    employees = category_employees
    if search_query:
        employees = employees.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(employee_id__icontains=search_query) |
            Q(department__name__icontains=search_query)
        )

    if department_id and department_id.isdigit():
        employees = employees.filter(department_id=int(department_id))

    if status == 'active':
        employees = employees.filter(is_active=True)
    elif status == 'inactive':
        employees = employees.filter(is_active=False)

    todays_records = AttendanceRecord.objects.filter(
        organization=organization,
        employee__category=category,
        **local_date_range_filter('check_in_time', today),
    ).select_related('employee__category', 'employee__department')

    total_employees = active_category_employees.count()
    present_count = todays_records.values('employee_id').distinct().count()
    checked_in_count = todays_records.filter(check_out_time__isnull=True).count()
    checked_out_count = todays_records.filter(check_out_time__isnull=False).count()
    late_count = count_distinct_late_employees(todays_records)
    absent_count = max(total_employees - present_count, 0)
    recent_attendance = todays_records.order_by('-check_in_time')[:8]
    employees_page, employees_pagination_query = paginate_queryset(
        request,
        employees.order_by('first_name', 'last_name'),
        per_page=25,
        page_param='employees_page',
    )

    context = {
        'category': category,
        'organization': organization,
        'today': today,
        'total_employees': total_employees,
        'present_count': present_count,
        'checked_in_count': checked_in_count,
        'checked_out_count': checked_out_count,
        'late_count': late_count,
        'absent_count': absent_count,
        'employees': employees_page,
        'employees_page_obj': employees_page,
        'employees_pagination_query': employees_pagination_query,
        'recent_attendance': recent_attendance,
        'departments': Department.objects.filter(organization=organization, is_active=True).order_by('name'),
        'search_query': search_query,
        'selected_department': department_id,
        'selected_status': status,
        'page_title': f'{category.name} Dashboard',
    }

    return render(request, 'attendance/category_dashboard.html', context)


# ==================== EMPLOYEE MANAGEMENT VIEWS ====================

@login_required
@hr_required
def employee_list(request):
    """List all employees with search and filter"""
    
    organization = get_active_organization(request)
    employees = Employee.objects.filter(organization=organization).select_related('department', 'category')
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        employees = employees.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(employee_id__icontains=search_query) |
            Q(department__name__icontains=search_query)
        )
    
    # Department filter
    department_id = request.GET.get('department', '')
    if department_id and department_id.isdigit():
        employees = employees.filter(department_id=int(department_id))

    category_id = request.GET.get('category', '')
    if category_id and category_id.isdigit():
        employees = employees.filter(category_id=int(category_id))
    
    # Status filter
    status = request.GET.get('status', '')
    if status == 'active':
        employees = employees.filter(is_active=True)
    elif status == 'inactive':
        employees = employees.filter(is_active=False)
    
    # Get unique departments for filter dropdown
    departments = Department.objects.filter(organization=organization, is_active=True).order_by('name')
    categories = Category.objects.filter(organization=organization).order_by('name')
    employees = employees.order_by('first_name', 'last_name')
    employees_page, employees_pagination_query = paginate_queryset(
        request,
        employees,
        per_page=25,
        page_param='employees_page',
    )
    
    context = {
        'employees': employees_page,
        'employees_page_obj': employees_page,
        'employees_pagination_query': employees_pagination_query,
        'organization': organization,
        'search_query': search_query,
        'departments': departments,
        'categories': categories,
        'selected_department': department_id,
        'selected_category': category_id,
        'selected_status': status,
        'page_title': 'Employee Management',
    }
    
    return render(request, 'attendance/employee_list.html', context)


@login_required
@hr_required
def employee_create(request):
    """Add new employee"""

    organization = get_active_organization(request)
    employee = Employee(organization=organization)

    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES, instance=employee, organization=organization)
        education_formset = EmployeeEducationFormSet(request.POST, instance=employee, prefix='education')
        certification_formset = EmployeeCertificationFormSet(request.POST, instance=employee, prefix='certification')
        work_experience_formset = EmployeeWorkExperienceFormSet(request.POST, instance=employee, prefix='work')
        document_formset = EmployeeDocumentFormSet(request.POST, request.FILES, instance=employee, prefix='document')

        if all([
            form.is_valid(),
            education_formset.is_valid(),
            certification_formset.is_valid(),
            work_experience_formset.is_valid(),
            document_formset.is_valid(),
        ]):
            with transaction.atomic():
                employee = form.save()
                education_formset.instance = employee
                certification_formset.instance = employee
                work_experience_formset.instance = employee
                document_formset.instance = employee
                education_formset.save()
                certification_formset.save()
                work_experience_formset.save()
                document_formset.save()
                write_audit_log(
                    request,
                    organization=organization,
                    area='employee',
                    action='employee_created',
                    target=employee,
                    summary=f'Created employee profile for {employee.full_name}.',
                    metadata={'employee_id': employee.employee_id, 'category': employee.category.code},
                )
            messages.success(request, f'{employee.full_name} has been added successfully.')
            return redirect('employee_list')
    else:
        form = EmployeeForm(instance=employee, organization=organization)
        education_formset = EmployeeEducationFormSet(instance=employee, prefix='education')
        certification_formset = EmployeeCertificationFormSet(instance=employee, prefix='certification')
        work_experience_formset = EmployeeWorkExperienceFormSet(instance=employee, prefix='work')
        document_formset = EmployeeDocumentFormSet(instance=employee, prefix='document')
    
    context = {
        'form': form,
        'organization': organization,
        'education_formset': education_formset,
        'certification_formset': certification_formset,
        'work_experience_formset': work_experience_formset,
        'document_formset': document_formset,
        'page_title': 'Add Employee',
        'action': 'Add',
    }
    
    return render(request, 'attendance/employee_form.html', context)


@login_required
@hr_required
def employee_edit(request, pk):
    """Edit existing employee"""
    
    organization = get_active_organization(request)
    employee = get_object_or_404(Employee, organization=organization, pk=pk)
    
    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES, instance=employee, organization=organization)
        education_formset = EmployeeEducationFormSet(request.POST, instance=employee, prefix='education')
        certification_formset = EmployeeCertificationFormSet(request.POST, instance=employee, prefix='certification')
        work_experience_formset = EmployeeWorkExperienceFormSet(request.POST, instance=employee, prefix='work')
        document_formset = EmployeeDocumentFormSet(request.POST, request.FILES, instance=employee, prefix='document')
        if all([
            form.is_valid(),
            education_formset.is_valid(),
            certification_formset.is_valid(),
            work_experience_formset.is_valid(),
            document_formset.is_valid(),
        ]):
            with transaction.atomic():
                employee = form.save()
                education_formset.save()
                certification_formset.save()
                work_experience_formset.save()
                document_formset.save()
                write_audit_log(
                    request,
                    organization=organization,
                    area='employee',
                    action='employee_updated',
                    target=employee,
                    summary=f'Updated employee profile for {employee.full_name}.',
                    metadata={'employee_id': employee.employee_id, 'category': employee.category.code},
                )
            messages.success(request, f'{employee.full_name} has been updated successfully.')
            return redirect('employee_list')
    else:
        form = EmployeeForm(instance=employee, organization=organization)
        education_formset = EmployeeEducationFormSet(instance=employee, prefix='education')
        certification_formset = EmployeeCertificationFormSet(instance=employee, prefix='certification')
        work_experience_formset = EmployeeWorkExperienceFormSet(instance=employee, prefix='work')
        document_formset = EmployeeDocumentFormSet(instance=employee, prefix='document')
    
    context = {
        'form': form,
        'organization': organization,
        'education_formset': education_formset,
        'certification_formset': certification_formset,
        'work_experience_formset': work_experience_formset,
        'document_formset': document_formset,
        'employee': employee,
        'page_title': f'Edit: {employee.full_name}',
        'action': 'Update',
    }
    
    return render(request, 'attendance/employee_form.html', context)


@login_required
@hr_required
def employee_delete(request, pk):
    """Delete employee"""
    
    organization = get_active_organization(request)
    employee = get_object_or_404(Employee, organization=organization, pk=pk)
    
    if request.method == 'POST':
        name = employee.full_name
        employee_id = employee.employee_id
        write_audit_log(
            request,
            organization=organization,
            area='employee',
            action='employee_deleted',
            target=employee,
            summary=f'Deleted employee profile for {name}.',
            metadata={'employee_id': employee_id},
        )
        employee.delete()
        messages.success(request, f'{name} has been deleted.')
        return redirect('employee_list')
    
    context = {
        'employee': employee,
        'page_title': f'Delete: {employee.full_name}',
    }
    
    return render(request, 'attendance/employee_confirm_delete.html', context)


@login_required
@hr_required
def employee_account_create(request, pk):
    """Create a login account for an employee."""

    organization = get_active_organization(request)
    employee = get_object_or_404(Employee, organization=organization, pk=pk)

    if employee.user:
        messages.info(request, f'{employee.full_name} already has a login account.')
        return redirect('employee_detail', pk=employee.pk)

    if request.method == 'POST':
        form = EmployeeAccountForm(request.POST, employee=employee)
        if form.is_valid():
            with transaction.atomic():
                user = User.objects.create_user(
                    username=form.cleaned_data['username'],
                    email=form.cleaned_data['email'],
                    password=form.cleaned_data['password'],
                    first_name=employee.first_name,
                    last_name=employee.last_name,
                )
                employee.user = user
                employee.save(update_fields=['user'])
                OrganizationMembership.objects.get_or_create(
                    user=user,
                    organization=employee.organization,
                    defaults={'role': 'employee', 'is_active': True},
                )
                write_audit_log(
                    request,
                    organization=organization,
                    area='security',
                    action='employee_account_created',
                    target=employee,
                    summary=f'Created login account for {employee.full_name}.',
                    metadata={'employee_id': employee.employee_id, 'username': user.username},
                )
            messages.success(
                request,
                f'Login account created for {employee.full_name}. Temporary password: {form.cleaned_data["password"]}'
            )
            return redirect('employee_detail', pk=employee.pk)
    else:
        generated_password = get_random_string(10)
        form = EmployeeAccountForm(initial={'password': generated_password}, employee=employee)

    context = {
        'form': form,
        'employee': employee,
        'organization': organization,
        'page_title': f'Create Account: {employee.full_name}',
    }
    return render(request, 'attendance/employee_account_form.html', context)


@login_required
@hr_required
def employee_detail(request, pk):
    """View employee details with attendance history"""
    
    organization = get_active_organization(request)
    employee = get_object_or_404(
        Employee.objects.filter(organization=organization).prefetch_related('educations', 'certifications', 'work_experiences', 'documents', 'onboarding_tasks'),
        pk=pk,
    )
    
    # Get attendance history
    attendance_history = AttendanceRecord.objects.filter(
        organization=organization,
        employee=employee
    ).order_by('-check_in_time')
    attendance_page, attendance_pagination_query = paginate_queryset(
        request,
        attendance_history,
        per_page=15,
        page_param='attendance_page',
    )
    
    context = {
        'employee': employee,
        'organization': organization,
        'attendance_history': attendance_page,
        'attendance_page_obj': attendance_page,
        'attendance_pagination_query': attendance_pagination_query,
        'page_title': employee.full_name,
    }
    
    return render(request, 'attendance/employee_detail.html', context)


@login_required
@hr_required
def employee_documents(request):
    organization = get_active_organization(request)
    documents = EmployeeDocument.objects.filter(
        employee__organization=organization,
    ).select_related('employee', 'employee__department', 'employee__category')

    search_query = request.GET.get('q', '').strip()
    document_type = request.GET.get('document_type', '').strip()
    expiring = request.GET.get('expiring', '').strip()
    today = timezone.localdate()

    if search_query:
        documents = documents.filter(
            Q(title__icontains=search_query)
            | Q(notes__icontains=search_query)
            | Q(employee__first_name__icontains=search_query)
            | Q(employee__last_name__icontains=search_query)
            | Q(employee__employee_id__icontains=search_query)
        )
    if document_type:
        documents = documents.filter(document_type=document_type)
    if expiring == 'expired':
        documents = documents.filter(expiry_date__lt=today)
    elif expiring == 'soon':
        documents = documents.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30))
    elif expiring == 'none':
        documents = documents.filter(expiry_date__isnull=True)
    documents = documents.order_by('-uploaded_at', 'employee__first_name', 'title')
    documents_page, documents_pagination_query = paginate_queryset(
        request,
        documents,
        per_page=25,
        page_param='documents_page',
    )

    context = {
        'organization': organization,
        'documents': documents_page,
        'documents_page_obj': documents_page,
        'documents_pagination_query': documents_pagination_query,
        'search_query': search_query,
        'selected_document_type': document_type,
        'selected_expiring': expiring,
        'document_type_choices': EmployeeDocument.DOCUMENT_TYPE_CHOICES,
        'total_documents': documents.count(),
        'expired_count': EmployeeDocument.objects.filter(employee__organization=organization, expiry_date__lt=today).count(),
        'expiring_soon_count': EmployeeDocument.objects.filter(
            employee__organization=organization,
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=30),
        ).count(),
        'page_title': 'Employee Documents',
    }
    return render(request, 'attendance/employee_documents.html', context)


@login_required
@hr_required
def employee_document_upload(request, employee_pk=None):
    organization = get_active_organization(request)
    employee = None
    if employee_pk:
        employee = get_object_or_404(Employee, organization=organization, pk=employee_pk)

    if request.method == 'POST':
        selected_employee = employee
        if not selected_employee:
            selected_employee = get_object_or_404(Employee, organization=organization, pk=request.POST.get('employee'))
        form = EmployeeDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save(commit=False)
            document.employee = selected_employee
            document.save()
            write_audit_log(
                request,
                organization=organization,
                area='employee',
                action='employee_document_uploaded',
                target=document,
                summary=f'Uploaded document {document.title} for {selected_employee.full_name}.',
                metadata={'employee_id': selected_employee.employee_id, 'document_type': document.document_type},
            )
            messages.success(request, f'Document uploaded for {selected_employee.full_name}.')
            return redirect('employee_documents')
    else:
        form = EmployeeDocumentForm()

    context = {
        'form': form,
        'employee': employee,
        'employees': Employee.objects.filter(
            organization=organization,
            is_active=True,
        ).select_related('department').order_by('first_name', 'last_name'),
        'organization': organization,
        'page_title': 'Upload Document',
    }
    return render(request, 'attendance/employee_document_form.html', context)


@login_required
@hr_required
def employee_document_edit(request, pk):
    organization = get_active_organization(request)
    document = get_object_or_404(
        EmployeeDocument.objects.select_related('employee'),
        employee__organization=organization,
        pk=pk,
    )

    if request.method == 'POST':
        form = EmployeeDocumentForm(request.POST, request.FILES, instance=document)
        if form.is_valid():
            document = form.save()
            write_audit_log(
                request,
                organization=organization,
                area='employee',
                action='employee_document_updated',
                target=document,
                summary=f'Updated document {document.title} for {document.employee.full_name}.',
                metadata={'employee_id': document.employee.employee_id, 'document_type': document.document_type},
            )
            messages.success(request, f'Document updated for {document.employee.full_name}.')
            return redirect('employee_documents')
    else:
        form = EmployeeDocumentForm(instance=document)

    context = {
        'form': form,
        'document': document,
        'employee': document.employee,
        'organization': organization,
        'page_title': 'Edit Document',
    }
    return render(request, 'attendance/employee_document_form.html', context)


@login_required
@hr_required
def employee_document_delete(request, pk):
    organization = get_active_organization(request)
    document = get_object_or_404(
        EmployeeDocument.objects.select_related('employee'),
        employee__organization=organization,
        pk=pk,
    )

    if request.method == 'POST':
        employee_name = document.employee.full_name
        employee_id = document.employee.employee_id
        document_title = document.title
        write_audit_log(
            request,
            organization=organization,
            area='employee',
            action='employee_document_deleted',
            target=document,
            summary=f'Deleted document {document_title} for {employee_name}.',
            metadata={'employee_id': employee_id, 'document_type': document.document_type},
        )
        document.delete()
        messages.success(request, f'Document deleted for {employee_name}.')
        return redirect('employee_documents')

    context = {
        'document': document,
        'employee': document.employee,
        'organization': organization,
        'page_title': 'Delete Document',
    }
    return render(request, 'attendance/employee_document_confirm_delete.html', context)


@login_required
@hr_required
def mail_dashboard(request):
    """Track outbound onboarding mail and candidate/employee responses."""

    organization = get_active_organization(request)
    search_query = request.GET.get('q', '').strip()
    selected_status = request.GET.get('status', '').strip()
    selected_type = request.GET.get('type', '').strip()

    valid_statuses = dict(OnboardingInvitation.STATUS_CHOICES)
    valid_types = dict(OnboardingInvitation.INVITATION_TYPE_CHOICES)
    if selected_status not in valid_statuses:
        selected_status = ''
    if selected_type not in valid_types:
        selected_type = ''

    invitations = OnboardingInvitation.objects.filter(
        organization=organization,
    ).select_related(
        'applicant',
        'employee',
        'invited_by',
    )

    if search_query:
        invitations = invitations.filter(
            Q(email__icontains=search_query) |
            Q(applicant__first_name__icontains=search_query) |
            Q(applicant__last_name__icontains=search_query) |
            Q(employee__first_name__icontains=search_query) |
            Q(employee__last_name__icontains=search_query) |
            Q(employee__employee_id__icontains=search_query)
        )

    if selected_status:
        invitations = invitations.filter(status=selected_status)
    if selected_type:
        invitations = invitations.filter(invitation_type=selected_type)

    organization_invitations = OnboardingInvitation.objects.filter(organization=organization)
    invitation_counts = {
        'total': organization_invitations.count(),
        'sent': organization_invitations.filter(status='sent').count(),
        'opened': organization_invitations.filter(status='opened').count(),
        'responded': organization_invitations.filter(status__in=['submitted', 'accepted']).count(),
    }
    mail_page, mail_pagination_query = paginate_queryset(
        request,
        invitations.order_by('-created_at'),
        per_page=25,
        page_param='mail_page',
    )
    inbox_messages, inbox_error = fetch_recent_mail(limit=10)

    context = {
        'organization': organization,
        'invitations': mail_page,
        'mail_page_obj': mail_page,
        'mail_pagination_query': mail_pagination_query,
        'inbox_messages': inbox_messages,
        'inbox_error': inbox_error,
        'invitation_counts': invitation_counts,
        'status_choices': OnboardingInvitation.STATUS_CHOICES,
        'type_choices': OnboardingInvitation.INVITATION_TYPE_CHOICES,
        'search_query': search_query,
        'selected_status': selected_status,
        'selected_type': selected_type,
        'page_title': 'Mail',
    }
    return render(request, 'attendance/mail_dashboard.html', context)


@login_required
@hr_required
def mail_inbox_message(request, uid):
    message, inbox_error = fetch_mail_message(uid)
    context = {
        'message': message,
        'inbox_error': inbox_error,
        'page_title': 'Inbox Message',
    }
    return render(request, 'attendance/mail_inbox_message.html', context)


@login_required
@hr_required
def mail_compose(request):
    initial_to = request.GET.get('to', '').strip()
    initial_subject = request.GET.get('subject', '').strip()
    form_data = {
        'to': initial_to,
        'subject': initial_subject,
        'body': '',
    }

    if request.method == 'POST':
        form_data = {
            'to': request.POST.get('to', '').strip(),
            'subject': request.POST.get('subject', '').strip(),
            'body': request.POST.get('body', '').strip(),
        }
        errors = []
        if not form_data['to']:
            errors.append('Recipient email is required.')
        if not form_data['subject']:
            errors.append('Subject is required.')
        if not form_data['body']:
            errors.append('Message body is required.')

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            email_message = EmailMessage(
                subject=form_data['subject'],
                body=form_data['body'],
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[address.strip() for address in form_data['to'].split(',') if address.strip()],
                reply_to=[settings.IMAP_HOST_USER] if settings.IMAP_HOST_USER else None,
            )
            email_message.send(fail_silently=False)
            messages.success(request, f"Mail sent to {form_data['to']}.")
            return redirect('mail_dashboard')

    context = {
        'form_data': form_data,
        'from_email': settings.DEFAULT_FROM_EMAIL,
        'page_title': 'Compose Mail',
    }
    return render(request, 'attendance/mail_compose.html', context)


@login_required
@hr_required
def onboarding_tasks(request):
    organization = get_active_organization(request)
    stages = sync_existing_onboarding_participants(organization)
    tasks = OnboardingTask.objects.filter(
        organization=organization,
    ).select_related('employee', 'employee__department', 'employee__category', 'stage', 'assigned_to')
    participants = OnboardingParticipant.objects.filter(
        organization=organization,
    ).select_related(
        'stage',
        'applicant',
        'applicant__category',
        'applicant__department',
        'employee',
        'employee__category',
        'employee__department',
        'invitation',
    )

    search_query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    category = request.GET.get('category', '').strip()
    stage_filter = request.GET.get('stage', '').strip()
    today = timezone.localdate()

    if search_query:
        tasks = tasks.filter(
            Q(title__icontains=search_query)
            | Q(notes__icontains=search_query)
            | Q(employee__first_name__icontains=search_query)
            | Q(employee__last_name__icontains=search_query)
            | Q(employee__employee_id__icontains=search_query)
        )
        participants = participants.filter(
            Q(applicant__first_name__icontains=search_query)
            | Q(applicant__last_name__icontains=search_query)
            | Q(applicant__email__icontains=search_query)
            | Q(applicant__phone__icontains=search_query)
            | Q(applicant__position__icontains=search_query)
            | Q(employee__first_name__icontains=search_query)
            | Q(employee__last_name__icontains=search_query)
            | Q(employee__email__icontains=search_query)
            | Q(employee__phone__icontains=search_query)
            | Q(employee__employee_id__icontains=search_query)
            | Q(employee__position__icontains=search_query)
        )
    if status:
        tasks = tasks.filter(status=status)
    if category:
        tasks = tasks.filter(category=category)
    if stage_filter:
        tasks = tasks.filter(stage_id=stage_filter)
        participants = participants.filter(stage_id=stage_filter)

    stage_rows = []
    for stage in stages:
        stage_rows.append({
            'stage': stage,
            'participants': list(participants.filter(stage=stage).order_by('created_at')),
            'task_count': tasks.filter(stage=stage).count(),
        })
    filtered_task_count = tasks.count()
    tasks = tasks.order_by('status', 'due_date', 'employee__first_name', 'title')
    tasks_page, tasks_pagination_query = paginate_queryset(
        request,
        tasks,
        per_page=20,
        page_param='tasks_page',
    )

    base_tasks = OnboardingTask.objects.filter(organization=organization)
    invitations = OnboardingInvitation.objects.filter(
        organization=organization,
    ).select_related('applicant', 'employee').order_by('-created_at')[:10]
    applicant_base = Applicant.objects.filter(organization=organization)
    invitation_base = OnboardingInvitation.objects.filter(organization=organization)
    participant_base = OnboardingParticipant.objects.filter(organization=organization)
    context = {
        'organization': organization,
        'tasks': tasks_page,
        'tasks_page_obj': tasks_page,
        'tasks_pagination_query': tasks_pagination_query,
        'stages': stages,
        'stage_rows': stage_rows,
        'invitations': invitations,
        'search_query': search_query,
        'selected_status': status,
        'selected_category': category,
        'selected_stage': stage_filter,
        'status_choices': OnboardingTask.STATUS_CHOICES,
        'category_choices': OnboardingTask.CATEGORY_CHOICES,
        'stage_choices': stages,
        'total_tasks': filtered_task_count,
        'pending_count': base_tasks.filter(status='pending').count(),
        'in_progress_count': base_tasks.filter(status='in_progress').count(),
        'completed_count': base_tasks.filter(status='completed').count(),
        'overdue_count': base_tasks.filter(
            due_date__lt=today,
        ).exclude(status__in=['completed', 'waived']).count(),
        'applicant_count': applicant_base.count(),
        'submitted_applicant_count': applicant_base.filter(status='submitted').count(),
        'converted_applicant_count': applicant_base.filter(status='converted').count(),
        'active_invitation_count': invitation_base.filter(status__in=['sent', 'opened']).count(),
        'active_participant_count': participant_base.filter(status='active').count(),
        'completed_participant_count': participant_base.filter(status='completed').count(),
        'page_title': 'Onboarding',
    }
    return render(request, 'attendance/onboarding_tasks.html', context)


@login_required
@hr_required
def onboarding_task_create(request, employee_pk=None):
    organization = get_active_organization(request)
    ensure_default_onboarding_stages(organization)
    employee = None
    stage = None
    if employee_pk:
        employee = get_object_or_404(Employee, organization=organization, pk=employee_pk)
    stage_pk = request.GET.get('stage')
    if stage_pk:
        stage = get_object_or_404(OnboardingStage, organization=organization, pk=stage_pk, is_active=True)

    if request.method == 'POST':
        form = OnboardingTaskForm(request.POST, organization=organization, employee=employee)
        if form.is_valid():
            task = form.save(commit=False)
            task.organization = organization
            if employee:
                task.employee = employee
            task.save()
            write_audit_log(
                request,
                organization=organization,
                area='employee',
                action='onboarding_task_created',
                target=task,
                summary=f'Created onboarding task {task.title} for {task.employee.full_name}.',
                metadata={'employee_id': task.employee.employee_id, 'status': task.status},
            )
            messages.success(request, f'Onboarding task created for {task.employee.full_name}.')
            return redirect('onboarding_tasks')
    else:
        form = OnboardingTaskForm(organization=organization, employee=employee, initial={'stage': stage})

    context = {
        'form': form,
        'employee': employee,
        'stage': stage,
        'organization': organization,
        'page_title': 'Add Onboarding Task',
    }
    return render(request, 'attendance/onboarding_task_form.html', context)


@login_required
@hr_required
def onboarding_task_edit(request, pk):
    organization = get_active_organization(request)
    task = get_object_or_404(
        OnboardingTask.objects.select_related('employee'),
        organization=organization,
        pk=pk,
    )

    if request.method == 'POST':
        form = OnboardingTaskForm(request.POST, organization=organization, instance=task)
        if form.is_valid():
            task = form.save()
            if task.status == 'completed' and not task.completed_at:
                task.completed_by = request.user
                task.completed_at = timezone.now()
                task.save(update_fields=['completed_by', 'completed_at', 'updated_at'])
            write_audit_log(
                request,
                organization=organization,
                area='employee',
                action='onboarding_task_updated',
                target=task,
                summary=f'Updated onboarding task {task.title} for {task.employee.full_name}.',
                metadata={'employee_id': task.employee.employee_id, 'status': task.status},
            )
            messages.success(request, 'Onboarding task updated.')
            return redirect('onboarding_tasks')
    else:
        form = OnboardingTaskForm(organization=organization, instance=task)

    context = {
        'form': form,
        'task': task,
        'employee': task.employee,
        'organization': organization,
        'page_title': 'Edit Onboarding Task',
    }
    return render(request, 'attendance/onboarding_task_form.html', context)


@login_required
@hr_required
def onboarding_task_complete(request, pk):
    organization = get_active_organization(request)
    task = get_object_or_404(OnboardingTask, organization=organization, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action', 'completed')
        task.status = 'waived' if action == 'waived' else 'completed'
        task.completed_by = request.user
        task.completed_at = timezone.now()
        task.save(update_fields=['status', 'completed_by', 'completed_at', 'updated_at'])
        write_audit_log(
            request,
            organization=organization,
            area='employee',
            action='onboarding_task_closed',
            target=task,
            summary=f'{task.get_status_display()} onboarding task {task.title} for {task.employee.full_name}.',
            metadata={'employee_id': task.employee.employee_id, 'status': task.status},
        )
        messages.success(request, f'Onboarding task marked {task.get_status_display().lower()}.')
    return redirect('onboarding_tasks')


@login_required
@hr_required
def onboarding_task_delete(request, pk):
    organization = get_active_organization(request)
    task = get_object_or_404(
        OnboardingTask.objects.select_related('employee'),
        organization=organization,
        pk=pk,
    )

    if request.method == 'POST':
        title = task.title
        employee_name = task.employee.full_name
        employee_id = task.employee.employee_id
        write_audit_log(
            request,
            organization=organization,
            area='employee',
            action='onboarding_task_deleted',
            target=task,
            summary=f'Deleted onboarding task {title} for {employee_name}.',
            metadata={'employee_id': employee_id},
        )
        task.delete()
        messages.success(request, f'Onboarding task deleted for {employee_name}.')
        return redirect('onboarding_tasks')

    context = {
        'task': task,
        'employee': task.employee,
        'organization': organization,
        'page_title': 'Delete Onboarding Task',
    }
    return render(request, 'attendance/onboarding_task_confirm_delete.html', context)


@login_required
@hr_required
def onboarding_stage_create(request):
    organization = get_active_organization(request)
    ensure_default_onboarding_stages(organization)

    if request.method == 'POST':
        form = OnboardingStageForm(request.POST, organization=organization)
        if form.is_valid():
            stage = form.save()
            write_audit_log(
                request,
                organization=organization,
                area='employee',
                action='onboarding_stage_created',
                target=stage,
                summary=f'Created onboarding stage {stage.title}.',
                metadata={'stage_code': stage.code},
            )
            messages.success(request, f'Onboarding stage "{stage.title}" has been created.')
            return redirect('onboarding_tasks')
    else:
        next_order = (OnboardingStage.objects.filter(organization=organization).count() + 1) * 10
        form = OnboardingStageForm(organization=organization, initial={'order': next_order, 'color': 'primary', 'is_active': True})

    context = {
        'form': form,
        'organization': organization,
        'page_title': 'Create Onboarding Stage',
        'action': 'Create',
    }
    return render(request, 'attendance/onboarding_stage_form.html', context)


@login_required
@hr_required
def onboarding_stage_edit(request, pk):
    organization = get_active_organization(request)
    stage = get_object_or_404(OnboardingStage, organization=organization, pk=pk)

    if request.method == 'POST':
        form = OnboardingStageForm(request.POST, organization=organization, instance=stage)
        if form.is_valid():
            stage = form.save()
            write_audit_log(
                request,
                organization=organization,
                area='employee',
                action='onboarding_stage_updated',
                target=stage,
                summary=f'Updated onboarding stage {stage.title}.',
                metadata={'stage_code': stage.code},
            )
            messages.success(request, f'Onboarding stage "{stage.title}" has been updated.')
            return redirect('onboarding_tasks')
    else:
        form = OnboardingStageForm(organization=organization, instance=stage)

    context = {
        'form': form,
        'stage': stage,
        'organization': organization,
        'page_title': 'Edit Onboarding Stage',
        'action': 'Update',
    }
    return render(request, 'attendance/onboarding_stage_form.html', context)


@login_required
@hr_required
def onboarding_stage_delete(request, pk):
    organization = get_active_organization(request)
    stage = get_object_or_404(OnboardingStage, organization=organization, pk=pk)
    participant_count = stage.participants.count()
    task_count = stage.tasks.count()

    if request.method == 'POST':
        if participant_count:
            messages.warning(request, f'Move everyone out of "{stage.title}" before deleting it.')
            return redirect('onboarding_tasks')

        stage_title = stage.title
        stage_code = stage.code
        write_audit_log(
            request,
            organization=organization,
            area='employee',
            action='onboarding_stage_deleted',
            target=stage,
            summary=f'Deleted onboarding stage {stage_title}.',
            metadata={'stage_code': stage_code, 'task_count': task_count},
        )
        stage.delete()
        messages.success(request, f'Onboarding stage "{stage_title}" has been deleted.')
        return redirect('onboarding_tasks')

    context = {
        'stage': stage,
        'organization': organization,
        'participant_count': participant_count,
        'task_count': task_count,
        'page_title': 'Delete Onboarding Stage',
    }
    return render(request, 'attendance/onboarding_stage_confirm_delete.html', context)


@login_required
@hr_required
def onboarding_participant_move(request, pk):
    organization = get_active_organization(request)
    participant = get_object_or_404(
        OnboardingParticipant.objects.select_related('stage', 'applicant', 'employee'),
        organization=organization,
        pk=pk,
    )

    wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    if request.method == 'POST':
        stage = get_object_or_404(
            OnboardingStage,
            organization=organization,
            is_active=True,
            pk=request.POST.get('stage'),
        )
        note = request.POST.get('note', '').strip()
        participant.stage = stage
        participant.status = participant_status_for_stage(stage)
        participant.moved_at = timezone.now()
        if note:
            participant.note = note
        participant.completed_at = timezone.now() if stage.code == 'completed' else None
        participant.save(update_fields=['stage', 'status', 'moved_at', 'note', 'completed_at', 'updated_at'])

        if participant.applicant and stage.code == 'hr_review' and participant.applicant.status in ['invited', 'submitted']:
            participant.applicant.status = 'under_review'
            participant.applicant.save(update_fields=['status', 'updated_at'])
        if participant.applicant and stage.code == 'rejected':
            participant.applicant.status = 'rejected'
            participant.applicant.reviewed_by = request.user
            participant.applicant.reviewed_at = timezone.now()
            participant.applicant.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

        write_audit_log(
            request,
            organization=organization,
            area='employee',
            action='onboarding_participant_moved',
            target=participant,
            summary=f'Moved {participant.display_name} to {stage.title}.',
            metadata={'stage_code': stage.code, 'participant_type': participant.participant_type},
        )
        if wants_json:
            return JsonResponse({
                'ok': True,
                'participant_id': participant.pk,
                'stage_id': stage.pk,
                'stage_title': stage.title,
                'participant_status': participant.get_status_display(),
                'source_status': participant.source_status,
            })
        messages.success(request, f'{participant.display_name} moved to {stage.title}.')
    return redirect('onboarding_tasks')


@login_required
@hr_required
def applicant_invite(request):
    organization = get_active_organization(request)

    if request.method == 'POST':
        form = ApplicantInvitationForm(request.POST, organization=organization)
        if form.is_valid():
            with transaction.atomic():
                applicant = form.save(commit=False)
                applicant.invited_by = request.user
                applicant.status = 'invited'
                applicant.save()
                invitation = OnboardingInvitation.objects.create(
                    organization=organization,
                    invitation_type='application',
                    applicant=applicant,
                    email=applicant.email,
                    message=applicant.cover_note,
                    invited_by=request.user,
                )
                send_onboarding_invitation_email(request, invitation)
                sync_onboarding_participant(
                    organization,
                    stage_code='invitation_sent',
                    applicant=applicant,
                    invitation=invitation,
                )
                write_audit_log(
                    request,
                    organization=organization,
                    area='employee',
                    action='applicant_invited',
                    target=applicant,
                    summary=f'Invited applicant {applicant.full_name}.',
                    metadata={'email': applicant.email, 'category': applicant.category.code},
                )
            messages.success(request, f'Application invitation sent to {applicant.email}.')
            return redirect('onboarding_tasks')
    else:
        form = ApplicantInvitationForm(organization=organization)

    context = {
        'form': form,
        'organization': organization,
        'page_title': 'Invite Applicant',
    }
    return render(request, 'attendance/applicant_invite_form.html', context)


@login_required
@hr_required
def existing_employee_onboarding_invite(request):
    organization = get_active_organization(request)

    if request.method == 'POST':
        form = ExistingEmployeeOnboardingInviteForm(request.POST, organization=organization)
        if form.is_valid():
            employee = form.cleaned_data['employee']
            invitation = OnboardingInvitation.objects.create(
                organization=organization,
                invitation_type='employee_setup',
                employee=employee,
                email=employee.email,
                message=form.cleaned_data['message'],
                invited_by=request.user,
            )
            send_onboarding_invitation_email(request, invitation)
            sync_onboarding_participant(
                organization,
                stage_code='profile_setup',
                employee=employee,
                invitation=invitation,
                joining_date=employee.hire_date,
            )
            write_audit_log(
                request,
                organization=organization,
                area='employee',
                action='employee_onboarding_invited',
                target=employee,
                summary=f'Sent onboarding setup invitation to {employee.full_name}.',
                metadata={'employee_id': employee.employee_id, 'email': employee.email},
            )
            messages.success(request, f'Onboarding setup invitation sent to {employee.email}.')
            return redirect('onboarding_tasks')
    else:
        form = ExistingEmployeeOnboardingInviteForm(organization=organization)

    context = {
        'form': form,
        'organization': organization,
        'page_title': 'Invite Existing Employee',
    }
    return render(request, 'attendance/existing_employee_onboarding_invite_form.html', context)


def public_onboarding_invitation(request, token):
    invitation = get_object_or_404(
        OnboardingInvitation.objects.select_related('organization', 'applicant', 'employee'),
        token=token,
    )
    if invitation.is_expired and invitation.status not in ['accepted', 'submitted']:
        invitation.status = 'expired'
        invitation.save(update_fields=['status', 'updated_at'])
        return render(request, 'attendance/public_onboarding_expired.html', {'invitation': invitation})

    if invitation.status == 'sent':
        invitation.status = 'opened'
        invitation.opened_at = timezone.now()
        invitation.save(update_fields=['status', 'opened_at', 'updated_at'])

    if invitation.invitation_type == 'application':
        return applicant_application_submit(request, invitation)
    return employee_onboarding_setup(request, invitation)


def applicant_application_submit(request, invitation):
    applicant = invitation.applicant
    if request.method == 'POST':
        form = ApplicantApplicationForm(request.POST, instance=applicant, organization=invitation.organization)
        if form.is_valid():
            applicant = form.save(commit=False)
            applicant.status = 'submitted'
            applicant.submitted_at = timezone.now()
            applicant.save()
            invitation.status = 'submitted'
            invitation.submitted_at = timezone.now()
            invitation.save(update_fields=['status', 'submitted_at', 'updated_at'])
            sync_onboarding_participant(
                invitation.organization,
                stage_code='application_submitted',
                applicant=applicant,
                invitation=invitation,
            )
            messages.success(request, 'Your application has been submitted.')
            return render(request, 'attendance/public_onboarding_done.html', {
                'invitation': invitation,
                'title': 'Application Submitted',
                'message': 'HR has received your application and will review it.',
            })
    else:
        form = ApplicantApplicationForm(instance=applicant, organization=invitation.organization)

    context = {
        'form': form,
        'invitation': invitation,
        'applicant': applicant,
        'page_title': 'Submit Application',
    }
    return render(request, 'attendance/public_application_form.html', context)


def employee_onboarding_setup(request, invitation):
    employee = invitation.employee
    if request.method == 'POST':
        form = EmployeeOnboardingSetupForm(request.POST, employee=employee)
        if form.is_valid():
            with transaction.atomic():
                if employee.user:
                    user = employee.user
                    user.set_password(form.cleaned_data['password'])
                    user.save(update_fields=['password'])
                else:
                    user = User.objects.create_user(
                        username=form.cleaned_data['username'],
                        email=employee.email,
                        password=form.cleaned_data['password'],
                        first_name=employee.first_name,
                        last_name=employee.last_name,
                    )
                    employee.user = user
                    OrganizationMembership.objects.get_or_create(
                        user=user,
                        organization=employee.organization,
                        defaults={'role': 'employee', 'is_active': True},
                    )
                employee.save(update_fields=[
                    'user',
                    'updated_at',
                ])
                invitation.status = 'accepted'
                invitation.submitted_at = timezone.now()
                invitation.save(update_fields=['status', 'submitted_at', 'updated_at'])
                sync_onboarding_participant(
                    employee.organization,
                    stage_code='pre_arrival',
                    employee=employee,
                    invitation=invitation,
                    joining_date=employee.hire_date,
                )
                login(request, user)
            messages.success(request, 'Your employee account is ready.')
            return redirect('employee_self_service_dashboard')
    else:
        form = EmployeeOnboardingSetupForm(employee=employee)

    context = {
        'form': form,
        'invitation': invitation,
        'employee': employee,
        'page_title': 'Activate Employee Account',
    }
    return render(request, 'attendance/public_employee_setup_form.html', context)


@login_required
@hr_required
def applicant_approve(request, pk):
    organization = get_active_organization(request)
    applicant = get_object_or_404(Applicant, organization=organization, pk=pk)

    if request.method == 'POST':
        if applicant.status == 'converted':
            messages.info(request, f'{applicant.full_name} has already been converted.')
            return redirect('onboarding_tasks')
        if not applicant.gender:
            messages.warning(request, 'Applicant must provide gender before conversion to employee.')
            return redirect('onboarding_tasks')
        with transaction.atomic():
            employee = Employee.objects.create(
                organization=organization,
                category=applicant.category,
                first_name=applicant.first_name,
                middle_name=applicant.middle_name,
                last_name=applicant.last_name,
                email=applicant.email,
                phone=applicant.phone,
                gender=applicant.gender,
                department=applicant.department,
                position=applicant.position,
                hire_date=timezone.localdate(),
                employment_status='active',
                is_active=True,
            )
            applicant.status = 'converted'
            applicant.employee = employee
            applicant.reviewed_by = request.user
            applicant.reviewed_at = timezone.now()
            applicant.save(update_fields=['status', 'employee', 'reviewed_by', 'reviewed_at', 'updated_at'])
            invitation = OnboardingInvitation.objects.create(
                organization=organization,
                invitation_type='employee_setup',
                employee=employee,
                email=employee.email,
                message='Your application has been approved. Please set up your employee profile.',
                invited_by=request.user,
            )
            send_onboarding_invitation_email(request, invitation)
            sync_onboarding_participant(
                organization,
                stage_code='profile_setup',
                applicant=applicant,
                employee=employee,
                invitation=invitation,
                joining_date=employee.hire_date,
            )
            write_audit_log(
                request,
                organization=organization,
                area='employee',
                action='applicant_converted',
                target=employee,
                summary=f'Converted applicant {applicant.full_name} to employee.',
                metadata={'applicant_id': applicant.pk, 'employee_id': employee.employee_id},
            )
        messages.success(request, f'{applicant.full_name} has been converted to employee and sent setup email.')
    return redirect('onboarding_tasks')


@login_required
@hr_required
def applicant_reject(request, pk):
    organization = get_active_organization(request)
    applicant = get_object_or_404(Applicant, organization=organization, pk=pk)
    if request.method == 'POST':
        applicant.status = 'rejected'
        applicant.reviewed_by = request.user
        applicant.reviewed_at = timezone.now()
        applicant.review_note = request.POST.get('review_note', '').strip()
        applicant.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note', 'updated_at'])
        sync_onboarding_participant(
            organization,
            stage_code='rejected',
            applicant=applicant,
            employee=applicant.employee,
            note=applicant.review_note,
        )
        write_audit_log(
            request,
            organization=organization,
            area='employee',
            action='applicant_rejected',
            target=applicant,
            summary=f'Rejected applicant {applicant.full_name}.',
            metadata={'email': applicant.email},
        )
        messages.success(request, f'{applicant.full_name} has been marked as rejected.')
    return redirect('onboarding_tasks')


@login_required
def employee_self_service_dashboard(request):
    """Self-service dashboard for an employee login."""

    employee = getattr(request.user, 'employee_profile', None)
    if not employee:
        messages.info(request, 'Your account is not linked to an employee profile yet.')
        return redirect('dashboard')

    attendance_history = AttendanceRecord.objects.filter(
        organization=employee.organization,
        employee=employee,
    ).order_by('-check_in_time')
    leave_requests_qs = LeaveRequest.objects.filter(
        organization=employee.organization,
        employee=employee,
    ).select_related('leave_type').order_by('-created_at')
    payslips_qs = Payslip.objects.filter(
        employee=employee,
        payroll_run__status__in=['approved', 'paid'],
    ).select_related('payroll_run').order_by('-payroll_run__payroll_month')
    attendance_page, attendance_pagination_query = paginate_queryset(
        request,
        attendance_history,
        per_page=10,
        page_param='attendance_page',
    )
    leave_page, leave_pagination_query = paginate_queryset(
        request,
        leave_requests_qs,
        per_page=10,
        page_param='leave_page',
    )
    payslips_page, payslips_pagination_query = paginate_queryset(
        request,
        payslips_qs,
        per_page=6,
        page_param='payslips_page',
    )
    leave_balances = build_leave_balances(employee)
    today_record = employee.today_attendance
    pending_leave_count = LeaveRequest.objects.filter(
        organization=employee.organization,
        employee=employee,
        status='pending',
    ).count()
    approved_leave_count = LeaveRequest.objects.filter(
        organization=employee.organization,
        employee=employee,
        status='approved',
    ).count()
    manager_pending_count = LeaveRequest.objects.filter(
        organization=employee.organization,
        employee__line_manager=employee,
        status='pending',
        manager_approval_status='pending',
    ).count()

    context = {
        'employee': employee,
        'organization': employee.organization,
        'attendance_history': attendance_page,
        'attendance_page_obj': attendance_page,
        'attendance_pagination_query': attendance_pagination_query,
        'leave_requests': leave_page,
        'leave_page_obj': leave_page,
        'leave_pagination_query': leave_pagination_query,
        'payslips': payslips_page,
        'payslips_page_obj': payslips_page,
        'payslips_pagination_query': payslips_pagination_query,
        'leave_balances': leave_balances,
        'today_record': today_record,
        'pending_leave_count': pending_leave_count,
        'approved_leave_count': approved_leave_count,
        'latest_payslip': payslips_qs.first(),
        'manager_pending_count': manager_pending_count,
        'page_title': 'My Dashboard',
    }
    return render(request, 'attendance/employee_self_service_dashboard.html', context)


@login_required
def employee_my_profile(request):
    employee = getattr(request.user, 'employee_profile', None)
    if not employee:
        messages.info(request, 'Your account is not linked to an employee profile yet.')
        return redirect('dashboard')

    employee = Employee.objects.select_related(
        'organization',
        'category',
        'department',
        'line_manager',
        'supervisor',
    ).prefetch_related(
        'educations',
        'certifications',
        'work_experiences',
        'documents',
    ).get(pk=employee.pk)

    context = {
        'employee': employee,
        'organization': employee.organization,
        'page_title': 'My Profile',
    }
    return render(request, 'attendance/employee_my_profile.html', context)


@login_required
def employee_my_documents(request):
    employee = getattr(request.user, 'employee_profile', None)
    if not employee:
        messages.info(request, 'Your account is not linked to an employee profile yet.')
        return redirect('dashboard')

    documents = employee.documents.order_by('-uploaded_at', 'title')
    documents_page, documents_pagination_query = paginate_queryset(
        request,
        documents,
        per_page=20,
        page_param='documents_page',
    )
    context = {
        'employee': employee,
        'organization': employee.organization,
        'documents': documents_page,
        'documents_page_obj': documents_page,
        'documents_pagination_query': documents_pagination_query,
        'document_count': documents.count(),
        'page_title': 'My Documents',
    }
    return render(request, 'attendance/employee_my_documents.html', context)


@login_required
def employee_my_document_upload(request):
    employee = getattr(request.user, 'employee_profile', None)
    if not employee:
        messages.info(request, 'Your account is not linked to an employee profile yet.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = EmployeeDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save(commit=False)
            document.employee = employee
            document.save()
            write_audit_log(
                request,
                organization=employee.organization,
                area='employee',
                action='employee_document_uploaded_self_service',
                target=document,
                summary=f'{employee.full_name} uploaded document {document.title}.',
                metadata={'employee_id': employee.employee_id, 'document_type': document.document_type},
            )
            messages.success(request, 'Your document has been uploaded.')
            return redirect('employee_my_documents')
    else:
        form = EmployeeDocumentForm()

    context = {
        'form': form,
        'employee': employee,
        'organization': employee.organization,
        'page_title': 'Upload My Document',
    }
    return render(request, 'attendance/employee_document_form.html', context)


@login_required
def employee_my_document_edit(request, pk):
    employee = getattr(request.user, 'employee_profile', None)
    if not employee:
        messages.info(request, 'Your account is not linked to an employee profile yet.')
        return redirect('dashboard')

    document = get_object_or_404(EmployeeDocument, employee=employee, pk=pk)
    if request.method == 'POST':
        form = EmployeeDocumentForm(request.POST, request.FILES, instance=document)
        if form.is_valid():
            document = form.save()
            write_audit_log(
                request,
                organization=employee.organization,
                area='employee',
                action='employee_document_updated_self_service',
                target=document,
                summary=f'{employee.full_name} updated document {document.title}.',
                metadata={'employee_id': employee.employee_id, 'document_type': document.document_type},
            )
            messages.success(request, 'Your document has been updated.')
            return redirect('employee_my_documents')
    else:
        form = EmployeeDocumentForm(instance=document)

    context = {
        'form': form,
        'document': document,
        'employee': employee,
        'organization': employee.organization,
        'page_title': 'Edit My Document',
    }
    return render(request, 'attendance/employee_document_form.html', context)


@login_required
def employee_leave_request_create(request):
    employee = getattr(request.user, 'employee_profile', None)
    if not employee:
        messages.info(request, 'Your account is not linked to an employee profile yet.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = LeaveRequestForm(request.POST, organization=employee.organization, employee=employee)
        if form.is_valid():
            leave_request = form.save()
            write_audit_log(
                request,
                organization=employee.organization,
                area='leave',
                action='leave_requested_self_service',
                target=leave_request,
                summary=f'{employee.full_name} submitted a leave request.',
                metadata={'employee_id': employee.employee_id, 'leave_type': leave_request.leave_type.name},
            )
            messages.success(request, f'{leave_request.leave_type.name} request submitted for review.')
            return redirect('employee_self_service_dashboard')
    else:
        form = LeaveRequestForm(organization=employee.organization, employee=employee)

    context = {
        'form': form,
        'employee': employee,
        'organization': employee.organization,
        'page_title': 'Request Leave',
        'is_self_service': True,
    }
    return render(request, 'attendance/leave_request_form.html', context)


@login_required
@manager_required
def manager_dashboard(request):
    manager = getattr(request.user, 'employee_profile', None)
    organization = manager.organization if manager else get_active_organization(request)
    today = timezone.localdate()

    if manager and not user_has_hr_access(request.user):
        team_members = Employee.objects.filter(
            organization=organization,
            line_manager=manager,
            is_active=True,
        ).select_related('department', 'category')
    else:
        team_members = Employee.objects.filter(
            organization=organization,
            is_active=True,
        ).select_related('department', 'category')

    team_member_ids = list(team_members.values_list('id', flat=True))
    pending_leave_requests = LeaveRequest.objects.filter(
        organization=organization,
        employee_id__in=team_member_ids,
        status='pending',
        manager_approval_status='pending',
    ).select_related('employee', 'leave_type').order_by('created_at')
    recent_leave_requests = LeaveRequest.objects.filter(
        organization=organization,
        employee_id__in=team_member_ids,
    ).select_related('employee', 'leave_type').order_by('-created_at')[:8]
    todays_records = AttendanceRecord.objects.filter(
        organization=organization,
        employee_id__in=team_member_ids,
        **local_date_range_filter('check_in_time', today),
    ).select_related('employee')
    present_today = todays_records.values('employee_id').distinct().count()
    late_today = count_distinct_late_employees(todays_records)
    team_by_department = team_members.values('department__name').annotate(total=Count('id')).order_by('department__name')
    team_by_category = team_members.values('category__name').annotate(total=Count('id')).order_by('category__name')
    open_attendance_count = todays_records.filter(check_out_time__isnull=True).values('employee_id').distinct().count()
    completed_attendance_count = todays_records.filter(check_out_time__isnull=False).values('employee_id').distinct().count()

    context = {
        'organization': organization,
        'manager': manager,
        'team_members': team_members.order_by('first_name', 'last_name')[:10],
        'team_count': len(team_member_ids),
        'present_today': present_today,
        'late_today': late_today,
        'absent_today': max(len(team_member_ids) - present_today, 0),
        'open_attendance_count': open_attendance_count,
        'completed_attendance_count': completed_attendance_count,
        'team_by_department': team_by_department,
        'team_by_category': team_by_category,
        'pending_leave_requests': pending_leave_requests[:8],
        'pending_leave_count': pending_leave_requests.count(),
        'recent_leave_requests': recent_leave_requests,
        'page_title': 'Manager Dashboard',
    }
    return render(request, 'attendance/manager_dashboard.html', context)


@login_required
@manager_required
def manager_team(request):
    manager = getattr(request.user, 'employee_profile', None)
    organization = manager.organization if manager else get_active_organization(request)
    today = timezone.localdate()

    if manager and not user_has_hr_access(request.user):
        team_members = Employee.objects.filter(
            organization=organization,
            line_manager=manager,
            is_active=True,
        )
    else:
        team_members = Employee.objects.filter(
            organization=organization,
            is_active=True,
        )

    team_members = team_members.select_related('department', 'category', 'line_manager').order_by('first_name', 'last_name')
    team_member_ids = list(team_members.values_list('id', flat=True))
    todays_records = AttendanceRecord.objects.filter(
        organization=organization,
        employee_id__in=team_member_ids,
        **local_date_range_filter('check_in_time', today),
    ).select_related('employee').order_by('employee_id', '-check_in_time')
    todays_record_by_employee = {}
    for record in todays_records:
        todays_record_by_employee.setdefault(record.employee_id, record)

    team_rows = []
    for member in team_members:
        record = todays_record_by_employee.get(member.id)
        if record and record.check_out_time:
            status = 'Completed'
            status_color = 'primary'
        elif record:
            status = 'Checked In'
            status_color = 'success'
        else:
            status = 'Not In'
            status_color = 'secondary'
        team_rows.append({
            'member': member,
            'today_record': record,
            'status': status,
            'status_color': status_color,
        })
    team_rows_page, team_rows_pagination_query = paginate_queryset(
        request,
        team_rows,
        per_page=25,
        page_param='team_page',
    )

    context = {
        'organization': organization,
        'manager': manager,
        'team_rows': team_rows_page,
        'team_rows_page_obj': team_rows_page,
        'team_rows_pagination_query': team_rows_pagination_query,
        'team_count': len(team_rows),
        'checked_in_count': sum(1 for row in team_rows if row['status'] == 'Checked In'),
        'completed_count': sum(1 for row in team_rows if row['status'] == 'Completed'),
        'not_in_count': sum(1 for row in team_rows if row['status'] == 'Not In'),
        'page_title': 'My Team',
    }
    return render(request, 'attendance/manager_team.html', context)


@login_required
@manager_required
def manager_leave_requests(request):
    manager = getattr(request.user, 'employee_profile', None)
    organization = manager.organization if manager else get_active_organization(request)
    requests_qs = LeaveRequest.objects.filter(
        organization=organization,
        status='pending',
    ).select_related('employee', 'leave_type')

    if manager and not user_has_hr_access(request.user):
        requests_qs = requests_qs.filter(employee__line_manager=manager)
    leave_requests_page, leave_requests_pagination_query = paginate_queryset(
        request,
        requests_qs.order_by('created_at'),
        per_page=20,
        page_param='leave_page',
    )

    context = {
        'organization': organization,
        'leave_requests': leave_requests_page,
        'leave_requests_page_obj': leave_requests_page,
        'leave_requests_pagination_query': leave_requests_pagination_query,
        'page_title': 'Manager Leave Approvals',
    }
    return render(request, 'attendance/manager_leave_requests.html', context)


@login_required
@manager_required
def manager_leave_request_approve(request, pk):
    leave_request = get_manager_leave_request(request, pk)

    if request.method == 'POST':
        form = LeaveReviewForm(request.POST)
        if form.is_valid():
            leave_request.manager_approval_status = 'approved'
            leave_request.manager_reviewed_by = request.user
            leave_request.manager_reviewed_at = timezone.now()
            leave_request.manager_review_note = form.cleaned_data['review_note']
            leave_request.save()
            write_audit_log(
                request,
                organization=leave_request.organization,
                area='leave',
                action='leave_manager_approved',
                target=leave_request,
                summary=f'Manager approved leave for {leave_request.employee.full_name}.',
                metadata={'employee_id': leave_request.employee.employee_id},
            )
            messages.success(request, f'Manager approval recorded for {leave_request.employee.full_name}.')
            return redirect('manager_leave_requests')
    else:
        form = LeaveReviewForm()

    context = {
        'form': form,
        'leave_request': leave_request,
        'organization': leave_request.organization,
        'action': 'Manager Approve',
        'page_title': 'Manager Approve Leave',
    }
    return render(request, 'attendance/leave_request_review.html', context)


@login_required
@manager_required
def manager_leave_request_reject(request, pk):
    leave_request = get_manager_leave_request(request, pk)

    if request.method == 'POST':
        form = LeaveReviewForm(request.POST)
        if form.is_valid():
            leave_request.manager_approval_status = 'rejected'
            leave_request.manager_reviewed_by = request.user
            leave_request.manager_reviewed_at = timezone.now()
            leave_request.manager_review_note = form.cleaned_data['review_note']
            leave_request.status = 'rejected'
            leave_request.reviewed_by = request.user
            leave_request.reviewed_at = timezone.now()
            leave_request.review_note = form.cleaned_data['review_note']
            leave_request.save()
            write_audit_log(
                request,
                organization=leave_request.organization,
                area='leave',
                action='leave_manager_rejected',
                target=leave_request,
                summary=f'Manager rejected leave for {leave_request.employee.full_name}.',
                metadata={'employee_id': leave_request.employee.employee_id},
            )
            messages.success(request, f'Leave rejected for {leave_request.employee.full_name}.')
            return redirect('manager_leave_requests')
    else:
        form = LeaveReviewForm()

    context = {
        'form': form,
        'leave_request': leave_request,
        'organization': leave_request.organization,
        'action': 'Manager Reject',
        'page_title': 'Manager Reject Leave',
    }
    return render(request, 'attendance/leave_request_review.html', context)


# ==================== ATTENDANCE MANAGEMENT VIEWS ====================

@login_required
@hr_required
def attendance_reports(request):
    """Attendance reports with date filtering"""
    
    organization = get_active_organization(request)
    # Date filter form
    date_form = DateFilterForm(request.GET or None, organization=organization)
    records = build_filtered_attendance_queryset(date_form, organization, default_to_today=True)
    exceptions = build_filtered_exception_queryset(date_form, organization, default_to_today=True)
    records = records.order_by('-check_in_time')
    total_hours = sum((record.hours_worked or 0) for record in records)
    late_records = sum(1 for record in records if record.is_late)
    exception_count = exceptions.count()
    records_page, records_pagination_query = paginate_queryset(
        request,
        records,
        per_page=25,
        page_param='attendance_page',
    )
    exceptions_ordered = exceptions.order_by('-start_date', 'employee__first_name')
    exceptions_page, exceptions_pagination_query = paginate_queryset(
        request,
        exceptions_ordered,
        per_page=20,
        page_param='exceptions_page',
    )
    recent_attendance_by_date = {}
    recent_records = (
        AttendanceRecord.objects
        .filter(organization=organization, employee__is_active=True)
        .only('id', 'employee_id', 'check_in_time', 'check_out_time')
        .order_by('-check_in_time')
    )
    for record in recent_records:
        attendance_date = timezone.localtime(record.check_in_time).date()
        day_stats = recent_attendance_by_date.setdefault(
            attendance_date,
            {
                'attendance_date': attendance_date,
                'employee_ids': set(),
                'total_records': 0,
                'completed_records': 0,
            },
        )
        day_stats['employee_ids'].add(record.employee_id)
        day_stats['total_records'] += 1
        if record.check_out_time is not None:
            day_stats['completed_records'] += 1

    recent_attendance_days_qs = [
        {
            'attendance_date': attendance_date,
            'people_count': len(day_stats['employee_ids']),
            'total_records': day_stats['total_records'],
            'completed_records': day_stats['completed_records'],
        }
        for attendance_date, day_stats in sorted(
            recent_attendance_by_date.items(),
            key=lambda item: item[0],
            reverse=True,
        )
    ]
    recent_attendance_days_page, recent_attendance_days_pagination_query = paginate_queryset(
        request,
        recent_attendance_days_qs,
        per_page=10,
        page_param='days_page',
    )
    
    context = {
        'records': records_page,
        'records_page_obj': records_page,
        'records_pagination_query': records_pagination_query,
        'organization': organization,
        'date_form': date_form,
        'total_hours': round(total_hours, 2),
        'late_records': late_records,
        'attendance_exceptions': exceptions_page,
        'exceptions_page_obj': exceptions_page,
        'exceptions_pagination_query': exceptions_pagination_query,
        'exception_count': exception_count,
        'recent_attendance_days': recent_attendance_days_page,
        'recent_attendance_days_page_obj': recent_attendance_days_page,
        'recent_attendance_days_pagination_query': recent_attendance_days_pagination_query,
        'page_title': 'Attendance Reports',
    }
    
    return render(request, 'attendance/attendance_reports.html', context)


@login_required
@hr_required
def manual_attendance_add(request):
    """HR manually adds attendance record"""
    
    organization = get_active_organization(request)
    if request.method == 'POST':
        form = ManualAttendanceForm(request.POST, organization=organization)
        if form.is_valid():
            employee = form.cleaned_data['employee']
            entry_type = form.cleaned_data['entry_type']

            if entry_type == 'work_session':
                check_in = form.cleaned_data['check_in_time']
                check_out = form.cleaned_data['check_out_time']
                attendance_record = AttendanceRecord.objects.create(
                    organization=organization,
                    employee=employee,
                    check_in_time=check_in,
                    check_out_time=check_out
                )
                write_audit_log(
                    request,
                    organization=organization,
                    area='attendance',
                    action='manual_attendance_created',
                    target=attendance_record,
                    summary=f'Manual attendance recorded for {employee.full_name}.',
                    metadata={'employee_id': employee.employee_id, 'check_in': check_in.isoformat()},
                )
                messages.success(request, f'Attendance recorded for {employee.full_name}')
            else:
                attendance_exception = AttendanceException.objects.create(
                    organization=organization,
                    employee=employee,
                    exception_type=form.cleaned_data['exception_type'].code,
                    start_date=form.cleaned_data['exception_start_date'],
                    end_date=form.cleaned_data['exception_end_date'],
                    notes=form.cleaned_data['notes'],
                )
                write_audit_log(
                    request,
                    organization=organization,
                    area='attendance',
                    action='attendance_exception_created',
                    target=attendance_exception,
                    summary=f'{attendance_exception.get_exception_type_display()} recorded for {employee.full_name}.',
                    metadata={'employee_id': employee.employee_id, 'exception_type': attendance_exception.exception_type},
                )
                messages.success(
                    request,
                    f'{attendance_exception.get_exception_type_display()} recorded for {employee.full_name}.'
                )
            return redirect('attendance_reports')
    else:
        form = ManualAttendanceForm(organization=organization)
    
    context = {
        'form': form,
        'organization': organization,
        'page_title': 'Add Attendance Record',
    }
    
    return render(request, 'attendance/manual_attendance_form.html', context)


@login_required
@hr_required
def attendance_exception_types(request):
    """Manage configurable attendance exception types."""

    organization = get_active_organization(request)
    if request.method == 'POST':
        form = AttendanceExceptionTypeForm(request.POST, organization=organization)
        if form.is_valid():
            exception_type = form.save()
            messages.success(request, f'{exception_type.name} has been added to attendance exception types.')
            return redirect('attendance_exception_types')
    else:
        form = AttendanceExceptionTypeForm(initial={'color': 'primary', 'is_active': True}, organization=organization)
    exception_types_page, exception_types_pagination_query = paginate_queryset(
        request,
        AttendanceExceptionType.objects.filter(organization=organization).order_by('name'),
        per_page=20,
        page_param='exception_types_page',
    )

    context = {
        'form': form,
        'organization': organization,
        'exception_types': exception_types_page,
        'exception_types_page_obj': exception_types_page,
        'exception_types_pagination_query': exception_types_pagination_query,
        'page_title': 'Attendance Exception Types',
    }
    return render(request, 'attendance/attendance_exception_types.html', context)


# ==================== LEAVE MANAGEMENT VIEWS ====================

@login_required
@hr_required
def leave_requests(request):
    organization = get_active_organization(request)
    status = request.GET.get('status', '')
    search_query = request.GET.get('search', '').strip()
    today = timezone.localdate()
    current_month_start = today.replace(day=1)
    upcoming_limit = today + timedelta(days=30)

    requests_qs = LeaveRequest.objects.filter(
        organization=organization
    ).select_related('employee', 'employee__department', 'leave_type', 'reviewed_by').order_by('-created_at')

    if status:
        requests_qs = requests_qs.filter(status=status)
    if search_query:
        requests_qs = requests_qs.filter(
            Q(employee__first_name__icontains=search_query) |
            Q(employee__last_name__icontains=search_query) |
            Q(employee__employee_id__icontains=search_query) |
            Q(leave_type__name__icontains=search_query)
        )

    active_employees = Employee.objects.filter(
        organization=organization,
        is_active=True,
    ).select_related('category', 'department').order_by('first_name', 'last_name')
    if search_query:
        active_employees = active_employees.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(employee_id__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(department__name__icontains=search_query)
        )

    leave_employee_rows = [
        build_employee_leave_overview(employee, year=today.year)
        for employee in active_employees
    ]
    leave_employee_page, leave_employee_pagination_query = paginate_queryset(
        request,
        leave_employee_rows,
        per_page=20,
        page_param='employees_page',
    )
    recent_leave_page, recent_leave_pagination_query = paginate_queryset(
        request,
        requests_qs,
        per_page=15,
        page_param='leave_page',
    )

    context = {
        'organization': organization,
        'leave_requests': recent_leave_page,
        'leave_page_obj': recent_leave_page,
        'leave_pagination_query': recent_leave_pagination_query,
        'leave_employee_rows': leave_employee_page,
        'leave_employee_page_obj': leave_employee_page,
        'leave_employee_pagination_query': leave_employee_pagination_query,
        'selected_status': status,
        'search_query': search_query,
        'status_choices': LeaveRequest.STATUS_CHOICES,
        'pending_count': LeaveRequest.objects.filter(organization=organization, status='pending').count(),
        'approved_count': LeaveRequest.objects.filter(organization=organization, status='approved').count(),
        'on_leave_today_count': LeaveRequest.objects.filter(
            organization=organization,
            status='approved',
            start_date__lte=today,
            end_date__gte=today,
        ).values('employee_id').distinct().count(),
        'approved_this_month_count': LeaveRequest.objects.filter(
            organization=organization,
            status='approved',
            start_date__gte=current_month_start,
            start_date__lte=today,
        ).count(),
        'upcoming_leave_count': LeaveRequest.objects.filter(
            organization=organization,
            status='approved',
            start_date__gt=today,
            start_date__lte=upcoming_limit,
        ).count(),
        'low_balance_count': sum(1 for row in leave_employee_rows if row['total_remaining'] <= 3),
        'recent_leave_requests': recent_leave_page,
        'today': today,
        'page_title': 'Leave Management',
    }
    return render(request, 'attendance/leave_requests.html', context)


@login_required
@hr_required
def employee_leave_detail(request, employee_pk):
    organization = get_active_organization(request)
    employee = get_object_or_404(
        Employee.objects.select_related('category', 'department', 'line_manager'),
        organization=organization,
        pk=employee_pk,
    )
    today = timezone.localdate()
    overview = build_employee_leave_overview(employee, year=today.year)
    leave_requests_qs = LeaveRequest.objects.filter(
        organization=organization,
        employee=employee,
    ).select_related('leave_type', 'reviewed_by').order_by('-created_at')
    leave_requests_page, leave_requests_pagination_query = paginate_queryset(
        request,
        leave_requests_qs,
        per_page=15,
        page_param='leave_page',
    )

    context = {
        'organization': organization,
        'employee': employee,
        'overview': overview,
        'leave_requests': leave_requests_page,
        'leave_requests_page_obj': leave_requests_page,
        'leave_requests_pagination_query': leave_requests_pagination_query,
        'approved_requests': leave_requests_qs.filter(status='approved')[:8],
        'pending_requests': leave_requests_qs.filter(status='pending'),
        'page_title': f'Leave: {employee.full_name}',
        'today': today,
    }
    return render(request, 'attendance/employee_leave_detail.html', context)


@login_required
@hr_required
def leave_request_detail(request, pk):
    organization = get_active_organization(request)
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related(
            'employee',
            'employee__category',
            'employee__department',
            'leave_type',
            'reviewed_by',
        ),
        pk=pk,
        organization=organization,
    )
    balances = build_leave_balances(leave_request.employee)
    selected_balance = next(
        (balance for balance in balances if balance['leave_type'].pk == leave_request.leave_type_id),
        None,
    )
    overlapping_requests = LeaveRequest.objects.filter(
        organization=organization,
        employee=leave_request.employee,
        start_date__lte=leave_request.end_date,
        end_date__gte=leave_request.start_date,
    ).exclude(pk=leave_request.pk).select_related('leave_type').order_by('-created_at')

    context = {
        'organization': organization,
        'leave_request': leave_request,
        'balances': balances,
        'selected_balance': selected_balance,
        'overlapping_requests': overlapping_requests,
        'page_title': f'Leave Request: {leave_request.employee.full_name}',
    }
    return render(request, 'attendance/leave_request_detail.html', context)


@login_required
@hr_required
def leave_request_create(request):
    organization = get_active_organization(request)

    if request.method == 'POST':
        form = LeaveRequestForm(request.POST, organization=organization)
        if form.is_valid():
            leave_request = form.save()
            write_audit_log(
                request,
                organization=organization,
                area='leave',
                action='leave_requested_by_hr',
                target=leave_request,
                summary=f'HR submitted leave request for {leave_request.employee.full_name}.',
                metadata={'employee_id': leave_request.employee.employee_id, 'leave_type': leave_request.leave_type.name},
            )
            messages.success(request, f'Leave request for {leave_request.employee.full_name} has been submitted.')
            return redirect('leave_request_detail', pk=leave_request.pk)
    else:
        form = LeaveRequestForm(organization=organization)

    context = {
        'form': form,
        'organization': organization,
        'page_title': 'New Leave Request',
    }
    return render(request, 'attendance/leave_request_form.html', context)


@login_required
@hr_required
def leave_request_edit(request, pk):
    organization = get_active_organization(request)
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related('employee', 'leave_type'),
        pk=pk,
        organization=organization,
    )
    if leave_request.status != 'pending':
        messages.warning(request, 'Only pending leave requests can be edited. Cancel or recreate reviewed requests instead.')
        return redirect('leave_request_detail', pk=leave_request.pk)

    if request.method == 'POST':
        form = LeaveRequestForm(request.POST, organization=organization, instance=leave_request)
        if form.is_valid():
            leave_request = form.save()
            write_audit_log(
                request,
                organization=organization,
                area='leave',
                action='leave_request_updated',
                target=leave_request,
                summary=f'Updated leave request for {leave_request.employee.full_name}.',
                metadata={'employee_id': leave_request.employee.employee_id, 'leave_type': leave_request.leave_type.name},
            )
            messages.success(request, 'Leave request has been updated.')
            return redirect('leave_request_detail', pk=leave_request.pk)
    else:
        form = LeaveRequestForm(organization=organization, instance=leave_request)

    context = {
        'form': form,
        'organization': organization,
        'leave_request': leave_request,
        'page_title': 'Edit Leave Request',
        'action': 'Update',
    }
    return render(request, 'attendance/leave_request_form.html', context)


@login_required
@hr_required
def leave_request_approve(request, pk):
    organization = get_active_organization(request)
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related('employee', 'leave_type'),
        pk=pk,
        organization=organization,
    )
    if leave_request.status != 'pending':
        messages.warning(request, 'Only pending leave requests can be approved.')
        return redirect('leave_request_detail', pk=leave_request.pk)

    if request.method == 'POST':
        form = LeaveReviewForm(request.POST)
        if form.is_valid():
            leave_request.status = 'approved'
            leave_request.reviewed_by = request.user
            leave_request.reviewed_at = timezone.now()
            leave_request.review_note = form.cleaned_data['review_note']
            leave_request.save()
            sync_leave_attendance_exception(leave_request)
            write_audit_log(
                request,
                organization=organization,
                area='leave',
                action='leave_hr_approved',
                target=leave_request,
                summary=f'HR approved leave for {leave_request.employee.full_name}.',
                metadata={'employee_id': leave_request.employee.employee_id},
            )
            messages.success(request, f'Leave approved for {leave_request.employee.full_name}.')
            return redirect('leave_request_detail', pk=leave_request.pk)
    else:
        form = LeaveReviewForm()

    context = {
        'form': form,
        'leave_request': leave_request,
        'organization': organization,
        'action': 'Approve',
        'page_title': 'Approve Leave',
    }
    return render(request, 'attendance/leave_request_review.html', context)


@login_required
@hr_required
def leave_request_reject(request, pk):
    organization = get_active_organization(request)
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related('employee', 'leave_type'),
        pk=pk,
        organization=organization,
    )
    if leave_request.status != 'pending':
        messages.warning(request, 'Only pending leave requests can be rejected.')
        return redirect('leave_request_detail', pk=leave_request.pk)

    if request.method == 'POST':
        form = LeaveReviewForm(request.POST)
        if form.is_valid():
            leave_request.status = 'rejected'
            leave_request.reviewed_by = request.user
            leave_request.reviewed_at = timezone.now()
            leave_request.review_note = form.cleaned_data['review_note']
            leave_request.save()
            write_audit_log(
                request,
                organization=organization,
                area='leave',
                action='leave_hr_rejected',
                target=leave_request,
                summary=f'HR rejected leave for {leave_request.employee.full_name}.',
                metadata={'employee_id': leave_request.employee.employee_id},
            )
            messages.success(request, f'Leave rejected for {leave_request.employee.full_name}.')
            return redirect('leave_request_detail', pk=leave_request.pk)
    else:
        form = LeaveReviewForm()

    context = {
        'form': form,
        'leave_request': leave_request,
        'organization': organization,
        'action': 'Reject',
        'page_title': 'Reject Leave',
    }
    return render(request, 'attendance/leave_request_review.html', context)


@login_required
@hr_required
def leave_request_cancel(request, pk):
    organization = get_active_organization(request)
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related('employee', 'leave_type'),
        pk=pk,
        organization=organization,
    )
    if leave_request.status not in ['pending', 'approved']:
        messages.warning(request, 'Only pending or approved leave requests can be cancelled.')
        return redirect('leave_request_detail', pk=leave_request.pk)

    if request.method == 'POST':
        form = LeaveReviewForm(request.POST)
        if form.is_valid():
            leave_request.status = 'cancelled'
            leave_request.reviewed_by = request.user
            leave_request.reviewed_at = timezone.now()
            leave_request.review_note = form.cleaned_data['review_note']
            leave_request.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note', 'updated_at'])
            remove_synced_leave_attendance_exception(leave_request)
            write_audit_log(
                request,
                organization=organization,
                area='leave',
                action='leave_request_cancelled',
                target=leave_request,
                summary=f'Cancelled leave request for {leave_request.employee.full_name}.',
                metadata={'employee_id': leave_request.employee.employee_id, 'leave_type': leave_request.leave_type.name},
            )
            messages.success(request, f'Leave request for {leave_request.employee.full_name} has been cancelled.')
            return redirect('leave_request_detail', pk=leave_request.pk)
    else:
        form = LeaveReviewForm()

    context = {
        'form': form,
        'leave_request': leave_request,
        'organization': organization,
        'action': 'Cancel',
        'page_title': 'Cancel Leave',
    }
    return render(request, 'attendance/leave_request_review.html', context)


@login_required
@hr_required
def leave_request_delete(request, pk):
    organization = get_active_organization(request)
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related('employee', 'leave_type'),
        pk=pk,
        organization=organization,
    )

    if request.method == 'POST':
        employee = leave_request.employee
        leave_type_name = leave_request.leave_type.name
        start_date = leave_request.start_date
        end_date = leave_request.end_date
        remove_synced_leave_attendance_exception(leave_request)
        write_audit_log(
            request,
            organization=organization,
            area='leave',
            action='leave_request_deleted',
            target=leave_request,
            summary=f'Deleted leave request for {employee.full_name}.',
            metadata={
                'employee_id': employee.employee_id,
                'leave_type': leave_type_name,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
            },
        )
        leave_request.delete()
        messages.success(request, f'{leave_type_name} request for {employee.full_name} has been deleted.')
        return redirect('employee_leave_detail', employee_pk=employee.pk)

    context = {
        'leave_request': leave_request,
        'organization': organization,
        'page_title': 'Delete Leave Request',
    }
    return render(request, 'attendance/leave_request_confirm_delete.html', context)


# ==================== PAYROLL VIEWS ====================

@login_required
@payroll_required
def payroll_runs(request):
    organization = get_active_organization(request)
    runs = PayrollRun.objects.filter(organization=organization).prefetch_related('payslips').order_by('-payroll_month', '-created_at')
    runs_page, runs_pagination_query = paginate_queryset(
        request,
        runs,
        per_page=20,
        page_param='runs_page',
    )

    context = {
        'organization': organization,
        'payroll_runs': runs_page,
        'payroll_runs_page_obj': runs_page,
        'payroll_runs_pagination_query': runs_pagination_query,
        'page_title': 'Payroll',
    }
    return render(request, 'attendance/payroll_runs.html', context)


@login_required
@payroll_required
def finance_dashboard(request):
    organization = get_active_organization(request)
    today = timezone.localdate()
    current_month = today.replace(day=1)
    payroll_runs_qs = PayrollRun.objects.filter(organization=organization).prefetch_related('payslips')
    latest_runs = payroll_runs_qs[:5]
    current_run = payroll_runs_qs.filter(payroll_month=current_month).first()
    approved_unpaid_runs = payroll_runs_qs.filter(status='approved')
    paid_runs = payroll_runs_qs.filter(status='paid')
    active_employees = Employee.objects.filter(organization=organization, is_active=True)
    payroll_status_counts = {
        status: payroll_runs_qs.filter(status=status).count()
        for status, _ in PayrollRun.STATUS_CHOICES
    }
    employees_with_salary = active_employees.filter(
        Q(basic_salary__gt=0)
        | Q(housing_allowance__gt=0)
        | Q(transport_allowance__gt=0)
        | Q(other_allowances__gt=0)
    ).count()
    employees_missing_bank = active_employees.filter(
        Q(bank_name='') | Q(bank_account_name='') | Q(bank_account_number='')
    ).count()

    context = {
        'organization': organization,
        'current_month': current_month,
        'current_run': current_run,
        'latest_runs': latest_runs,
        'total_payroll_runs': payroll_runs_qs.count(),
        'payroll_status_counts': payroll_status_counts,
        'approved_unpaid_count': approved_unpaid_runs.count(),
        'paid_runs_count': paid_runs.count(),
        'active_payroll_people': active_employees.count(),
        'employees_with_salary': employees_with_salary,
        'employees_missing_bank': employees_missing_bank,
        'monthly_gross_basis': sum((employee.gross_pay for employee in active_employees), 0),
        'monthly_deduction_basis': sum((employee.total_deductions for employee in active_employees), 0),
        'monthly_net_basis': sum((employee.net_pay for employee in active_employees), 0),
        'page_title': 'Finance Dashboard',
    }
    return render(request, 'attendance/finance_dashboard.html', context)


@login_required
@payroll_required
def finance_payroll_readiness(request):
    organization = get_active_organization(request)
    active_employees = Employee.objects.filter(
        organization=organization,
        is_active=True,
    ).select_related('department', 'category').order_by('first_name', 'last_name')
    employees_missing_salary = active_employees.filter(
        basic_salary=0,
        housing_allowance=0,
        transport_allowance=0,
        other_allowances=0,
    )
    employees_missing_bank = active_employees.filter(
        Q(bank_name='') | Q(bank_account_name='') | Q(bank_account_number='')
    )
    draft_runs = PayrollRun.objects.filter(organization=organization, status='draft')
    processed_runs = PayrollRun.objects.filter(organization=organization, status='processed')
    approved_unpaid_runs = PayrollRun.objects.filter(organization=organization, status='approved')

    context = {
        'organization': organization,
        'active_people_count': active_employees.count(),
        'employees_missing_salary': employees_missing_salary,
        'employees_missing_salary_count': employees_missing_salary.count(),
        'employees_missing_bank': employees_missing_bank,
        'employees_missing_bank_count': employees_missing_bank.count(),
        'draft_runs': draft_runs,
        'draft_runs_count': draft_runs.count(),
        'processed_runs': processed_runs,
        'processed_runs_count': processed_runs.count(),
        'approved_unpaid_runs': approved_unpaid_runs,
        'approved_unpaid_count': approved_unpaid_runs.count(),
        'page_title': 'Payroll Readiness',
    }
    return render(request, 'attendance/finance_payroll_readiness.html', context)


@login_required
@payroll_required
def payroll_run_create(request):
    organization = get_active_organization(request)

    if request.method == 'POST':
        form = PayrollRunForm(request.POST, organization=organization)
        if form.is_valid():
            payroll_run = form.save(commit=False)
            payroll_run.created_by = request.user
            payroll_run.save()
            write_audit_log(
                request,
                organization=organization,
                area='payroll',
                action='payroll_run_created',
                target=payroll_run,
                summary=f'Created payroll run {payroll_run.title}.',
                metadata={'payroll_month': payroll_run.payroll_month.isoformat()},
            )
            messages.success(request, f'{payroll_run.title} has been created.')
            return redirect('payroll_run_detail', pk=payroll_run.pk)
    else:
        today = timezone.localdate()
        form = PayrollRunForm(
            initial={
                'title': f'{today:%B %Y} Payroll',
                'payroll_month': today.replace(day=1),
            },
            organization=organization,
        )

    context = {
        'form': form,
        'organization': organization,
        'page_title': 'Create Payroll Run',
    }
    return render(request, 'attendance/payroll_run_form.html', context)


@login_required
@payroll_required
def payroll_run_detail(request, pk):
    organization = get_active_organization(request)
    payroll_run = get_object_or_404(
        PayrollRun.objects.filter(organization=organization).prefetch_related('payslips__employee'),
        pk=pk,
    )

    context = {
        'organization': organization,
        'payroll_run': payroll_run,
        'payslips': payroll_run.payslips.select_related('employee'),
        'page_title': payroll_run.title,
    }
    return render(request, 'attendance/payroll_run_detail.html', context)


@login_required
@require_POST
@payroll_required
def payroll_run_generate(request, pk):
    organization = get_active_organization(request)
    payroll_run = get_object_or_404(PayrollRun, organization=organization, pk=pk)

    if payroll_run.status not in ['draft', 'processed']:
        messages.warning(request, 'Only draft or processed payroll runs can be regenerated.')
        return redirect('payroll_run_detail', pk=payroll_run.pk)

    employees = Employee.objects.filter(
        organization=organization,
        is_active=True,
    ).select_related('department', 'category')
    generated = 0
    with transaction.atomic():
        payroll_run.payslips.all().delete()
        for employee in employees:
            Payslip.objects.create(
                payroll_run=payroll_run,
                employee=employee,
                basic_salary=employee.basic_salary,
                housing_allowance=employee.housing_allowance,
                transport_allowance=employee.transport_allowance,
                other_allowances=employee.other_allowances,
                tax_deduction=employee.tax_deduction,
                pension_deduction=employee.pension_deduction,
                other_deductions=employee.other_deductions,
                bank_name=employee.bank_name,
                bank_account_name=employee.bank_account_name,
                bank_account_number=employee.bank_account_number,
                pension_rsa_pin=employee.pension_rsa_pin,
            )
            generated += 1
        payroll_run.status = 'processed'
        payroll_run.save(update_fields=['status', 'updated_at'])
        write_audit_log(
            request,
            organization=organization,
            area='payroll',
            action='payslips_generated',
            target=payroll_run,
            summary=f'Generated {generated} payslips for {payroll_run.title}.',
            metadata={'generated_count': generated},
        )

    messages.success(request, f'{generated} payslips generated for {payroll_run.title}.')
    return redirect('payroll_run_detail', pk=payroll_run.pk)


@login_required
@require_POST
@payroll_required
def payroll_run_approve(request, pk):
    organization = get_active_organization(request)
    payroll_run = get_object_or_404(PayrollRun, organization=organization, pk=pk)

    if payroll_run.status != 'processed':
        messages.warning(request, 'Payroll must be processed before approval.')
        return redirect('payroll_run_detail', pk=payroll_run.pk)

    payroll_run.status = 'approved'
    payroll_run.approved_by = request.user
    payroll_run.approved_at = timezone.now()
    payroll_run.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
    write_audit_log(
        request,
        organization=organization,
        area='payroll',
        action='payroll_run_approved',
        target=payroll_run,
        summary=f'Approved payroll run {payroll_run.title}.',
        metadata={'payroll_month': payroll_run.payroll_month.isoformat()},
    )
    messages.success(request, f'{payroll_run.title} has been approved.')
    return redirect('payroll_run_detail', pk=payroll_run.pk)


@login_required
@require_POST
@payroll_required
def payroll_run_mark_paid(request, pk):
    organization = get_active_organization(request)
    payroll_run = get_object_or_404(PayrollRun, organization=organization, pk=pk)

    if payroll_run.status != 'approved':
        messages.warning(request, 'Payroll must be approved before it can be marked as paid.')
        return redirect('payroll_run_detail', pk=payroll_run.pk)

    payroll_run.status = 'paid'
    payroll_run.save(update_fields=['status', 'updated_at'])
    write_audit_log(
        request,
        organization=organization,
        area='payroll',
        action='payroll_run_marked_paid',
        target=payroll_run,
        summary=f'Marked payroll run {payroll_run.title} as paid.',
        metadata={'payroll_month': payroll_run.payroll_month.isoformat()},
    )
    messages.success(request, f'{payroll_run.title} has been marked as paid.')
    return redirect('payroll_run_detail', pk=payroll_run.pk)


@login_required
def payslip_detail(request, pk):
    payslip = get_object_or_404(Payslip.objects.select_related('payroll_run', 'employee'), pk=pk)
    employee = getattr(request.user, 'employee_profile', None)
    active_organization = get_active_organization(request)

    has_payroll_access = (
        active_organization
        and payslip.payroll_run.organization_id == active_organization.pk
        and user_has_payroll_access(request.user, active_organization)
    )
    owns_payslip = employee and payslip.employee_id == employee.pk
    if not has_payroll_access and not owns_payslip:
        raise PermissionDenied('You can only view your own payslips.')

    context = {
        'payslip': payslip,
        'employee': payslip.employee,
        'organization': payslip.payroll_run.organization,
        'page_title': 'Payslip',
    }
    return render(request, 'attendance/payslip_detail.html', context)


# ==================== ADMIN REPORTS ====================

@login_required
@hr_required
def admin_reports(request):
    organization = get_active_organization(request)
    reports = AdminReport.objects.filter(
        organization=organization,
    ).select_related('related_employee', 'related_department', 'created_by', 'reviewed_by')

    search_query = request.GET.get('q', '').strip()
    report_type = request.GET.get('report_type', '').strip()
    tone = request.GET.get('tone', '').strip()
    status = request.GET.get('status', '').strip()

    if search_query:
        reports = reports.filter(
            Q(title__icontains=search_query)
            | Q(body__icontains=search_query)
            | Q(action_taken__icontains=search_query)
            | Q(related_employee__first_name__icontains=search_query)
            | Q(related_employee__last_name__icontains=search_query)
            | Q(related_employee__employee_id__icontains=search_query)
            | Q(related_department__name__icontains=search_query)
        )
    if report_type:
        reports = reports.filter(report_type=report_type)
    if tone:
        reports = reports.filter(tone=tone)
    if status:
        reports = reports.filter(status=status)
    reports = reports.order_by('-event_date', '-created_at')
    reports_page, reports_pagination_query = paginate_queryset(
        request,
        reports,
        per_page=20,
        page_param='reports_page',
    )

    base_reports = AdminReport.objects.filter(organization=organization)
    context = {
        'organization': organization,
        'admin_reports': reports_page,
        'admin_reports_page_obj': reports_page,
        'admin_reports_pagination_query': reports_pagination_query,
        'search_query': search_query,
        'selected_report_type': report_type,
        'selected_tone': tone,
        'selected_status': status,
        'report_type_choices': AdminReport.REPORT_TYPE_CHOICES,
        'tone_choices': AdminReport.TONE_CHOICES,
        'status_choices': AdminReport.STATUS_CHOICES,
        'total_reports': reports_page.paginator.count,
        'open_count': base_reports.filter(status='open').count(),
        'reviewed_count': base_reports.filter(status='reviewed').count(),
        'closed_count': base_reports.filter(status='closed').count(),
        'urgent_count': base_reports.filter(tone='urgent').count(),
        'page_title': 'Admin Reports',
    }
    return render(request, 'attendance/admin_reports.html', context)


@login_required
@hr_required
def admin_report_create(request):
    organization = get_active_organization(request)
    if request.method == 'POST':
        form = AdminReportForm(request.POST, organization=organization)
        if form.is_valid():
            report = form.save(commit=False)
            report.created_by = request.user
            if report.status in ['reviewed', 'closed']:
                report.reviewed_by = request.user
                report.reviewed_at = timezone.now()
            report.save()
            write_audit_log(
                request,
                organization=organization,
                area='admin_report',
                action='admin_report_created',
                target=report,
                summary=f'Created admin report: {report.title}.',
                metadata={'report_type': report.report_type, 'tone': report.tone, 'status': report.status},
            )
            messages.success(request, 'Admin report has been saved.')
            return redirect('admin_report_detail', pk=report.pk)
    else:
        form = AdminReportForm(organization=organization, initial={'event_date': timezone.localdate(), 'status': 'open'})

    context = {
        'form': form,
        'organization': organization,
        'page_title': 'Write Admin Report',
        'action': 'Create',
    }
    return render(request, 'attendance/admin_report_form.html', context)


@login_required
@hr_required
def admin_report_detail(request, pk):
    organization = get_active_organization(request)
    report = get_object_or_404(
        AdminReport.objects.select_related('related_employee', 'related_department', 'created_by', 'reviewed_by'),
        organization=organization,
        pk=pk,
    )
    context = {
        'organization': organization,
        'report': report,
        'page_title': report.title,
    }
    return render(request, 'attendance/admin_report_detail.html', context)


@login_required
@hr_required
def admin_report_edit(request, pk):
    organization = get_active_organization(request)
    report = get_object_or_404(AdminReport, organization=organization, pk=pk)

    if request.method == 'POST':
        form = AdminReportForm(request.POST, organization=organization, instance=report)
        if form.is_valid():
            report = form.save(commit=False)
            if report.status in ['reviewed', 'closed'] and not report.reviewed_at:
                report.reviewed_by = request.user
                report.reviewed_at = timezone.now()
            report.save()
            write_audit_log(
                request,
                organization=organization,
                area='admin_report',
                action='admin_report_updated',
                target=report,
                summary=f'Updated admin report: {report.title}.',
                metadata={'report_type': report.report_type, 'tone': report.tone, 'status': report.status},
            )
            messages.success(request, 'Admin report has been updated.')
            return redirect('admin_report_detail', pk=report.pk)
    else:
        form = AdminReportForm(organization=organization, instance=report)

    context = {
        'form': form,
        'organization': organization,
        'report': report,
        'page_title': 'Edit Admin Report',
        'action': 'Update',
    }
    return render(request, 'attendance/admin_report_form.html', context)


@login_required
@hr_required
def admin_report_set_status(request, pk, status):
    organization = get_active_organization(request)
    report = get_object_or_404(AdminReport, organization=organization, pk=pk)
    allowed_statuses = {choice[0] for choice in AdminReport.STATUS_CHOICES}
    if request.method == 'POST' and status in allowed_statuses:
        report.status = status
        if status in ['reviewed', 'closed']:
            report.reviewed_by = request.user
            report.reviewed_at = timezone.now()
        report.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])
        write_audit_log(
            request,
            organization=organization,
            area='admin_report',
            action='admin_report_status_changed',
            target=report,
            summary=f'Set admin report {report.title} to {report.get_status_display()}.',
            metadata={'status': report.status},
        )
        messages.success(request, f'Admin report marked {report.get_status_display().lower()}.')
    return redirect('admin_report_detail', pk=report.pk)


@login_required
@hr_required
def admin_report_delete(request, pk):
    organization = get_active_organization(request)
    report = get_object_or_404(AdminReport, organization=organization, pk=pk)

    if request.method == 'POST':
        title = report.title
        write_audit_log(
            request,
            organization=organization,
            area='admin_report',
            action='admin_report_deleted',
            target=report,
            summary=f'Deleted admin report: {title}.',
            metadata={'report_type': report.report_type, 'tone': report.tone, 'status': report.status},
        )
        report.delete()
        messages.success(request, f'Admin report "{title}" has been deleted.')
        return redirect('admin_reports')

    context = {
        'organization': organization,
        'report': report,
        'page_title': 'Delete Admin Report',
    }
    return render(request, 'attendance/admin_report_confirm_delete.html', context)


# ==================== REPORT VIEWS ====================

@login_required
@hr_required
def reports_view(request):
    """Generate and export reports"""
    
    organization = get_active_organization(request)
    today = timezone.localdate()
    date_form = DateFilterForm(request.GET or None, organization=organization)
    records = build_filtered_attendance_queryset(date_form, organization).order_by('-check_in_time')
    exceptions = build_filtered_exception_queryset(date_form, organization).order_by('-start_date')
    cleaned_data = date_form.cleaned_data if date_form.is_valid() else {}
    employee_scope = build_employee_scope(cleaned_data, organization)
    records_total = records.count()
    exceptions_total = exceptions.count()
    records_page, records_pagination_query = paginate_queryset(
        request,
        records,
        per_page=25,
        page_param='records_page',
    )
    exceptions_page, exceptions_pagination_query = paginate_queryset(
        request,
        exceptions,
        per_page=20,
        page_param='exceptions_page',
    )

    total_employees = employee_scope.count()
    present_count = records.values('employee_id').distinct().count()
    checked_in_count = records.filter(check_out_time__isnull=True).count()
    checked_out_count = records.filter(check_out_time__isnull=False).count()
    late_records = sum(1 for record in records if record.is_late)
    total_hours = round(sum((record.hours_worked or 0) for record in records), 2)
    avg_daily_hours = round((total_hours / checked_out_count), 2) if checked_out_count else 0
    exception_employee_count = exceptions.values('employee_id').distinct().count()
    covered_employee_count = build_covered_employee_count(employee_scope, cleaned_data)
    attendance_rate = round((present_count / total_employees) * 100) if total_employees else 0
    absent_count = max(total_employees - covered_employee_count, 0)
    leave_count = exceptions.filter(exception_type='leave').count()
    sick_count = exceptions.filter(exception_type='sick').count()

    department_summary = build_scope_breakdown(employee_scope, 'department', 'department__name')
    category_summary = build_scope_breakdown(employee_scope, 'category', 'category__name')
    trend_data = build_attendance_trend(records)
    person_hours_summary = build_person_hours_summary(records)
    top_people = person_hours_summary[:6]
    has_completed_hours = any(row['total_hours'] > 0 for row in person_hours_summary)

    context = {
        'today': today,
        'organization': organization,
        'date_form': date_form,
        'records': records_page,
        'records_page_obj': records_page,
        'records_pagination_query': records_pagination_query,
        'records_total': records_total,
        'total_employees': total_employees,
        'present_count': present_count,
        'checked_in_count': checked_in_count,
        'checked_out_count': checked_out_count,
        'late_records': late_records,
        'total_hours': total_hours,
        'avg_daily_hours': avg_daily_hours,
        'absent_count': absent_count,
        'exceptions_total': exceptions_total,
        'leave_count': leave_count,
        'sick_count': sick_count,
        'attendance_exceptions': exceptions_page,
        'exceptions_page_obj': exceptions_page,
        'exceptions_pagination_query': exceptions_pagination_query,
        'attendance_rate': attendance_rate,
        'department_summary': department_summary,
        'category_summary': category_summary,
        'trend_data': trend_data,
        'top_people': top_people,
        'has_completed_hours': has_completed_hours,
        'birthdays_this_week': get_upcoming_birthdays(organization=organization),
        'internship_endings': get_upcoming_internship_endings(organization=organization),
        'page_title': 'Analytics',
    }
    
    return render(request, 'attendance/reports.html', context)


@login_required
@hr_required
def export_attendance_csv(request):
    """Export attendance data to CSV"""
    organization = get_active_organization(request)
    date_form = DateFilterForm(request.GET or None, organization=organization)
    export_scope = request.GET.get('scope')
    records = build_filtered_attendance_queryset(
        date_form,
        organization,
        default_to_today=(export_scope != 'reports'),
        default_to_current_month=False,
    ).order_by('-check_in_time')
    
    # Create HTTP response with CSV
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="attendance_export_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Date', 'Employee ID', 'Employee', 'Category', 'Department', 'Employment Status', 'Check In', 'Check Out', 'Hours Worked', 'Attendance Status'])
    
    for record in records:
        writer.writerow([
            record.check_in_time.strftime('%Y-%m-%d'),
            record.employee.employee_id,
            record.employee.full_name,
            record.employee.category.name,
            record.employee.department,
            record.employee.get_employment_status_display(),
            record.check_in_time.strftime('%H:%M'),
            record.check_out_time.strftime('%H:%M') if record.check_out_time else 'Still Working',
            record.hours_worked or '-',
            record.status.title(),
        ])

    exceptions = build_filtered_exception_queryset(
        date_form,
        organization,
        default_to_today=(export_scope != 'reports'),
        default_to_current_month=False,
    ).order_by('-start_date')

    if exceptions.exists():
        writer.writerow([])
        writer.writerow(['Attendance Exceptions'])
        writer.writerow(['Start Date', 'End Date', 'Employee ID', 'Employee', 'Category', 'Department', 'Employment Status', 'Exception Type', 'Notes'])
        for exception in exceptions:
            writer.writerow([
                exception.start_date.strftime('%Y-%m-%d'),
                exception.end_date.strftime('%Y-%m-%d'),
                exception.employee.employee_id,
                exception.employee.full_name,
                exception.employee.category.name,
                exception.employee.department,
                exception.employee.get_employment_status_display(),
                exception.get_exception_type_display(),
                exception.notes or '-',
            ])
    
    return response


# ==================== HELPER FUNCTIONS ====================

def get_attendance_settings(organization=None):
    return AttendanceSettings.get_solo(organization)


def get_manager_leave_request(request, pk):
    organization = get_active_organization(request)
    leave_request = get_object_or_404(
        LeaveRequest.objects.select_related('employee', 'employee__line_manager', 'leave_type'),
        pk=pk,
        organization=organization,
        status='pending',
    )
    manager = getattr(request.user, 'employee_profile', None)
    if not user_has_hr_access(request.user, organization) and (
        not manager or leave_request.employee.line_manager_id != manager.pk
    ):
        raise PermissionDenied('You can only review leave requests for your direct reports.')
    return leave_request


def sync_leave_attendance_exception(leave_request):
    """Approved leave should show up anywhere attendance exceptions are reported."""

    exception_code = {
        'annual_leave': 'leave',
        'unpaid_leave': 'leave',
        'sick_leave': 'sick',
    }.get(leave_request.leave_type.code, leave_request.leave_type.code)

    exception_type, _ = AttendanceExceptionType.objects.get_or_create(
        organization=leave_request.organization,
        code=exception_code,
        defaults={
            'name': leave_request.leave_type.name,
            'description': 'Approved leave from leave management.',
            'color': leave_request.leave_type.color,
            'is_active': True,
        },
    )
    note_parts = [f"{leave_request.leave_type.name} approved via leave management."]
    if leave_request.reason:
        note_parts.append(f"Reason: {leave_request.reason}")
    if leave_request.review_note:
        note_parts.append(f"Review note: {leave_request.review_note}")

    AttendanceException.objects.get_or_create(
        organization=leave_request.organization,
        employee=leave_request.employee,
        exception_type=exception_type.code,
        start_date=leave_request.start_date,
        end_date=leave_request.end_date,
        defaults={'notes': ' '.join(note_parts)},
    )


def remove_synced_leave_attendance_exception(leave_request):
    """Remove the attendance exception created by leave approval when leave is cancelled/deleted."""

    exception_code = {
        'annual_leave': 'leave',
        'unpaid_leave': 'leave',
        'sick_leave': 'sick',
    }.get(leave_request.leave_type.code, leave_request.leave_type.code)

    AttendanceException.objects.filter(
        organization=leave_request.organization,
        employee=leave_request.employee,
        exception_type=exception_code,
        start_date=leave_request.start_date,
        end_date=leave_request.end_date,
        notes__icontains='approved via leave management',
    ).delete()


def build_leave_balances(employee, year=None):
    year = year or timezone.now().year
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    leave_types = LeaveType.objects.filter(
        organization=employee.organization,
        is_active=True,
    ).order_by('name')

    rows = []
    for leave_type in leave_types:
        approved_requests = LeaveRequest.objects.filter(
            organization=employee.organization,
            employee=employee,
            leave_type=leave_type,
            status='approved',
            start_date__lte=year_end,
            end_date__gte=year_start,
        )
        pending_requests = LeaveRequest.objects.filter(
            organization=employee.organization,
            employee=employee,
            leave_type=leave_type,
            status='pending',
            start_date__lte=year_end,
            end_date__gte=year_start,
        )
        used_days = sum(request.day_count for request in approved_requests)
        pending_days = sum(request.day_count for request in pending_requests)
        entitlement = leave_type.annual_entitlement_days
        rows.append({
            'leave_type': leave_type,
            'entitlement': entitlement,
            'used': used_days,
            'pending': pending_days,
            'remaining': max(entitlement - used_days - pending_days, 0),
        })
    return rows


def build_employee_leave_overview(employee, year=None):
    today = timezone.localdate()
    balances = build_leave_balances(employee, year)
    approved_requests = LeaveRequest.objects.filter(
        organization=employee.organization,
        employee=employee,
        status='approved',
    ).select_related('leave_type').order_by('start_date')
    current_leave = approved_requests.filter(
        start_date__lte=today,
        end_date__gte=today,
    ).first()
    next_leave = approved_requests.filter(
        start_date__gt=today,
    ).first()
    pending_count = LeaveRequest.objects.filter(
        organization=employee.organization,
        employee=employee,
        status='pending',
    ).count()

    return {
        'employee': employee,
        'balances': balances,
        'total_entitlement': sum(balance['entitlement'] for balance in balances),
        'total_used': sum(balance['used'] for balance in balances),
        'total_pending': sum(balance['pending'] for balance in balances),
        'total_remaining': sum(balance['remaining'] for balance in balances),
        'current_leave': current_leave,
        'next_leave': next_leave,
        'pending_count': pending_count,
    }


def build_organization_leave_balances(organization, year=None):
    employees = Employee.objects.filter(
        organization=organization,
        is_active=True,
    ).select_related('department', 'category').order_by('first_name', 'last_name')
    rows = []
    for employee in employees:
        rows.append(build_employee_leave_overview(employee, year))
    return rows


def build_employee_scope(cleaned_data=None, organization=None):
    cleaned_data = cleaned_data or {}
    employees = Employee.objects.select_related('department', 'category').all()
    if organization:
        employees = employees.filter(organization=organization)

    if cleaned_data.get('employee'):
        employees = employees.filter(pk=cleaned_data['employee'].pk)
    if cleaned_data.get('category'):
        employees = employees.filter(category=cleaned_data['category'])
    if cleaned_data.get('department'):
        employees = employees.filter(department=cleaned_data['department'])
    if cleaned_data.get('employment_status'):
        employees = employees.filter(employment_status=cleaned_data['employment_status'])
    if cleaned_data.get('search'):
        search = cleaned_data['search'].strip()
        employees = employees.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(employee_id__icontains=search)
        )
    return employees



def local_date_range_filter(field_name, start_date, end_date=None):
    end_date = end_date or start_date
    current_tz = timezone.get_current_timezone()
    start_at = timezone.make_aware(datetime.combine(start_date, time.min), current_tz)
    end_at = timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min), current_tz)
    return {
        f'{field_name}__gte': start_at,
        f'{field_name}__lt': end_at,
    }


def local_date_range_q(field_name, start_date, end_date=None):
    return Q(**local_date_range_filter(field_name, start_date, end_date))

def build_filtered_attendance_queryset(date_form, organization=None, default_to_today=False, default_to_current_month=False):
    cleaned_data = date_form.cleaned_data if date_form.is_valid() else {}
    records = AttendanceRecord.objects.select_related('employee__department', 'employee__category').all()
    if organization:
        records = records.filter(organization=organization)
    employees = build_employee_scope(cleaned_data, organization)
    records = records.filter(employee__in=employees)

    if cleaned_data.get('date'):
        records = records.filter(**local_date_range_filter('check_in_time', cleaned_data['date']))
    elif cleaned_data.get('start_date') and cleaned_data.get('end_date'):
        records = records.filter(**local_date_range_filter('check_in_time', cleaned_data['start_date'], cleaned_data['end_date']))
    elif default_to_current_month:
        today = timezone.localdate()
        records = records.filter(**local_date_range_filter('check_in_time', today.replace(day=1), today))
    elif default_to_today:
        records = records.filter(**local_date_range_filter('check_in_time', timezone.localdate()))

    return records


def build_filtered_exception_queryset(date_form, organization=None, default_to_today=False, default_to_current_month=False):
    cleaned_data = date_form.cleaned_data if date_form.is_valid() else {}
    exceptions = AttendanceException.objects.select_related('employee__department', 'employee__category').all()
    if organization:
        exceptions = exceptions.filter(organization=organization)
    employees = build_employee_scope(cleaned_data, organization)
    exceptions = exceptions.filter(employee__in=employees)

    if cleaned_data.get('date'):
        exceptions = exceptions.filter(start_date__lte=cleaned_data['date'], end_date__gte=cleaned_data['date'])
    elif cleaned_data.get('start_date') and cleaned_data.get('end_date'):
        exceptions = exceptions.filter(
            start_date__lte=cleaned_data['end_date'],
            end_date__gte=cleaned_data['start_date'],
        )
    elif default_to_current_month:
        today = timezone.localdate()
        month_start = today.replace(day=1)
        exceptions = exceptions.filter(end_date__gte=month_start, start_date__lte=today)
    elif default_to_today:
        today = timezone.localdate()
        exceptions = exceptions.filter(start_date__lte=today, end_date__gte=today)

    return exceptions


def build_covered_employee_count(employee_scope, cleaned_data=None):
    cleaned_data = cleaned_data or {}
    attendance_filters = Q()
    exception_filters = Q()

    if cleaned_data.get('date'):
        attendance_filters &= local_date_range_q('attendance_records__check_in_time', cleaned_data['date'])
        exception_filters &= Q(
            attendance_exceptions__start_date__lte=cleaned_data['date'],
            attendance_exceptions__end_date__gte=cleaned_data['date'],
        )
    elif cleaned_data.get('start_date') and cleaned_data.get('end_date'):
        attendance_filters &= local_date_range_q(
            'attendance_records__check_in_time',
            cleaned_data['start_date'],
            cleaned_data['end_date'],
        )
        exception_filters &= Q(
            attendance_exceptions__start_date__lte=cleaned_data['end_date'],
            attendance_exceptions__end_date__gte=cleaned_data['start_date'],
        )
    else:
        return employee_scope.filter(
            Q(attendance_records__isnull=False) | Q(attendance_exceptions__isnull=False)
        ).distinct().count()

    return employee_scope.filter(attendance_filters | exception_filters).distinct().count()


def build_scope_breakdown(employee_scope, relation_name, order_field):
    if relation_name == 'department':
        queryset = employee_scope.exclude(department__isnull=True)
        rows = queryset.values('department__name').annotate(count=Count('id')).order_by(order_field)
        data = [{'label': row['department__name'], 'count': row['count']} for row in rows]
    else:
        rows = employee_scope.values('category__name').annotate(count=Count('id')).order_by(order_field)
        data = [{'label': row['category__name'], 'count': row['count']} for row in rows]

    max_count = max((row['count'] for row in data), default=1)
    for row in data:
        row['percent'] = round((row['count'] / max_count) * 100) if max_count else 0
    return data


def build_attendance_trend(records):
    daily_totals = {}
    for record in records:
        day = timezone.localtime(record.check_in_time).date()
        key = day.isoformat()
        if key not in daily_totals:
            daily_totals[key] = {'date': day, 'label': day.strftime('%b %d'), 'present': set(), 'hours': 0}
        daily_totals[key]['present'].add(record.employee_id)
        daily_totals[key]['hours'] += record.hours_worked or 0

    data = []
    max_present = 1
    for value in daily_totals.values():
        present = len(value['present'])
        max_present = max(max_present, present)
        data.append({
            'date': value['date'],
            'label': value['label'],
            'present': present,
            'hours': round(value['hours'], 1),
        })

    data.sort(key=lambda item: item['date'])
    for item in data:
        item['percent'] = round((item['present'] / max_present) * 100) if max_present else 0
    return data[-10:]


def count_distinct_late_employees(records):
    employee_ids = {record.employee_id for record in records if record.is_late}
    return len(employee_ids)


def build_person_hours_summary(records):
    summary = {}
    for record in records:
        employee = record.employee
        if employee.pk not in summary:
            summary[employee.pk] = {
                'name': employee.display_name,
                'employee_id': employee.employee_id,
                'department': employee.department,
                'attendance_days': set(),
                'completed_sessions': 0,
                'total_hours': 0,
            }
        summary[employee.pk]['attendance_days'].add(timezone.localtime(record.check_in_time).date())
        if record.hours_worked is not None:
            summary[employee.pk]['completed_sessions'] += 1
            summary[employee.pk]['total_hours'] += record.hours_worked

    rows = list(summary.values())
    for row in rows:
        row['days_present'] = len(row.pop('attendance_days'))
        row['total_hours'] = round(row['total_hours'], 1)
        row['avg_hours'] = round((row['total_hours'] / row['completed_sessions']), 2) if row['completed_sessions'] else 0
    rows.sort(key=lambda item: (item['total_hours'], item['days_present']), reverse=True)
    return rows


def get_upcoming_birthdays(days=None, organization=None):
    """Get employees with birthdays in the configured reminder window."""

    settings_obj = get_attendance_settings(organization)
    reminder_days = days if days is not None else settings_obj.birthday_reminder_days
    today = date.today()
    week_later = today + timedelta(days=reminder_days)

    birthdays = []

    employees = Employee.objects.filter(is_active=True, date_of_birth__isnull=False)
    if organization:
        employees = employees.filter(organization=organization)

    for employee in employees:
        bday = employee.date_of_birth
        birthday_this_year = date(today.year, bday.month, bday.day)
        if birthday_this_year < today:
            birthday_this_year = date(today.year + 1, bday.month, bday.day)

        if today <= birthday_this_year <= week_later:
            birthdays.append({
                'employee': employee,
                'date': birthday_this_year,
                'days_until': (birthday_this_year - today).days
            })

    birthdays.sort(key=lambda x: x['days_until'])
    return birthdays


def get_upcoming_internship_endings(days=None, organization=None):
    """Get active interns whose end date is approaching."""

    settings_obj = get_attendance_settings(organization)
    reminder_days = days if days is not None else settings_obj.internship_reminder_days
    today = date.today()
    reminder_limit = today + timedelta(days=reminder_days)

    upcoming = []
    interns = Employee.objects.filter(
        is_active=True,
        category__code='INTERN',
        end_date__isnull=False,
        end_date__gte=today,
        end_date__lte=reminder_limit,
    ).select_related('department', 'category', 'supervisor')
    if organization:
        interns = interns.filter(organization=organization)

    for employee in interns:
        upcoming.append({
            'employee': employee,
            'date': employee.end_date,
            'days_until': (employee.end_date - today).days,
        })

    upcoming.sort(key=lambda x: x['days_until'])
    return upcoming


# ==================== COMPANY BRANDING ====================

@login_required
def organization_branding(request):
    from .branding import accent_vars, dominant_color
    from .forms import OrganizationBrandingForm
    organization = get_active_organization(request)
    membership = OrganizationMembership.objects.filter(
        user=request.user, organization=organization, is_active=True
    ).first()
    role = membership.role if membership else ''
    if not (request.user.is_superuser or role in ('owner', 'hr_admin')):
        raise PermissionDenied
    suggested = None
    if request.method == 'POST':
        form = OrganizationBrandingForm(request.POST, request.FILES, instance=organization)
        if form.is_valid():
            org = form.save(commit=False)
            if form.cleaned_data.get('remove_logo') and org.logo:
                org.logo.delete(save=False)
                org.logo = None
            org.save()
            write_audit_log(request, organization=organization, area='organization',
                            action='branding.update', summary=f'Updated branding for {org.name}', target=org)
            messages.success(request, 'Company branding updated.')
            return redirect('organization_branding')
    else:
        form = OrganizationBrandingForm(instance=organization)
    # Dominant-color suggestion from current logo
    try:
        if organization.logo:
            with organization.logo.open('rb') as fh:
                suggested = dominant_color(fh)
    except Exception:
        suggested = None
    context = {
        'organization': organization,
        'form': form,
        'suggested_color': suggested,
        'preview_vars': accent_vars(form.initial.get('brand_color') or organization.brand_color),
        'page_title': 'Company Branding',
    }
    return render(request, 'attendance/organization_branding.html', context)


def welcome_view(request):
    return render(request, 'attendance/welcome.html')


def contact_request_view(request):
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()[:120]
        email = (request.POST.get('email') or '').strip()[:120]
        message = (request.POST.get('message') or '').strip()[:2000]
        if name and email and message:
            send_mail(
                subject=f'DIGI HR access request from {name}',
                message=f'From: {name} <{email}>\n\n{message}',
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@digi02hr.local'),
                recipient_list=[getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@digi02hr.local')],
            )
            messages.success(request, 'Thanks — we will be in touch shortly.')
            return redirect('welcome')
        messages.error(request, 'Please complete name, email and message.')
    return redirect('welcome')
