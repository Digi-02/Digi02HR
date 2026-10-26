# core/urls.py

from django.contrib import admin
from django.urls import path, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as static_serve
from attendance import views
from attendance import wizard as wizard_views
from attendance.integration_api import technical_command_attendance_today_api, technical_command_people_api

from django.contrib.auth import views as auth_views
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.core.cache import cache
from django.http import HttpResponseRedirect
import time

User = get_user_model()

_ratelimit_store = {}


def _reset_ratelimited(request):
    if request.method != 'POST':
        return False
    ip = request.META.get('REMOTE_ADDR', 'anon')
    now = time.time()
    hits = [t for t in _ratelimit_store.get(ip, []) if now - t < 600]
    _ratelimit_store[ip] = hits
    if len(hits) >= 5:
        return True
    hits.append(now)
    _ratelimit_store[ip] = hits
    return False


class RateLimitedPasswordResetView(auth_views.PasswordResetView):
    html_email_template_name = 'registration/email/password_reset.html'

    def dispatch(self, request, *args, **kwargs):
        if _reset_ratelimited(request):
            from django.contrib import messages as dj_messages
            dj_messages.error(request, 'Too many reset attempts. Try again later.')
            return HttpResponseRedirect(request.path)
        return super().dispatch(request, *args, **kwargs)

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        # Add organization name from the user's first active membership.
        org_name = ''
        try:
            user = User.objects.filter(email=to_email).first()
            if user:
                membership = user.organization_memberships.filter(
                    is_active=True).select_related('organization').first()
                if membership:
                    org_name = membership.organization.name
        except Exception:
            pass
        context['organization_name'] = org_name or 'DIGI HR'

        html_content = render_to_string(self.html_email_template_name, context)
        text_content = render_to_string(email_template_name, context)
        subject = render_to_string(subject_template_name, context).strip()
        email = EmailMessage(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[to_email],
        )
        email.attach_alternative(html_content, 'text/html')
        email.send(fail_silently=False)

from attendance import platform as platform_views

