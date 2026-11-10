from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.utils import timezone
from django.utils.html import escape, linebreaks
from datetime import datetime

from attendance.models import AttendanceSettings, BirthdayMessageLog, Employee, Organization


DEFAULT_BIRTHDAY_SUBJECT = 'Happy Birthday, {first_name}! From everyone at {organization_name}'
DEFAULT_BIRTHDAY_BODY = (
    'Dear {display_name},\n\n'
    'Happy birthday from all of us at {organization_name}.\n\n'
    'Today, we celebrate you and the value you bring to the team. We hope your day is filled with joy, '
    'good health, and the kind of moments that remind you how appreciated you are.\n\n'
    'Thank you for being part of {organization_name}. We wish you a wonderful birthday and a year ahead '
    'filled with growth, fulfilment, and success.\n\n'
    'Warm regards,\n'
    'HR Team\n'
    '{organization_name}'
)


def birthday_context(employee, organization):
    return {
        'first_name': employee.first_name,
        'last_name': employee.last_name,
        'full_name': employee.full_name,
        'display_name': employee.display_name,
        'employee_id': employee.employee_id,
        'organization_name': organization.name,
    }


def render_birthday_template(template, employee, organization):
    try:
        return template.format(**birthday_context(employee, organization))
    except KeyError as exc:
        missing_key = exc.args[0]
        return template + f'\n\n[Missing template placeholder: {missing_key}]'


def birthday_subject(employee, organization, settings_obj=None):
    template = getattr(settings_obj, 'birthday_message_subject', '') or DEFAULT_BIRTHDAY_SUBJECT
    return render_birthday_template(template, employee, organization)


def birthday_text_message(employee, organization, settings_obj=None):
    template = getattr(settings_obj, 'birthday_message_body', '') or DEFAULT_BIRTHDAY_BODY
    return render_birthday_template(template, employee, organization)


def birthday_html_message(employee, organization, settings_obj=None):
    body = birthday_text_message(employee, organization, settings_obj)
    return f"""
<div style="font-family: Arial, Helvetica, sans-serif; color: #0f172a; line-height: 1.6; max-width: 640px;">
  <h2 style="color: #020617; margin-bottom: 8px;">{escape(birthday_subject(employee, organization, settings_obj))}</h2>
  {linebreaks(escape(body))}
</div>
"""


class Command(BaseCommand):
    help = 'Send birthday messages to active employees whose birthday is today.'

    def add_arguments(self, parser):
        parser.add_argument('--organization', type=str, help='Organization slug to process.')
        parser.add_argument('--date', type=str, help='Date to process in YYYY-MM-DD format. Defaults to today.')
        parser.add_argument('--dry-run', action='store_true', help='Preview recipients without sending email.')

    def handle(self, *args, **options):
        run_date = datetime.strptime(options['date'], '%Y-%m-%d').date() if options['date'] else timezone.localdate()
        organizations = Organization.objects.filter(is_active=True)
        if options['organization']:
            organizations = organizations.filter(slug=options['organization'])

        sent_count = 0
        skipped_count = 0

        for organization in organizations:
            settings_obj = AttendanceSettings.get_solo(organization)
            employees = Employee.objects.filter(
                organization=organization,
                is_active=True,
                date_of_birth__month=run_date.month,
                date_of_birth__day=run_date.day,
            ).exclude(email='')

            for employee in employees:
                already_sent = BirthdayMessageLog.objects.filter(
                    organization=organization,
                    employee=employee,
                    birthday_year=run_date.year,
                ).exists()
                if already_sent:
                    skipped_count += 1
                    self.stdout.write(f'Skipped {employee.display_name}: already sent for {run_date.year}.')
                    continue

                if options['dry_run']:
                    skipped_count += 1
                    self.stdout.write(f'Would send birthday message to {employee.display_name} <{employee.email}>.')
                    continue

                message = EmailMultiAlternatives(
                    subject=birthday_subject(employee, organization, settings_obj),
                    body=birthday_text_message(employee, organization, settings_obj),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[employee.email],
                    reply_to=[settings.EMAIL_HOST_USER] if getattr(settings, 'EMAIL_HOST_USER', '') else None,
                )
                message.attach_alternative(birthday_html_message(employee, organization, settings_obj), 'text/html')
                message.send(fail_silently=False)
                try:
                    BirthdayMessageLog.objects.create(
                        organization=organization,
                        employee=employee,
                        birthday_year=run_date.year,
                        recipient_email=employee.email,
                    )
                except IntegrityError:
                    skipped_count += 1
                    self.stdout.write(f'Skipped {employee.display_name}: already logged for {run_date.year}.')
                    continue

                sent_count += 1
                self.stdout.write(self.style.SUCCESS(f'Sent birthday message to {employee.display_name} <{employee.email}>.'))

        self.stdout.write(self.style.SUCCESS(f'Birthday messaging complete. Sent: {sent_count}. Skipped: {skipped_count}.'))
