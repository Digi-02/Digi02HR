from django.contrib.auth.models import User
from django.test import Client, TestCase

from attendance.branding import contrast_ratio, nav_vars
from attendance.forms import OrganizationBrandingForm
from attendance.models import Organization, OrganizationMembership


def make_org_with_owner(name, slug, username):
    org = Organization.objects.create(name=name, slug=slug)
    user = User.objects.create_user(username, email=f'{username}@example.com', password='pw123456')
    OrganizationMembership.objects.create(user=user, organization=org, role='owner')
    return org, user


def valid_nav(**over):
    data = {
        'name': 'NavCo', 'brand_color': '#0A0A0A', 'timezone': 'Africa/Lagos',
        'nav_style': 'black', 'nav_bg_color': '#0A0A0A',
        'nav_highlight_style': 'pill', 'nav_highlight_source': 'auto',
        'nav_highlight_color': '#0A0A0A',
    }
    data.update(over)
    return data


class NavValidationTests(TestCase):
    def test_bad_hex_rejected(self):
        org = Organization.objects.create(name='HexNav', slug='hexnav')
        for field in ('nav_bg_color', 'nav_highlight_color'):
            form = OrganizationBrandingForm(valid_nav(**{field: 'red'}), {}, instance=org)
            self.assertFalse(form.is_valid(), field)
            self.assertIn(field, form.errors)

    def test_contrast_white_sidebar_dark_text(self):
        v = nav_vars(nav_style='white')
        self.assertEqual(v['nav_bg'], '#FFFFFF')
        self.assertEqual(v['nav_fg'], '#0A0A0A')
        self.assertGreaterEqual(contrast_ratio(v['nav_fg'], v['nav_bg']), 4.5)

    def test_contrast_pale_yellow_custom_dark_text(self):
        v = nav_vars(nav_style='custom', nav_bg_color='#FFF9C4')
        self.assertEqual(v['nav_fg'], '#0A0A0A')
        self.assertGreaterEqual(contrast_ratio(v['nav_fg'], v['nav_bg']), 4.5)

    def test_contrast_navy_white_text(self):
        v = nav_vars(nav_style='custom', nav_bg_color='#0B1226')
        self.assertEqual(v['nav_fg'], '#FFFFFF')
        self.assertGreaterEqual(contrast_ratio(v['nav_fg'], v['nav_bg']), 4.5)

    def test_all_highlight_styles_have_vars(self):
        for style in ('pill', 'left_bar', 'soft_tint', 'outline'):
            v = nav_vars(nav_highlight_style=style)
            for key in ('nav_bg', 'nav_fg', 'nav_fg_muted', 'nav_border',
                        'nav_hover_bg', 'nav_active_bg', 'nav_active_fg',
                        'nav_active_indicator'):
                self.assertIn(key, v, (style, key))
            self.assertEqual(v['nav_highlight_style'], style)


class NavIsolationTests(TestCase):
    def test_each_highlight_style_renders(self):
        org, user = make_org_with_owner('StyleCo', 'styleco', 'style_owner')
        c = Client()
        c.force_login(user)
        for style in ('pill', 'left_bar', 'soft_tint', 'outline'):
            org.nav_highlight_style = style
            org.save(update_fields=['nav_highlight_style'])
            html = c.get('/dashboard/').content.decode('utf-8')
            self.assertIn(f'data-nav-highlight="{style}"', html, style)
            self.assertIn('--nav-bg:', html, style)

    def test_company_a_nav_does_not_affect_company_b(self):
        org_a, user_a = make_org_with_owner('NavA', 'nava', 'nava_owner')
        org_b, user_b = make_org_with_owner('NavB', 'navb', 'navb_owner')
        org_a.nav_style = 'white'
        org_a.save(update_fields=['nav_style'])
        ca, cb = Client(), Client()
        ca.force_login(user_a)
        cb.force_login(user_b)
        self.assertIn('--nav-bg: #FFFFFF;', ca.get('/dashboard/').content.decode('utf-8'))
        self.assertIn('--nav-bg: #0A0A0A;', cb.get('/dashboard/').content.decode('utf-8'))

    def test_accent_change_does_not_change_nav_bg(self):
        org, user = make_org_with_owner('AccNav', 'accnav', 'accnav_owner')
        c = Client()
        c.force_login(user)
        before = c.get('/dashboard/').content.decode('utf-8')
        self.assertIn('--nav-bg: #0A0A0A;', before)
        c.post('/settings/branding/', valid_nav(
            name='AccNav', brand_color='#1F9D55', nav_style='black'))
        html = c.get('/dashboard/').content.decode('utf-8')
        self.assertIn('--accent: #1F9D55;', html)
        self.assertIn('--nav-bg: #0A0A0A;', html)
