# attendance/platform.py — separate product-owner admin area (NOT a company workspace).
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_POST

from .models import (
    AccessRequest,
    AuditLog,
    Employee,
    Organization,
    OrganizationMembership,
    PlatformAuditLog,
    PlatformSettings,
)
from .organization import setup_default_organization_records

User = get_user_model()


def platform_admin_required(view):
    """Only platform admins (is_superuser) may enter. Everyone else gets 404."""

    @wraps(view)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise Http404
        return view(request, *args, **kwargs)

    return _wrapped


def platform_audit(request, action, organization=None, detail=''):
    PlatformAuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        organization=organization,
        detail=detail[:255],
    )


def _owner_of(organization):
    membership = (
        OrganizationMembership.objects.filter(
            organization=organization, role='owner', is_active=True
        )
        .select_related('user')
        .order_by('created_at')
        .first()
    )
    return membership.user if membership else None


def _company_last_activity(organization):
    log = AuditLog.objects.filter(organization=organization).order_by('-created_at').first()
    return log.created_at if log else organization.created_at


@platform_admin_required
def overview(request):
    companies = Organization.objects.all()
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    context = {
        'total_companies': companies.count(),
        'active_companies': companies.filter(is_suspended=False).count(),
        'suspended_companies': companies.filter(is_suspended=True).count(),
        'total_employees': Employee.objects.count(),
        'new_this_month': companies.filter(created_at__gte=month_start).count(),
        'pending_requests': AccessRequest.objects.filter(status='new').count(),
        'recent_companies': companies.order_by('-created_at')[:8],
        'recent_audit': PlatformAuditLog.objects.select_related(
            'actor', 'organization').order_by('-created_at')[:10],
        'page_title': 'Platform Overview',
    }
    return render(request, 'platform/overview.html', context)


@platform_admin_required
def company_list(request):
    q = (request.GET.get('q') or '').strip()
    companies = Organization.objects.all().order_by('name')
    if q:
        companies = companies.filter(
            Q(name__icontains=q)
            | Q(slug__icontains=q)
            | Q(memberships__user__email__icontains=q)
        ).distinct()
    rows = []
    for org in companies:
        owner = _owner_of(org)
        rows.append({
            'org': org,
            'owner_email': owner.email if owner else '-',
            'employees': Employee.objects.filter(organization=org).count(),
            'last_activity': _company_last_activity(org),
        })
    context = {'rows': rows, 'q': q, 'page_title': 'Companies'}
    return render(request, 'platform/company_list.html', context)


@platform_admin_required
def company_detail(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    owner = _owner_of(org)
    roles = (
        OrganizationMembership.objects.filter(organization=org, is_active=True)
        .values('role')
        .annotate(total=Count('id'))
        .order_by('role')
    )
    context = {
        'org': org,
        'owner': owner,
        'roles': roles,
        'employees': Employee.objects.filter(organization=org).count(),
        'last_activity': _company_last_activity(org),
        'page_title': org.name,
    }
    return render(request, 'platform/company_detail.html', context)


@platform_admin_required
def company_create(request):
    prefill = {}
    source_request = None
    request_id = request.GET.get('request') or request.POST.get('request_id')
    if request_id:
        try:
            source_request = AccessRequest.objects.get(pk=int(request_id))
            prefill = {
                'name': source_request.company_name,
                'owner_name': source_request.contact_name,
                'owner_email': source_request.email,
            }
        except (AccessRequest.DoesNotExist, ValueError):
            source_request = None
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        owner_name = (request.POST.get('owner_name') or '').strip()
        owner_email = (request.POST.get('owner_email') or '').strip().lower()
        errors = []
        if not name:
            errors.append('Company name is required.')
        if not owner_name:
            errors.append('Owner name is required.')
        if not owner_email or '@' not in owner_email:
            errors.append('A valid owner email is required.')
        if Organization.objects.filter(name__iexact=name).exists():
            errors.append('A company with this name already exists.')
        if User.objects.filter(email__iexact=owner_email).exists():
            errors.append('A user with this email already exists.')
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            from django.utils.text import slugify as dj_slugify
            slug = dj_slugify(name)[:80] or f'company-{get_random_string(6)}'
            base_slug, counter, candidate = slug, 2, slug
            while Organization.objects.filter(slug=candidate).exists():
                candidate = f'{base_slug}-{counter}'
                counter += 1
            with transaction.atomic():
                org = Organization.objects.create(name=name, slug=candidate)
                setup_default_organization_records(org)
                parts = owner_name.split()
                user = User.objects.create_user(
                    username=owner_email.split('@')[0][:140] or f'owner-{get_random_string(6)}',
                    email=owner_email,
                    password=get_random_string(24),
                    first_name=parts[0] if parts else '',
                    last_name=' '.join(parts[1:]) if len(parts) > 1 else '',
                )
                OrganizationMembership.objects.create(
                    user=user, organization=org, role='owner', is_active=True)
                if source_request:
                    source_request.status = 'approved'
                    source_request.created_company = org
                    source_request.save(update_fields=['status', 'created_company', 'updated_at'])
            send_owner_invite(request, user, org)
            platform_audit(request, 'company.created', org, f'Created {name}; invite sent to {owner_email}.')
            messages.success(request, f'{name} created. An invite was sent to {owner_email}.')
            return redirect('platform_company_detail', pk=org.pk)
    context = {
        'prefill': prefill,
        'request_id': request.POST.get('request_id') or request.GET.get('request') or '',
        'source_request': source_request,
        'page_title': 'Create company',
    }
    return render(request, 'platform/company_form.html', context)


def send_owner_invite(request, user, org):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = request.build_absolute_uri(
        reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token}))
    send_mail(
        subject=f'Your {org.name} workspace is ready — set your password',
        message=(
            f'Hello,\n\nYour {org.name} workspace on DIGI HR is ready.\n\n'
            f'Set your password here:\n{link}\n\n'
            f'This link expires after use.\n\nPowered by DIGI'
        ),
        from_email=None,
        recipient_list=[user.email],
    )
    platform_audit(None if request is None else request, 'owner.invite_sent', org,
                   f'Invite sent to {user.email}.')


