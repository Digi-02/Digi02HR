"""Encryption and revocation helpers for individual work mailboxes."""
import base64
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _keyring():
    keys = getattr(settings, 'MAILBOX_ENCRYPTION_KEYS', {}) or {}
    current = getattr(settings, 'MAILBOX_ENCRYPTION_CURRENT_KEY_ID', '')
    if not isinstance(keys, dict) or not current or current not in keys:
        raise ImproperlyConfigured('Configure MAILBOX_ENCRYPTION_KEYS and MAILBOX_ENCRYPTION_CURRENT_KEY_ID.')
    result = {}
    for key_id, value in keys.items():
        try:
            raw = value.encode('ascii') if isinstance(value, str) else value
            decoded = base64.urlsafe_b64decode(raw)
            if len(decoded) != 32:
                raise ValueError('Fernet keys must decode to 32 bytes.')
            result[str(key_id)] = Fernet(raw)
        except Exception as exc:
            raise ImproperlyConfigured(f'Invalid mailbox encryption key {key_id!r}.') from exc
    return current, result


def encrypt_password(password):
    current, keys = _keyring()
    return current, keys[current].encrypt(password.encode('utf-8')).decode('ascii')


def decrypt_password(ciphertext, key_id):
    _current, keys = _keyring()
    if key_id not in keys:
        raise ImproperlyConfigured(f'Mailbox encryption key {key_id!r} is unavailable.')
    try:
        return keys[key_id].decrypt(ciphertext.encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise ImproperlyConfigured('Mailbox credentials could not be decrypted.') from exc


def revoke_mailbox(mailbox):
    """Clear encrypted credentials and disable one mailbox without touching the HR account."""
    if mailbox is None:
        return
    mailbox.password_ciphertext = ''
    mailbox.encryption_key_id = ''
    mailbox.is_connected = False
    mailbox.save(update_fields=['password_ciphertext', 'encryption_key_id', 'is_connected', 'updated_at'])


def revoke_user_mailboxes(*, user_id, organization_id=None):
    from .models import WorkMailbox
    rows = WorkMailbox.objects.filter(user_id=user_id)
    if organization_id is not None:
        rows = rows.filter(organization_id=organization_id)
    rows.update(password_ciphertext='', encryption_key_id='', is_connected=False)


def rotate_mailbox_credentials(*, new_key_id=None):
    """Re-encrypt all live credentials with the configured current key."""
    current, _keys = _keyring()
    if new_key_id and current != new_key_id:
        raise ImproperlyConfigured('Set MAILBOX_ENCRYPTION_CURRENT_KEY_ID to the new key before rotation.')
    from .models import WorkMailbox
    changed = 0
    for mailbox in WorkMailbox.objects.filter(is_connected=True).exclude(password_ciphertext='').iterator():
        if mailbox.encryption_key_id == current:
            continue
        password = decrypt_password(mailbox.password_ciphertext, mailbox.encryption_key_id)
        mailbox.encryption_key_id, mailbox.password_ciphertext = encrypt_password(password)
        mailbox.save(update_fields=['encryption_key_id', 'password_ciphertext', 'updated_at'])
        changed += 1
    return changed
