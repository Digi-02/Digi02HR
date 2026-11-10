"""Views for each member's own work mailbox. There is no company-wide mailbox query."""
from email.utils import getaddresses
from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from .forms import WorkMailboxConfigForm
from .mailbox_security import encrypt_password, revoke_mailbox, decrypt_password
from .mailbox_service import (
    MailConfig, fetch_attachment, folder_kind, friendly_mail_error, get_message, list_folder_metadata, list_folders,
    list_messages, message_action, save_draft, send_message,
    test_connections,
)
from .models import WorkMailbox
from .organization import get_active_organization, user_has_work_mail_access


def _mailbox_context(request):
    org = get_active_organization(request)
    if org is None or not user_has_work_mail_access(request.user, org):
        raise PermissionDenied
    mailbox = WorkMailbox.objects.filter(organization=org, user=request.user).first()
    return org, mailbox


def _usable(mailbox):
    return bool(mailbox and mailbox.is_connected and mailbox.password_ciphertext and mailbox.encryption_key_id)


def _config_data(cleaned, mailbox):
    data = dict(cleaned)
    if not data.get('password') and _usable(mailbox):
        data['password'] = decrypt_password(mailbox.password_ciphertext, mailbox.encryption_key_id)
    return MailConfig.from_mapping(data)


@login_required
def my_work_email(request):
    org, mailbox = _mailbox_context(request)
    if request.method == 'POST' and request.POST.get('action') == 'disconnect':
        if mailbox:
            revoke_mailbox(mailbox)
        messages.success(request, 'Your work email is disconnected. Its saved password has been erased.')
        return redirect('my_work_email')

    if request.method == 'POST':
        form = WorkMailboxConfigForm(request.POST, instance=mailbox)
        action = request.POST.get('action', 'save')
        if form.is_valid():
            try:
                config = _config_data(form.cleaned_data, mailbox)
                test_connections(config)
                if action == 'test':
                    messages.success(request, 'Incoming and outgoing secure connections both succeeded. Nothing was saved.')
                elif action == 'save':
                    key_id, ciphertext = encrypt_password(config.password)
                    target = form.save(commit=False)
                    target.organization = org
                    target.user = request.user
                    target.username = config.username
                    target.password_ciphertext = ciphertext
                    target.encryption_key_id = key_id
                    target.is_connected = True
                    target.last_tested_at = timezone.now()
                    target.save()
                    messages.success(request, 'Your work email is connected.')
                    return redirect('mail_dashboard')
                else:
                    messages.error(request, 'Unsupported mailbox action.')
            except Exception as exc:
                # Do not display provider exceptions: IMAP/SMTP providers can echo credentials.
                messages.error(request, friendly_mail_error(exc, 'connect'))
        else:
            messages.error(request, 'Review the highlighted mailbox settings.')
    else:
        initial = {}
        employee = getattr(request.user, 'employee_profile', None)
        if employee and employee.organization_id == org.pk:
            initial['email_address'] = employee.email
            initial['username'] = employee.email
        elif request.user.email:
            initial['email_address'] = request.user.email
            initial['username'] = request.user.email
        if mailbox:
            initial['email_address'] = mailbox.email_address
            initial['username'] = mailbox.username
        form = WorkMailboxConfigForm(instance=mailbox, initial=initial)
    return render(request, 'attendance/my_work_email.html', {
        'organization': org, 'mailbox': mailbox, 'is_connected': _usable(mailbox),
        'form': form, 'page_title': 'My work email',
    })


@login_required
def mail_dashboard(request):
    org, mailbox = _mailbox_context(request)
    if not _usable(mailbox):
        return render(request, 'attendance/mail_dashboard.html', {
            'organization': org, 'mailbox': mailbox, 'connected': False,
            'page_title': 'Mail',
        })
    folder = request.GET.get('folder', 'INBOX')
    query = request.GET.get('q', '').strip()[:160]
    try:
        page = min(max(int(request.GET.get('page', '1')), 1), 100000)
    except (TypeError, ValueError):
        page = 1
    folder_metadata = []
    try:
        folder_metadata = list_folder_metadata(mailbox)
        folders = [item['name'] for item in folder_metadata]
        if folder != '__STARRED__' and folder not in folders:
            folder = next((name for name in folders if folder_kind(name) == 'inbox'), 'INBOX')
        rows, page_info = list_messages(mailbox, folder=folder, query=query, page=page, return_page_info=True)
        mailbox.last_synced_at = timezone.now()
        mailbox.save(update_fields=['last_synced_at', 'updated_at'])
        error = ''
    except Exception as exc:
        folders, rows, page_info, error = [], [], {}, friendly_mail_error(exc, 'sync')
    folder_rows = folder_metadata or [{'name': name, 'kind': folder_kind(name)} for name in folders]
    return render(request, 'attendance/mail_dashboard.html', {
        'organization': org, 'mailbox': mailbox, 'connected': True, 'folders': folder_rows,
        'selected_folder': folder, 'messages_list': rows, 'query': query,
        'mail_error': error, 'page_title': 'Mail',
        'page_info': page_info,
    })


