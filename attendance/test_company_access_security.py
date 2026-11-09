from datetime import date

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image
from io import BytesIO

from attendance.models import (
    Category,
    Employee,
    EmployeeDocument,
    Organization,
    OrganizationMembership,
    PayrollRun,
    Payslip,
)


def image_upload(name='logo.png'):
    stream = BytesIO()
    Image.new('RGB', (24, 24), 'navy').save(stream, format='PNG')
    return SimpleUploadedFile(name, stream.getvalue(), content_type='image/png')


class ActiveMembershipAuthorizationTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name='Membership A', slug='membership-a', setup_completed=True)
        self.org_b = Organization.objects.create(name='Membership B', slug='membership-b', setup_completed=True)
        self.category_a = Category.objects.create(organization=self.org_a, name='Staff A', code='STAFF')
        self.user = User.objects.create_user('linked_member', password='pw123456')
        self.membership_a = OrganizationMembership.objects.create(user=self.user, organization=self.org_a, role='employee')
        self.employee = Employee.objects.create(
            organization=self.org_a, user=self.user, employee_id='A-001', category=self.category_a,
            first_name='Ada', last_name='Staff', email='ada@a.example', phone='08000000000', gender='FEMALE',
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_inactive_membership_with_linked_employee_profile_loses_access(self):
        self.membership_a.is_active = False
        self.membership_a.save(update_fields=['is_active'])

        response = self.client.get(reverse('employee_my_profile'), follow=True)

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'You do not have access to an active company', status_code=403)
        self.assertFalse(self.client.session.get('active_organization_id'))

    def test_removed_membership_with_linked_employee_profile_loses_access(self):
        self.membership_a.delete()

        response = self.client.get(reverse('employee_my_profile'), follow=True)

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Your employee profile alone cannot grant access', status_code=403)

    def test_two_company_user_falls_back_to_active_membership_and_cannot_switch_to_inactive(self):
        self.membership_a.is_active = False
        self.membership_a.save(update_fields=['is_active'])
        membership_b = OrganizationMembership.objects.create(user=self.user, organization=self.org_b, role='owner')
        session = self.client.session
        session['active_organization_id'] = self.org_a.pk
        session.save()

        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Membership B')
        self.assertEqual(self.client.session['active_organization_id'], self.org_b.pk)
        switch_response = self.client.get(reverse('organization_switch', args=[self.org_a.pk]))
        self.assertEqual(switch_response.status_code, 404)
        self.assertEqual(self.client.session['active_organization_id'], membership_b.organization_id)

    def test_superuser_without_membership_has_no_company_access(self):
        superuser = User.objects.create_superuser('platform_only', email='platform@example.com', password='pw123456')
        client = Client()
        client.force_login(superuser)

        self.assertEqual(client.get(reverse('dashboard'), follow=True).status_code, 403)
        self.assertEqual(client.get(reverse('digidoc_list'), follow=True).status_code, 403)
        self.assertEqual(client.get(reverse('platform_overview')).status_code, 200)
        self.assertEqual(client.get('/admin/', follow=True).status_code, 403)

    def test_staff_flag_without_membership_does_not_grant_company_access(self):
        staff = User.objects.create_user('unaffiliated_staff_flag', password='pw123456', is_staff=True)
        client = Client()
        client.force_login(staff)

        response = client.get(reverse('employee_list'), follow=True)

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Your employee profile alone cannot grant access', status_code=403)

    def test_active_session_switching_and_direct_company_url_scope(self):
        self.membership_a.role = 'owner'
        self.membership_a.save(update_fields=['role'])
        OrganizationMembership.objects.create(user=self.user, organization=self.org_b, role='owner')
        self.client.get(reverse('organization_switch', args=[self.org_b.pk]))
        self.assertEqual(self.client.session['active_organization_id'], self.org_b.pk)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

        self.org_b.is_active = False
        self.org_b.save(update_fields=['is_active'])
        response = self.client.get(reverse('organization_edit', args=[self.org_b.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.session['active_organization_id'], self.org_a.pk)

    def test_hr_in_one_company_cannot_edit_another_membership_company(self):
        self.membership_a.role = 'owner'
        self.membership_a.save(update_fields=['role'])
        OrganizationMembership.objects.create(user=self.user, organization=self.org_b, role='employee')

        response = self.client.get(reverse('organization_edit', args=[self.org_b.pk]))

        self.assertEqual(response.status_code, 404)


class ViewerCapabilityTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Viewer Company', slug='viewer-company', setup_completed=True)
        category = Category.objects.create(organization=self.org, name='Staff', code='STAFF')
        self.viewer = User.objects.create_user('viewer_account', password='pw123456')
        OrganizationMembership.objects.create(user=self.viewer, organization=self.org, role='viewer')
        self.employee = Employee.objects.create(
            organization=self.org, user=self.viewer, employee_id='V-001', category=category,
            first_name='Vera', last_name='Viewer', email='vera@viewer.example', phone='08000000000', gender='FEMALE',
        )
        self.client = Client()
        self.client.force_login(self.viewer)

    def test_viewer_gets_only_dashboard_and_own_profile_navigation(self):
        dashboard = self.client.get(reverse('dashboard'))
        profile = self.client.get(reverse('employee_my_profile'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(profile.status_code, 200)
        self.assertContains(dashboard, 'Dashboard')
        self.assertContains(profile, 'Vera Viewer')
        nav_labels = [
            item['label']
            for section in dashboard.context['shell_sections']
            for item in section['items']
        ]
        self.assertIn('Dashboard', nav_labels)
        self.assertIn('My profile', nav_labels)
        self.assertNotIn('Employees', nav_labels)
        self.assertNotIn('Payroll runs', nav_labels)
        self.assertNotIn('DigiDoc', nav_labels)

    def test_viewer_cannot_reach_sensitive_pages_or_write_routes(self):
        protected = [
            reverse('employee_list'), reverse('employee_documents'), reverse('attendance_reports'),
            reverse('leave_requests'), reverse('reports'), reverse('export_attendance_csv'),
            reverse('payroll_runs'), reverse('finance_dashboard'), reverse('admin_reports'),
            reverse('organization_settings'), reverse('organization_branding'), reverse('digidoc_list'),
            reverse('mail_dashboard'), reverse('employee_my_documents'), reverse('employee_my_document_upload'),
            reverse('employee_leave_request_create'),
        ]
        for url in protected:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertNotEqual(response.status_code, 200, url)
        before = Employee.objects.count()
        write_urls = [
            reverse('employee_create'), reverse('manual_attendance_add'), reverse('leave_request_create'),
            reverse('payroll_run_create'), reverse('employee_my_document_upload'),
            reverse('employee_leave_request_create'), reverse('digidoc_create'),
            reverse('organization_branding'),
        ]
        for url in write_urls:
            with self.subTest(write_url=url):
                self.assertNotEqual(self.client.post(url, {'first_name': 'Injected'}).status_code, 200)
        self.assertEqual(Employee.objects.count(), before)

    def test_viewer_cannot_download_even_their_own_payslip(self):
        run = PayrollRun.objects.create(organization=self.org, title='Private payroll', payroll_month=date(2026, 1, 1), status='paid')
        payslip = Payslip.objects.create(payroll_run=run, employee=self.employee, bank_account_number='sensitive')

        response = self.client.get(reverse('payslip_detail', args=[payslip.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'sensitive', status_code=403)


class DigiDocOrganizationSwitchTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='DigiDoc Switch', slug='digidoc-switch', setup_completed=True)
        self.owner = User.objects.create_user('switch_owner', password='pw123456')
        OrganizationMembership.objects.create(user=self.owner, organization=self.organization, role='owner')
        self.staff = User.objects.create_user('switch_staff', password='pw123456')
        OrganizationMembership.objects.create(user=self.staff, organization=self.organization, role='employee')
        self.owner_client = Client()
        self.owner_client.force_login(self.owner)
        self.staff_client = Client()
        self.staff_client.force_login(self.staff)

    def test_owner_can_turn_staff_digidoc_off_and_audit_it(self):
        response = self.owner_client.post(reverse('organization_settings'), {'action': 'digidoc_staff_access', 'enabled': 'false'})
        self.assertEqual(response.status_code, 302)
        self.organization.refresh_from_db()
        self.assertFalse(self.organization.allow_staff_digidoc)
        self.assertEqual(self.staff_client.get(reverse('digidoc_list')).status_code, 403)
        from attendance.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(organization=self.organization, action='digidoc.staff_access_changed', metadata={'enabled': False}).exists())
        self.assertEqual(self.owner_client.get(reverse('digidoc_list')).status_code, 200)

    def test_staff_cannot_change_the_company_digidoc_switch(self):
        response = self.staff_client.post(reverse('organization_settings'), {'action': 'digidoc_staff_access', 'enabled': 'false'})
        self.assertNotEqual(response.status_code, 200)
        self.organization.refresh_from_db()
        self.assertTrue(self.organization.allow_staff_digidoc)
