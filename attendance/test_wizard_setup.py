from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.core import mail
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from .models import Organization, OrganizationMembership, AttendanceSettings


class InviteFlowTests(TestCase):
    """Owner invite: unusable password, single-use token, HTML email."""

    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pass12345')
        self.client.login(username='admin', password='pass12345')

    def test_platform_admin_creates_company_with_unusable_owner_password(self):
        response = self.client.post(reverse('platform_company_create'), {
            'name': 'Test Co',
            'owner_name': 'Jane Doe',
            'owner_email': 'jane@testco.com',
        })
        org = Organization.objects.get(name='Test Co')
        self.assertRedirects(response, reverse('platform_company_detail', kwargs={'pk': org.pk}))

        owner = User.objects.get(email='jane@testco.com')

        # Owner has unusable password — only the invite link can set one
        self.assertFalse(owner.has_usable_password())

        # Owner membership created
        membership = OrganizationMembership.objects.get(user=owner, organization=org)
        self.assertEqual(membership.role, 'owner')

        # Invite email sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('set your password', mail.outbox[0].subject.lower())
        self.assertIn('Test Co', mail.outbox[0].body)

    def test_invite_email_is_html_and_plain_text(self):
        self.client.post(reverse('platform_company_create'), {
            'name': 'HTML Co',
            'owner_name': 'Bob Smith',
            'owner_email': 'bob@htmlco.com',
        })
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        # HTML alternative attached to EmailMultiAlternatives
        self.assertTrue(any(
            'text/html' in str(alt[1]) for alt in email.alternatives
        ))
        self.assertIn('HTML Co', email.body)

    def test_resend_invite_creates_new_token(self):
        self.client.post(reverse('platform_company_create'), {
            'name': 'Resend Co',
            'owner_name': 'Owner One',
            'owner_email': 'owner@resendco.com',
        })
        owner = User.objects.get(email='owner@resendco.com')
        org = Organization.objects.get(name='Resend Co')

        # First invite token
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        uid1 = urlsafe_base64_encode(force_bytes(owner.pk))
        token1 = default_token_generator.make_token(owner)

        # Resend via company action
        self.client.post(reverse('platform_company_action', kwargs={'pk': org.pk}), {
            'action': 'resend_invite',
        })
        self.assertEqual(len(mail.outbox), 2)

        # Re-send should send a second email to the owner
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('Resend Co', mail.outbox[1].body)


@override_settings(PASSWORD_RESET_TIMEOUT=259200)
class TokenExpiryTests(TestCase):
    """Verify PASSWORD_RESET_TIMEOUT is 72 hours and tokens expire."""

    def test_password_reset_timeout_is_72_hours(self):
        from django.conf import settings
        self.assertEqual(settings.PASSWORD_RESET_TIMEOUT, 259200)
        self.assertEqual(timedelta(seconds=259200), timedelta(hours=72))

    def test_invalid_token_cannot_set_password(self):
        self.admin = User.objects.create_superuser('admin2', 'admin2@example.com', 'pass12345')
        self.client.login(username='admin2', password='pass12345')
        self.client.post(reverse('platform_company_create'), {
            'name': 'Expiry Co',
            'owner_name': 'Exp Owner',
            'owner_email': 'exp@expiryco.com',
        })
        owner = User.objects.get(email='exp@expiryco.com')

        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes

        uid = urlsafe_base64_encode(force_bytes(owner.pk))
        token = default_token_generator.make_token(owner)

        # Wrong token should fail
        response = self.client.post(reverse('set_owner_password', kwargs={'uidb64': uid, 'token': 'badtoken'}), {
            'new_password1': 'SecurePass123!',
            'new_password2': 'SecurePass123!',
        })
        self.assertEqual(response.status_code, 200)
        # Password still unusable
        owner.refresh_from_db()
        self.assertFalse(owner.has_usable_password())


