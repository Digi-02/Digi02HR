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
        form = OrganizationBrandingForm({'name': 'LogoCo', 'brand_color': '#1F9D55'}, {'logo': bad}, instance=org)
        self.assertFalse(form.is_valid())
        self.assertIn('logo', form.errors)

    def test_logo_size_rejection(self):
        from attendance.forms import OrganizationBrandingForm
        org = make_org('BigCo')
        big = SimpleUploadedFile('big.png', b'x' * (2 * 1024 * 1024 + 1), content_type='image/png')
        form = OrganizationBrandingForm({'name': 'BigCo', 'brand_color': '#1F9D55'}, {'logo': big}, instance=org)
        self.assertFalse(form.is_valid())

    def test_contrast_light_yellow_gets_dark_text(self):
        self.assertEqual(contrast_text('#FFF9C4'), '#0A0A0B')
        vars_ = accent_vars('#FFF9C4')
        self.assertEqual(vars_['accent_contrast'], '#0A0A0B')
        # readable link variant must differ from unreadable light color
        self.assertNotEqual(vars_['accent_text'], '#FFF9C4')

    def test_isolation(self):
        a = make_org('CompA')
        b = make_org('CompB')
        u = User.objects.create_user('ownerA', password='pw123456')
        OrganizationMembership.objects.create(user=u, organization=a, role='owner')
        c = Client()
        c.force_login(u)
        c.session['active_organization_id'] = b.pk
        session = c.session
        session.save()
        # user has no membership in B; branding view must forbid
        resp = c.get('/settings/branding/')
        self.assertIn(resp.status_code, (403, 302))

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
