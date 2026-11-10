from django.contrib.auth.models import User, UserManager
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from .mailbox_lifecycle import revoke_for_employee, revoke_for_membership, revoke_for_user
from .models import Employee, OrganizationMembership


class WorkMailUserQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if kwargs.get('is_active') is False:
            user_ids = list(self.values_list('pk', flat=True))
            changed = super().update(**kwargs)
            for user_id in user_ids:
                revoke_for_user(user_id)
            return changed
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        objs = list(objs)
        ids = [user.pk for user in objs if 'is_active' in fields and not user.is_active and user.pk]
        changed = super().bulk_update(objs, fields, batch_size=batch_size)
        for user_id in ids:
            revoke_for_user(user_id)
        return changed


# Preserve the standard UserManager in migration state while giving its User queryset
# lifecycle-aware update methods. Managers for any custom user model keep their original
# queryset; this project uses Django's built-in User model.
if not getattr(UserManager, '_work_mail_lifecycle_installed', False):
    _user_manager_get_queryset = UserManager.get_queryset

    def _mailbox_aware_get_queryset(manager):
        if manager.model is User:
            return WorkMailUserQuerySet(manager.model, using=manager._db, hints=manager._hints)
        return _user_manager_get_queryset(manager)

    UserManager.get_queryset = _mailbox_aware_get_queryset
    UserManager._work_mail_lifecycle_installed = True


@receiver(post_save, sender=OrganizationMembership)
def revoke_mail_on_membership_deactivation(sender, instance, **kwargs):
    if not instance.is_active:
        revoke_for_membership(instance.user_id, instance.organization_id)


@receiver(post_delete, sender=OrganizationMembership)
def revoke_mail_on_membership_removal(sender, instance, **kwargs):
    revoke_for_membership(instance.user_id, instance.organization_id)


@receiver(post_save, sender=Employee)
def revoke_mail_on_employee_termination(sender, instance, **kwargs):
    if not instance.is_active or instance.employment_status == 'terminated':
        revoke_for_employee(instance.user_id, instance.organization_id)


@receiver(post_save, sender=User)
def revoke_mail_on_user_deactivation(sender, instance, **kwargs):
    if not instance.is_active:
        revoke_for_user(instance.pk)
