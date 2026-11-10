"""Single entry point for erasing work-mail credentials on account lifecycle changes."""
from .mailbox_security import revoke_user_mailboxes


def revoke_for_membership(user_id, organization_id):
    revoke_user_mailboxes(user_id=user_id, organization_id=organization_id)


def revoke_for_employee(user_id, organization_id):
    if user_id:
        revoke_user_mailboxes(user_id=user_id, organization_id=organization_id)


def revoke_for_user(user_id):
    revoke_user_mailboxes(user_id=user_id)