@login_required
def mail_inbox_message(request, uid):
    _org, mailbox = _mailbox_context(request)
    if not _usable(mailbox):
        return redirect('my_work_email')
    folder = request.GET.get('folder', 'INBOX')[:255]
    try:
        if folder not in list_folders(mailbox): raise Http404
        message = get_message(mailbox, folder, uid)
    except Http404:
        raise
    except Exception as exc:
        return render(request, 'attendance/mail_inbox_message.html', {
            'message': None, 'folder': folder, 'mail_error': friendly_mail_error(exc, 'sync'), 'page_title': 'Message',
        })
    return render(request, 'attendance/mail_inbox_message.html', {
        'message': message, 'folder': folder, 'page_title': message['subject'],
    })


@login_required
@require_POST
def mail_action(request, uid):
    _org, mailbox = _mailbox_context(request)
    if not _usable(mailbox): return redirect('my_work_email')
    folder = request.POST.get('folder', 'INBOX')[:255]
    action = request.POST.get('action', '')
    try:
        if folder not in list_folders(mailbox): raise ValueError('Folder is unavailable.')
        message_action(mailbox, folder, uid, action)
        messages.success(request, 'Mailbox updated.')
    except Exception as exc:
        messages.error(request, str(exc) if isinstance(exc, ValueError) else friendly_mail_error(exc))
    return redirect(f"{reverse('mail_dashboard')}?{urlencode({'folder': folder})}")


@login_required
def mail_attachment(request, uid, part):
    _org, mailbox = _mailbox_context(request)
    if not _usable(mailbox): raise Http404
    folder = request.GET.get('folder', 'INBOX')[:255]
    try:
        if folder not in list_folders(mailbox): raise Http404
        filename, content_type, data = fetch_attachment(mailbox, folder, uid, part)
    except Http404: raise
    except Exception as exc:
        messages.error(request, friendly_mail_error(exc, 'attachment'))
        return redirect(f"{reverse('mail_inbox_message', args=[uid])}?{urlencode({'folder': folder})}")
    from django.utils.http import content_disposition_header
    response = HttpResponse(data, content_type=content_type)
    response['Content-Disposition'] = content_disposition_header(True, filename)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _validate_addresses(value, label, required=False):
    addresses = [address for _name, address in getaddresses([value or '']) if address]
    if required and not addresses: raise ValueError(f'Enter at least one {label} address.')
    for address in addresses:
        try: validate_email(address)
        except ValidationError as exc: raise ValueError(f'Enter valid {label} addresses.') from exc
    return value


@login_required
def mail_compose(request):
    org, mailbox = _mailbox_context(request)
    if not _usable(mailbox): return redirect('my_work_email')
    form_data = {key: request.POST.get(key, '') if request.method == 'POST' else request.GET.get(key, '')
                 for key in ('to', 'cc', 'subject', 'body', 'in_reply_to', 'references')}
    if request.method == 'POST':
        action = request.POST.get('action', 'send')
        try:
            _validate_addresses(form_data['to'], 'recipient', required=action == 'send')
            _validate_addresses(form_data['cc'], 'CC')
            if any('\r' in form_data[key] or '\n' in form_data[key] for key in ('subject', 'to', 'cc')):
                raise ValueError('Headers cannot contain line breaks.')
            attachments = request.FILES.getlist('attachments')
            if action == 'draft':
                save_draft(mailbox, **{key: form_data[key] for key in ('to', 'cc', 'subject', 'body')}, attachments=attachments)
                messages.success(request, 'Draft saved to your mailbox.')
            elif action == 'send':
                if not form_data['subject'].strip() or not form_data['body'].strip():
                    raise ValueError('Enter a subject and message before sending.')
                sent_copy_saved = send_message(mailbox, **{key: form_data[key] for key in ('to', 'cc', 'subject', 'body', 'in_reply_to', 'references')}, attachments=attachments)
                if sent_copy_saved:
                    messages.success(request, f"Message sent from {mailbox.email_address} and saved in Sent.")
                else:
                    messages.warning(request, f"Message sent from {mailbox.email_address}, but the provider did not save a Sent copy.")
            else: raise ValueError('Unsupported message action.')
            return redirect('mail_dashboard')
        except Exception as exc:
            messages.error(request, str(exc) if isinstance(exc, ValueError) else friendly_mail_error(exc, 'send' if action == 'send' else 'mailbox'))
    return render(request, 'attendance/mail_compose.html', {
        'form_data': form_data, 'mailbox': mailbox, 'page_title': 'Compose email',
    })