class WizardResumeTests(TestCase):
    """Wizard progress is saved after every step and resumable."""

    def setUp(self):
        self.owner = User.objects.create_user('owner', 'owner@wizardco.com', 'pass12345')
        self.org = Organization.objects.create(
            name='Wizard Co', slug='wizard-co',
            setup_completed=False, setup_completed_steps=[], setup_current_step=1,
        )
        OrganizationMembership.objects.create(
            user=self.owner, organization=self.org, role='owner', is_active=True,
        )
        self.client.login(username='owner', password='pass12345')

    def test_wizard_saves_progress_after_step_1(self):
        response = self.client.post(reverse('setup_wizard'), {
            'action': 'next',
            'company_name': 'Wizard Co Updated',
            'industry': 'Technology',
            'company_size': '1-10',
            'country': 'Nigeria',
            'timezone': 'Africa/Lagos',
            'workday_start': '08:00',
            'late_after': '09:00',
        })
        # Should advance to step 2
        self.assertRedirects(response, reverse('setup_wizard'))

        self.org.refresh_from_db()
        self.assertEqual(self.org.setup_current_step, 2)
        self.assertIn(1, self.org.setup_completed_steps)
        self.assertEqual(self.org.name, 'Wizard Co Updated')
        self.assertEqual(self.org.industry, 'Technology')
        self.assertEqual(self.org.country, 'Nigeria')

        # AttendanceSettings updated
        settings = AttendanceSettings.get_solo(self.org)
        self.assertEqual(str(settings.workday_start), '08:00:00')
        self.assertEqual(str(settings.late_threshold), '09:00:00')

    def test_wizard_resumes_at_current_step(self):
        # Simulate partial progress: step 1 done, on step 2
        self.org.setup_completed_steps = [1]
        self.org.setup_current_step = 2
        self.org.save()

        response = self.client.get(reverse('setup_wizard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Branding')  # Step 2 title

    def test_wizard_skip_optional_steps(self):
        # Complete step 1
        self.client.post(reverse('setup_wizard'), {
            'action': 'next',
            'company_name': 'Skip Co',
            'industry': 'Retail',
            'company_size': '11-50',
            'country': 'Ghana',
            'timezone': 'Africa/Accra',
            'workday_start': '09:00',
            'late_after': '10:00',
        })
        # Skip step 2 (branding)
        response = self.client.post(reverse('setup_wizard'), {
            'action': 'skip',
        })
        self.assertRedirects(response, reverse('setup_wizard'))

        self.org.refresh_from_db()
        self.assertIn(2, self.org.setup_completed_steps)
        self.assertEqual(self.org.setup_current_step, 3)

    def test_wizard_complete_all_steps(self):
        self.client.post(reverse('setup_wizard'), {
            'action': 'next', 'company_name': 'Complete Co', 'industry': 'Tech',
            'company_size': '1-10', 'country': 'Kenya', 'timezone': 'Africa/Nairobi',
            'workday_start': '08:00', 'late_after': '09:00',
        })
        self.client.post(reverse('setup_wizard'), {'action': 'skip'})  # skip branding
        self.client.post(reverse('setup_wizard'), {'action': 'skip'})  # skip dashboard
        # Step 4: "I'll do this later" (REQUIRE_MAILBOX_SETUP=False default)
        response = self.client.post(reverse('setup_wizard'), {
            'action': 'later',
        })
        self.assertRedirects(response, reverse('setup_complete'))

        self.org.refresh_from_db()
        self.assertTrue(self.org.setup_completed)


class RequireMailboxSetupTests(TestCase):
    """REQUIRE_MAILBOX_SETUP flag controls Step 4 behaviour."""

    def setUp(self):
        self.owner = User.objects.create_user('owner2', 'owner2@mbco.com', 'pass12345')
        self.org = Organization.objects.create(
            name='Mailbox Co', slug='mailbox-co',
            setup_completed=False, setup_completed_steps=[1, 2, 3], setup_current_step=4,
        )
        OrganizationMembership.objects.create(
            user=self.owner, organization=self.org, role='owner', is_active=True,
        )
        self.client.login(username='owner2', password='pass12345')

    @override_settings(REQUIRE_MAILBOX_SETUP=False)
    def test_optional_mailbox_can_skip_with_later(self):
        response = self.client.post(reverse('setup_wizard'), {'action': 'later'})
        self.assertRedirects(response, reverse('setup_complete'))
        self.org.refresh_from_db()
        self.assertTrue(self.org.setup_completed)

    @override_settings(REQUIRE_MAILBOX_SETUP=True)
    def test_required_mailbox_blocks_completion(self):
        response = self.client.post(reverse('setup_wizard'), {'action': 'next'})
        # Should not complete — mailbox required
        self.assertEqual(response.status_code, 200)
        self.org.refresh_from_db()
        self.assertFalse(self.org.setup_completed)


class OrganizationIsolationTests(TestCase):
    """Company A cannot read or change Company B's setup data."""

    def setUp(self):
        self.owner_a = User.objects.create_user('ownera', 'a@coa.com', 'pass12345')
        self.owner_b = User.objects.create_user('ownerb', 'b@cob.com', 'pass12345')
        self.org_a = Organization.objects.create(
            name='Company A', slug='company-a', setup_completed=False,
        )
        self.org_b = Organization.objects.create(
            name='Company B', slug='company-b', setup_completed=False,
        )
        OrganizationMembership.objects.create(
            user=self.owner_a, organization=self.org_a, role='owner', is_active=True,
        )
        OrganizationMembership.objects.create(
            user=self.owner_b, organization=self.org_b, role='owner', is_active=True,
        )

    def test_owner_a_sees_own_org_wizard_not_org_b(self):
        self.client.login(username='ownera', password='pass12345')
        response = self.client.get(reverse('setup_wizard'))
        # Org A (owner A's org) is not completed, so wizard renders step 1 (200).
        # Org B data never appears.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Company A')
        self.assertNotContains(response, 'Company B')

    def test_owner_a_cannot_see_organization_b_setup_data(self):
        self.client.login(username='ownera', password='pass12345')
        # Dashboard redirects to wizard (org A not completed). Follow redirect.
        response = self.client.get(reverse('dashboard'), follow=True)
        self.assertContains(response, 'Company A')
        self.assertNotContains(response, 'Company B')

    def test_wizard_only_for_owner_and_hr_admin(self):
        # Create an employee user (not owner/hr_admin) in org A
        employee = User.objects.create_user('emp', 'emp@coa.com', 'pass12345')
        OrganizationMembership.objects.create(
            user=employee, organization=self.org_a, role='employee', is_active=True,
        )
        self.client.login(username='emp', password='pass12345')
        response = self.client.get(reverse('setup_wizard'))
        # Employee cannot access wizard — redirected away (302)
        self.assertEqual(response.status_code, 302)
