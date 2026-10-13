from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from attendance.models import Organization, OrganizationMembership
from attendance.branding import accent_vars, contrast_text, normalize_hex


def make_org(name='Acme'):
    return Organization.objects.create(name=name, slug=name.lower())


class BrandingTests(TestCase):
    def test_hex_validation(self):
        org = make_org('HexCo')
        org.brand_color = 'not-a-color'
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            org.full_clean()

    def test_logo_type_rejection(self):
        from attendance.forms import OrganizationBrandingForm
        org = make_org('LogoCo')
        bad = SimpleUploadedFile('evil.svg', b'<svg></svg>', content_type='image/svg+xml')
        form = OrganizationBrandingForm(
            {'name': 'LogoCo', 'brand_color': '#1F9D55', 'timezone': 'Africa/Lagos'},
            {'logo': bad}, instance=org)
        self.assertFalse(form.is_valid())
        self.assertIn('logo', form.errors)

    def test_logo_size_rejection(self):
        from attendance.forms import OrganizationBrandingForm
        org = make_org('BigCo')
        big = SimpleUploadedFile('big.png', b'x' * (2 * 1024 * 1024 + 1), content_type='image/png')
        form = OrganizationBrandingForm(
            {'name': 'BigCo', 'brand_color': '#1F9D55', 'timezone': 'Africa/Lagos'},
            {'logo': big}, instance=org)
        self.assertFalse(form.is_valid())

    def test_contrast_light_yellow_gets_dark_text(self):
        self.assertEqual(contrast_text('#FFF9C4'), '#0A0A0B')
        vars_ = accent_vars('#FFF9C4')
        self.assertEqual(vars_['accent_contrast'], '#0A0A0B')
        # readable link variant must differ from unreadable light color
        self.assertNotEqual(vars_['accent_text'], '#FFF9C4')

    def test_isolation(self):
        from attendance.organization import get_active_organization
        a = make_org('CompA')
        b = make_org('CompB')
        u = User.objects.create_user('ownerA', password='pw123456')
        OrganizationMembership.objects.create(user=u, organization=a, role='owner')
        c = Client()
        c.force_login(u)
        # Attacker sets session to company B, which they don't belong to.
        session = c.session
        session['active_organization_id'] = b.pk
        session.save()
        # The branding view resolves the org from memberships, so B is
        # unreachable; posting must not change B.
        resp = c.post('/settings/branding/', {
            'name': 'CompA', 'brand_color': '#FF0000', 'timezone': 'Africa/Lagos',
        })
        b.refresh_from_db()
        self.assertEqual(b.brand_color, '#0A0A0A')
        self.assertEqual(b.name, 'CompB')
        a.refresh_from_db()
        self.assertEqual(a.brand_color, '#FF0000')
        self.assertIn(resp.status_code, (200, 302))

    def test_password_reset_flow(self):
        User.objects.create_user('resetuser', email='r@example.com', password='pw123456')
        c = Client()
        resp = c.get('/password-reset/')
        self.assertEqual(resp.status_code, 200)
        resp = c.post('/password-reset/', {'email': 'r@example.com'})
        self.assertEqual(resp.status_code, 302)
        # unknown email must give same response (no reveal)
        resp2 = c.post('/password-reset/', {'email': 'nobody@example.com'})
        self.assertEqual(resp2.status_code, 302)

    def test_timezone_validation(self):
        from attendance.forms import OrganizationBrandingForm
        org = make_org('TzCo')
        form = OrganizationBrandingForm(
            {'name': 'TzCo', 'brand_color': '#0A0A0A', 'timezone': 'Mars/Olympus'},
            {}, instance=org)
        self.assertFalse(form.is_valid())
        self.assertIn('timezone', form.errors)
        form = OrganizationBrandingForm(
            {'name': 'TzCo', 'brand_color': '#0A0A0A', 'timezone': 'America/New_York'},
            {}, instance=org)
        self.assertTrue(form.is_valid())

    def test_lateness_uses_company_timezone(self):
        from datetime import datetime, timezone as dt_timezone
        from attendance.models import AttendanceRecord, Category, Department, Employee
        from attendance.organization import setup_default_organization_records
        org = make_org('NyCo')
        org.timezone = 'America/New_York'
        org.save(update_fields=['timezone'])
        setup_default_organization_records(org)
        cat = Category.objects.filter(organization=org, code='STAFF').first()
        emp = Employee.objects.create(
            organization=org, category=cat, first_name='Ada', last_name='Test',
            email='ada@nyco.example', phone='08000000001', gender='FEMALE')
        # 12:30 UTC == 08:30 EDT -> late (>= threshold)
        rec_late = AttendanceRecord.objects.create(
            organization=org, employee=emp,
            check_in_time=datetime(2026, 6, 1, 12, 30, tzinfo=dt_timezone.utc))
        self.assertTrue(rec_late.is_late)
        # 12:00 UTC == 08:00 EDT -> on time
        rec_ok = AttendanceRecord.objects.create(
            organization=org, employee=emp,
            check_in_time=datetime(2026, 6, 2, 12, 0, tzinfo=dt_timezone.utc))
        self.assertFalse(rec_ok.is_late)

    def test_logo_resized_on_save(self):
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from attendance.forms import OrganizationBrandingForm
        org = make_org('ResizeCo')
        img = Image.new('RGB', (1200, 800), color='red')
        buf = BytesIO()
        img.save(buf, format='PNG')
        up = SimpleUploadedFile('big-logo.png', buf.getvalue(), content_type='image/png')
        form = OrganizationBrandingForm(
            {'name': 'ResizeCo', 'brand_color': '#0A0A0A', 'timezone': 'Africa/Lagos'},
            {'logo': up}, instance=org)
        self.assertTrue(form.is_valid())
        saved = form.save()
        saved.logo.open()
        out = Image.open(saved.logo)
        self.assertLessEqual(out.width, 512)
        self.assertLessEqual(out.height, 512)
