from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from PIL import Image

from attendance.models import Organization, OrganizationMembership


def make_png(color='red', size=(100, 60)):
    buf = BytesIO()
    Image.new('RGB', size, color=color).save(buf, format='PNG')
    return buf.getvalue()


def make_org_with_owner(name, slug, username):
    org = Organization.objects.create(name=name, slug=slug)
    user = User.objects.create_user(username, email=f'{username}@example.com', password='pw123456')
    OrganizationMembership.objects.create(user=user, organization=org, role='owner')
    return org, user


class BrandingAppliedTests(TestCase):
    def test_saved_colour_reaches_dashboard_employees_attendance(self):
        org, user = make_org_with_owner('GreenCo', 'greenco', 'green_owner')
        org.brand_color = '#1F9D55'
        org.save(update_fields=['brand_color'])
        c = Client()
        c.force_login(user)
        for url in ['/dashboard/', '/employees/', '/attendance/']:
            html = c.get(url).content.decode('utf-8')
            self.assertIn('--accent: #1F9D55;', html, url)
            self.assertIn('--bs-primary: #1F9D55;', html, url)
            self.assertIn('.btn-primary {', html, url)

    def test_upload_logo_renders_in_sidebar(self):
        org, user = make_org_with_owner('LogoCo2', 'logoco2', 'logo_owner')
        c = Client()
        c.force_login(user)
        up = SimpleUploadedFile('mark.png', make_png(), content_type='image/png')
        resp = c.post('/settings/branding/', {
            'name': 'LogoCo2', 'brand_color': '#0A0A0A', 'timezone': 'Africa/Lagos',
            'nav_style': 'black', 'nav_bg_color': '#0A0A0A',
            'nav_highlight_style': 'pill', 'nav_highlight_source': 'auto',
            'nav_highlight_color': '#0A0A0A', 'logo': up})
        self.assertEqual(resp.status_code, 302)
        org.refresh_from_db()
        self.assertTrue(bool(org.logo))
        html = c.get('/dashboard/').content.decode('utf-8')
        self.assertIn(org.logo.url, html)
        self.assertIn('brand-logo-full', html)

    def test_replace_and_remove_logo(self):
        org, user = make_org_with_owner('SwapCo', 'swapco', 'swap_owner')
        c = Client()
        c.force_login(user)
        first = SimpleUploadedFile('one.png', make_png('red'), content_type='image/png')
        c.post('/settings/branding/', {
            'name': 'SwapCo', 'brand_color': '#0A0A0A', 'timezone': 'Africa/Lagos',
            'nav_style': 'black', 'nav_bg_color': '#0A0A0A',
            'nav_highlight_style': 'pill', 'nav_highlight_source': 'auto',
            'nav_highlight_color': '#0A0A0A', 'logo': first})
        org.refresh_from_db()
        first_name = org.logo.name
        second = SimpleUploadedFile('two.png', make_png('blue'), content_type='image/png')
        c.post('/settings/branding/', {
            'name': 'SwapCo', 'brand_color': '#0A0A0A', 'timezone': 'Africa/Lagos',
            'nav_style': 'black', 'nav_bg_color': '#0A0A0A',
            'nav_highlight_style': 'pill', 'nav_highlight_source': 'auto',
            'nav_highlight_color': '#0A0A0A', 'logo': second})
        org.refresh_from_db()
        self.assertNotEqual(org.logo.name, first_name)
        self.assertIn(org.logo.url, c.get('/dashboard/').content.decode('utf-8'))
        # Remove
        c.post('/settings/branding/', {
            'name': 'SwapCo', 'brand_color': '#0A0A0A', 'timezone': 'Africa/Lagos',
            'nav_style': 'black', 'nav_bg_color': '#0A0A0A',
            'nav_highlight_style': 'pill', 'nav_highlight_source': 'auto',
            'nav_highlight_color': '#0A0A0A', 'remove_logo': 'on'})
        org.refresh_from_db()
        self.assertFalse(bool(org.logo))
        html = c.get('/dashboard/').content.decode('utf-8')
        self.assertNotIn('brand-logo-tile"><img', html)
        self.assertIn('brand-initials', html)

    def test_company_a_branding_not_shown_to_company_b(self):
        org_a, user_a = make_org_with_owner('AyeCo', 'ayeco', 'aye_owner')
        org_b, user_b = make_org_with_owner('BeeCo', 'beeco', 'bee_owner')
        org_a.brand_color = '#1F9D55'
        org_a.save(update_fields=['brand_color'])
        org_b.brand_color = '#DC2626'
        org_b.save(update_fields=['brand_color'])
        ca, cb = Client(), Client()
        ca.force_login(user_a)
        cb.force_login(user_b)
        html_a = ca.get('/dashboard/').content.decode('utf-8')
        html_b = cb.get('/dashboard/').content.decode('utf-8')
        self.assertIn('--accent: #1F9D55;', html_a)
        self.assertNotIn('--accent: #DC2626;', html_a)
        self.assertIn('--accent: #DC2626;', html_b)
        self.assertNotIn('--accent: #1F9D55;', html_b)

    def test_light_logo_gets_dark_tile(self):
        from attendance.forms import OrganizationBrandingForm
        org, user = make_org_with_owner('TileCo', 'tileco', 'tile_owner')
        c = Client()
        c.force_login(user)
        nav = {'nav_style': 'black', 'nav_bg_color': '#0A0A0A',
               'nav_highlight_style': 'pill', 'nav_highlight_source': 'auto',
               'nav_highlight_color': '#0A0A0A'}
        white = SimpleUploadedFile('w.png', make_png('white'), content_type='image/png')
        resp = c.post('/settings/branding/', {
            'name': 'TileCo', 'brand_color': '#0A0A0A', 'timezone': 'Africa/Lagos',
            **nav, 'logo': white})
        self.assertEqual(resp.status_code, 302)
        org.refresh_from_db()
        self.assertTrue(org.logo_is_light)
        html = c.get('/dashboard/').content.decode('utf-8')
        self.assertIn('brand-logo-full dark-tile', html)
        # Dark logo keeps the white tile
        black = SimpleUploadedFile('b.png', make_png('black'), content_type='image/png')
        c.post('/settings/branding/', {
            'name': 'TileCo', 'brand_color': '#0A0A0A', 'timezone': 'Africa/Lagos',
            **nav, 'logo': black})
        org.refresh_from_db()
        self.assertFalse(org.logo_is_light)
        html = c.get('/dashboard/').content.decode('utf-8')
        self.assertIn('brand-logo-full', html)
        self.assertNotIn('brand-logo-full dark-tile', html)

    def test_blank_transparent_logo_rejected(self):
        from attendance.forms import OrganizationBrandingForm
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        org, _ = make_org_with_owner("BlankCo", "blankco", "blank_owner")
        buf = BytesIO()
        Image.new("RGBA", (200, 80), (0, 0, 0, 0)).save(buf, format="PNG")
        blank = SimpleUploadedFile("blank.png", buf.getvalue(), content_type="image/png")
        form = OrganizationBrandingForm(
            {"name": "BlankCo", "brand_color": "#0A0A0A", "timezone": "Africa/Lagos",
             "nav_style": "black", "nav_bg_color": "#0A0A0A",
             "nav_highlight_style": "pill", "nav_highlight_source": "auto",
             "nav_highlight_color": "#0A0A0A"},
            {"logo": blank}, instance=org)
        self.assertFalse(form.is_valid())
        self.assertIn("logo", form.errors)