@platform_admin_required
@require_POST
def company_action(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    action = request.POST.get('action')
    if action == 'suspend':
        org.is_suspended = True
        org.suspended_at = timezone.now()
        org.save(update_fields=['is_suspended', 'suspended_at'])
        platform_audit(request, 'company.suspended', org, f'Suspended {org.name}.')
        messages.success(request, f'{org.name} has been suspended.')
    elif action == 'activate':
        org.is_suspended = False
        org.suspended_at = None
        org.save(update_fields=['is_suspended', 'suspended_at'])
        platform_audit(request, 'company.activated', org, f'Reactivated {org.name}.')
        messages.success(request, f'{org.name} is active again.')
    elif action == 'rename':
        new_name = (request.POST.get('name') or '').strip()
        if new_name and not Organization.objects.filter(name__iexact=new_name).exclude(pk=org.pk).exists():
            old = org.name
            org.name = new_name
            org.save(update_fields=['name'])
            platform_audit(request, 'company.renamed', org, f'Renamed {old} to {new_name}.')
            messages.success(request, 'Company name updated.')
        else:
            messages.error(request, 'Enter a unique company name.')
    elif action == 'resend_invite':
        owner = _owner_of(org)
        if owner:
            send_owner_invite(request, owner, org)
            messages.success(request, f'Invite resent to {owner.email}.')
        else:
            messages.error(request, 'This company has no owner to invite.')
    return redirect('platform_company_detail', pk=org.pk)


@platform_admin_required
def access_requests(request):
    status = (request.GET.get('status') or '').strip()
    valid = dict(AccessRequest.STATUS_CHOICES)
    if status not in valid:
        status = ''
    items = AccessRequest.objects.all().order_by('-created_at')
    if status:
        items = items.filter(status=status)
    context = {
        'items': items[:100],
        'status': status,
        'status_choices': AccessRequest.STATUS_CHOICES,
        'page_title': 'Access requests',
    }
    return render(request, 'platform/access_requests.html', context)


@platform_admin_required
@require_POST
def access_request_action(request, pk):
    item = get_object_or_404(AccessRequest, pk=pk)
    action = request.POST.get('action')
    if action == 'reject':
        item.status = 'rejected'
        item.save(update_fields=['status', 'updated_at'])
        platform_audit(request, 'request.rejected', None, f'Rejected request from {item.email}.')
        messages.success(request, 'Request rejected.')
        return redirect('platform_access_requests')
    if action == 'approve':
        platform_audit(request, 'request.approved', None, f'Approved request from {item.email}; opening create flow.')
        return redirect(f"{reverse('platform_company_create')}?request={item.pk}")
    return redirect('platform_access_requests')


@platform_admin_required
def audit_log(request):
    logs = PlatformAuditLog.objects.select_related('actor', 'organization').order_by('-created_at')[:200]
    context = {'logs': logs, 'page_title': 'Platform audit log'}
    return render(request, 'platform/audit_log.html', context)


@platform_admin_required
def platform_settings(request):
    settings_obj = PlatformSettings.get_solo()
    if request.method == 'POST':
        settings_obj.support_email = (request.POST.get('support_email') or '').strip() or settings_obj.support_email
        settings_obj.announcement = (request.POST.get('announcement') or '').strip()
        settings_obj.announcement_active = bool(request.POST.get('announcement_active')) and bool(settings_obj.announcement)
        settings_obj.save()
        platform_audit(request, 'platform.settings_updated', None, 'Updated platform settings.')
        messages.success(request, 'Platform settings saved.')
        return redirect('platform_settings')
    context = {'settings_obj': settings_obj, 'page_title': 'Platform settings'}
    return render(request, 'platform/settings.html', context)