urlpatterns = [
    path('platform/', platform_views.overview, name='platform_overview'),
    path('platform/companies/', platform_views.company_list, name='platform_companies'),
    path('platform/companies/create/', platform_views.company_create, name='platform_company_create'),
    path('platform/companies/<int:pk>/', platform_views.company_detail, name='platform_company_detail'),
    path('platform/companies/<int:pk>/action/', platform_views.company_action, name='platform_company_action'),
    path('platform/requests/', platform_views.access_requests, name='platform_access_requests'),
    path('platform/requests/<int:pk>/action/', platform_views.access_request_action, name='platform_access_request_action'),
    path('platform/audit/', platform_views.audit_log, name='platform_audit'),
    path('platform/settings/', platform_views.platform_settings, name='platform_settings'),
    path('welcome/', views.welcome_view, name='welcome'),
    path('welcome/contact/', views.contact_request_view, name='welcome_contact'),
    path('password-reset/', RateLimitedPasswordResetView.as_view(
        template_name='registration/auth/password_reset_form.html',
        email_template_name='registration/email/password_reset.txt',
        subject_template_name='registration/password_reset_subject.txt',
        html_email_template_name='registration/email/password_reset.html',
        success_url='/password-reset/done/'), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/auth/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/auth/password_reset_confirm.html',
        success_url='/reset/complete/'), name='password_reset_confirm'),
    path('set-password/<uidb64>/<token>/', platform_views.set_owner_password, name='set_owner_password'),
    path('reset/complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/auth/password_reset_complete.html'), name='password_reset_complete'),
    path('password-change/', auth_views.PasswordChangeView.as_view(
        template_name='registration/password_change_form.html',
        success_url='/password-change/done/'), name='password_change'),
    path('password-change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='registration/password_change_done.html'), name='password_change_done'),
    path('api/v1/technical-command/people/', technical_command_people_api, name='technical_command_people_api'),
    path('api/v1/technical-command/attendance/today/', technical_command_attendance_today_api, name='technical_command_attendance_today_api'),
    # Admin (only for superusers)
    path('admin/', admin.site.urls),
    
    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Public kiosk
    path('', views.kiosk_view, name='kiosk'),
    path('o/<slug:org_slug>/kiosk/', views.kiosk_view, name='organization_kiosk'),
    
    # Setup wizard (owner / hr_admin only, first-time company setup)
    path('setup/wizard/', wizard_views.setup_wizard, name='setup_wizard'),
    path('setup/complete/', wizard_views.setup_complete, name='setup_complete'),

    # Dashboard
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('dashboard/category/<str:code>/', views.category_dashboard, name='category_dashboard'),
    
    # Organizations
    path('organizations/', views.organization_list, name='organization_list'),
    path('organizations/add/', views.organization_create, name='organization_create'),
    path('organizations/<int:pk>/edit/', views.organization_edit, name='organization_edit'),
    path('organizations/<int:pk>/switch/', views.organization_switch, name='organization_switch'),
    path('settings/', views.organization_settings, name='organization_settings'),
    path('settings/branding/', views.organization_branding, name='organization_branding'),
    path('settings/departments/', views.organization_departments, name='organization_departments'),
    path('settings/categories/', views.organization_categories, name='organization_categories'),
    path('settings/attendance/', views.organization_attendance_settings, name='organization_attendance_settings'),
    path('settings/birthday-message/', views.organization_birthday_message_template, name='organization_birthday_message_template'),
    path('settings/leave-types/', views.organization_leave_types, name='organization_leave_types'),
    path('settings/leave-types/<int:pk>/edit/', views.organization_leave_type_edit, name='organization_leave_type_edit'),
    path('settings/leave-types/<int:pk>/delete/', views.organization_leave_type_delete, name='organization_leave_type_delete'),
    
    # Employee Management
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/add/', views.employee_create, name='employee_create'),
    path('employees/<int:pk>/', views.employee_detail, name='employee_detail'),
    path('employees/<int:pk>/account/', views.employee_account_create, name='employee_account_create'),
    path('employees/<int:pk>/edit/', views.employee_edit, name='employee_edit'),
    path('employees/<int:pk>/delete/', views.employee_delete, name='employee_delete'),
    path('documents/', views.employee_documents, name='employee_documents'),
    path('documents/upload/', views.employee_document_upload, name='employee_document_upload'),
    path('employees/<int:employee_pk>/documents/upload/', views.employee_document_upload, name='employee_document_upload_for_employee'),
    path('documents/<int:pk>/edit/', views.employee_document_edit, name='employee_document_edit'),
    path('documents/<int:pk>/delete/', views.employee_document_delete, name='employee_document_delete'),
    path('mail/', views.mail_dashboard, name='mail_dashboard'),
    path('mail/compose/', views.mail_compose, name='mail_compose'),
    path('mail/inbox/<str:uid>/', views.mail_inbox_message, name='mail_inbox_message'),
    path('onboarding/', views.onboarding_tasks, name='onboarding_tasks'),
    path('onboarding/invite-applicant/', views.applicant_invite, name='applicant_invite'),
    path('onboarding/invite-employee/', views.existing_employee_onboarding_invite, name='existing_employee_onboarding_invite'),
    path('onboarding/applicants/<int:pk>/approve/', views.applicant_approve, name='applicant_approve'),
    path('onboarding/applicants/<int:pk>/reject/', views.applicant_reject, name='applicant_reject'),
    path('onboarding/stages/add/', views.onboarding_stage_create, name='onboarding_stage_create'),
    path('onboarding/stages/<int:pk>/edit/', views.onboarding_stage_edit, name='onboarding_stage_edit'),
    path('onboarding/stages/<int:pk>/delete/', views.onboarding_stage_delete, name='onboarding_stage_delete'),
    path('onboarding/participants/<int:pk>/move/', views.onboarding_participant_move, name='onboarding_participant_move'),
    path('onboarding/add/', views.onboarding_task_create, name='onboarding_task_create'),
    path('employees/<int:employee_pk>/onboarding/add/', views.onboarding_task_create, name='onboarding_task_create_for_employee'),
    path('onboarding/<int:pk>/edit/', views.onboarding_task_edit, name='onboarding_task_edit'),
    path('onboarding/<int:pk>/complete/', views.onboarding_task_complete, name='onboarding_task_complete'),
    path('onboarding/<int:pk>/delete/', views.onboarding_task_delete, name='onboarding_task_delete'),
    path('onboarding/invite/<str:token>/', views.public_onboarding_invitation, name='public_onboarding_invitation'),

    # Employee Self-Service
    path('me/', views.employee_self_service_dashboard, name='employee_self_service_dashboard'),
    path('me/profile/', views.employee_my_profile, name='employee_my_profile'),
    path('me/documents/', views.employee_my_documents, name='employee_my_documents'),
    path('me/documents/upload/', views.employee_my_document_upload, name='employee_my_document_upload'),
    path('me/documents/<int:pk>/edit/', views.employee_my_document_edit, name='employee_my_document_edit'),
    path('me/leave/request/', views.employee_leave_request_create, name='employee_leave_request_create'),
    path('manager/', views.manager_dashboard, name='manager_dashboard'),
    path('manager/team/', views.manager_team, name='manager_team'),
    path('manager/leave/', views.manager_leave_requests, name='manager_leave_requests'),
    path('manager/leave/<int:pk>/approve/', views.manager_leave_request_approve, name='manager_leave_request_approve'),
    path('manager/leave/<int:pk>/reject/', views.manager_leave_request_reject, name='manager_leave_request_reject'),
    
    # Attendance Management
    path('attendance/', views.attendance_reports, name='attendance_reports'),
    path('attendance/add/', views.manual_attendance_add, name='manual_attendance_add'),
    path('attendance/exception-types/', views.attendance_exception_types, name='attendance_exception_types'),

    # Leave Management
    path('leave/', views.leave_requests, name='leave_requests'),
    path('leave/employees/<int:employee_pk>/', views.employee_leave_detail, name='employee_leave_detail'),
    path('leave/add/', views.leave_request_create, name='leave_request_create'),
    path('leave/<int:pk>/', views.leave_request_detail, name='leave_request_detail'),
    path('leave/<int:pk>/edit/', views.leave_request_edit, name='leave_request_edit'),
    path('leave/<int:pk>/approve/', views.leave_request_approve, name='leave_request_approve'),
    path('leave/<int:pk>/reject/', views.leave_request_reject, name='leave_request_reject'),
    path('leave/<int:pk>/cancel/', views.leave_request_cancel, name='leave_request_cancel'),
    path('leave/<int:pk>/delete/', views.leave_request_delete, name='leave_request_delete'),

    # Payroll
    path('finance/', views.finance_dashboard, name='finance_dashboard'),
    path('finance/readiness/', views.finance_payroll_readiness, name='finance_payroll_readiness'),
    path('payroll/', views.payroll_runs, name='payroll_runs'),
    path('payroll/add/', views.payroll_run_create, name='payroll_run_create'),
    path('payroll/<int:pk>/', views.payroll_run_detail, name='payroll_run_detail'),
    path('payroll/<int:pk>/generate/', views.payroll_run_generate, name='payroll_run_generate'),
    path('payroll/<int:pk>/approve/', views.payroll_run_approve, name='payroll_run_approve'),
    path('payroll/<int:pk>/mark-paid/', views.payroll_run_mark_paid, name='payroll_run_mark_paid'),
    path('payslips/<int:pk>/', views.payslip_detail, name='payslip_detail'),
    
    # Admin Reports
    path('admin-reports/', views.admin_reports, name='admin_reports'),
    path('admin-reports/add/', views.admin_report_create, name='admin_report_create'),
    path('admin-reports/<int:pk>/', views.admin_report_detail, name='admin_report_detail'),
    path('admin-reports/<int:pk>/edit/', views.admin_report_edit, name='admin_report_edit'),
    path('admin-reports/<int:pk>/delete/', views.admin_report_delete, name='admin_report_delete'),
    path('admin-reports/<int:pk>/status/<str:status>/', views.admin_report_set_status, name='admin_report_set_status'),

    # Analytics
    path('reports/', views.reports_view, name='reports'),
    path('analytics/', views.reports_view, name='analytics'),
    path('reports/export/', views.export_attendance_csv, name='export_attendance_csv'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += [
    re_path(r"^static/(?P<path>.*)$", static_serve, {"document_root": settings.STATIC_ROOT}),
    re_path(r"^media/(?P<path>.*)$", static_serve, {"document_root": settings.MEDIA_ROOT}),
]
