from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ImproperlyConfigured
from attendance.mailbox_security import rotate_mailbox_credentials


class Command(BaseCommand):
    help = 'Re-encrypt connected work mailbox credentials with MAILBOX_ENCRYPTION_CURRENT_KEY_ID.'

    def handle(self, *args, **options):
        try:
            count = rotate_mailbox_credentials()
        except ImproperlyConfigured as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f'Re-encrypted {count} mailbox credential(s).'))
