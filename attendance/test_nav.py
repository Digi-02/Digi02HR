import importlib

from django.apps import apps
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from attendance.branding import contrast_ratio, nav_vars
from attendance.forms import OrganizationBrandingForm
from attendance.models import Organization, OrganizationMembership


def make_org_with_owner(name, slug, username):
    org = Organization.objects.create(name=name, slug=slug, setup_completed=True)
    user = User.objects.create_user(username, email=f'{username}@example.com', password='pw123456')
    OrganizationMembership.objects.create(user=user, organization=org, role='owner')
    return org, user


def valid_nav(**over):
    data = {
        'name': 'NavCo', 'brand_color': '#0A0A0A', 'timezone': 'Africa/Lagos',
        'nav_style': 'clean', 'nav_bg_color': '#0A0A0A',
        'nav_highlight_style': 'rounded_pill', 'nav_highlight_source': 'auto',
        'nav_highlight_color': '#111111',
        'nav_text_color': '', 'nav_muted_color': '', 'nav_hover_bg': '',
        'nav_hover_fg': '', 'nav_active_icon_bg': '', 'nav_active_icon_fg': '',
    }
    data.update(over)
    return data


class NavResolverTests(TestCase):
    def test_clean_default_is_the_jobgio_black_pill(self):
        v = nav_vars(nav_style='clean')
        self.assertEqual(v['nav_bg'], '#FFFFFF')
        self.assertEqual(v['nav_fg'], '#1C1C1C')
        self.assertEqual(v['nav_active_style'], 'rounded_pill')
        self.assertEqual(v['nav_active_bg'], '#111111')
        self.assertEqual(v['nav_active_fg'], '#FFFFFF')
        self.assertEqual(v['nav_active_icon_bg'], '#FFFFFF')
        self.assertEqual(v['nav_active_icon_fg'], '#111111')
        self.assertGreaterEqual(contrast_ratio(v['nav_fg_muted'], v['nav_bg']), 4.5)
        self.assertGreaterEqual(contrast_ratio(v['nav_active_fg'], v['nav_active_bg']), 4.5)

    def test_legacy_values_are_resolved(self):
        dark = nav_vars(nav_style='black', nav_highlight_style='pill')
        self.assertEqual(dark['nav_appearance'], 'dark')
        self.assertEqual(dark['nav_active_style'], 'rounded_pill')
        self.assertEqual(dark['nav_bg'], '#0A0A0A')
        self.assertEqual(dark['nav_active_bg'], '#FFFFFF')

        light = nav_vars(nav_style='light_grey', nav_highlight_style='soft_tint')
        self.assertEqual(light['nav_appearance'], 'light')
        self.assertEqual(light['nav_active_style'], 'soft_pill')
        self.assertEqual(light['nav_bg'], '#F5F5F5')

        minimal = nav_vars(nav_highlight_style='left_bar')
        self.assertEqual(minimal['nav_active_style'], 'minimal')
        self.assertEqual(minimal['nav_active_bg'], 'transparent')

    def test_pale_custom_background_gets_dark_readable_text(self):
        v = nav_vars(nav_style='custom', nav_bg_color='#FFF9C4')
        self.assertEqual(v['nav_bg'], '#FFF9C4')
        self.assertGreaterEqual(contrast_ratio(v['nav_fg'], v['nav_bg']), 4.5)
        self.assertLess(contrast_ratio(v['nav_fg'], v['nav_bg']), 21)

    def test_navy_custom_background_gets_light_text(self):
        v = nav_vars(nav_style='custom', nav_bg_color='#0B1226')
        self.assertEqual(v['nav_bg'], '#0B1226')
        self.assertGreaterEqual(contrast_ratio(v['nav_fg'], v['nav_bg']), 4.5)

    def test_every_active_style_has_complete_accessible_tokens(self):
        for style in ('rounded_pill', 'soft_pill', 'minimal', 'outline', 'custom'):
            v = nav_vars(nav_style='clean', nav_highlight_style=style)
            for key in (
                'nav_bg', 'nav_fg', 'nav_fg_muted', 'nav_border', 'nav_hover_bg',
                'nav_hover_fg', 'nav_icon_bg', 'nav_icon_fg', 'nav_active_bg',
                'nav_active_fg', 'nav_active_icon_bg', 'nav_active_icon_fg',
                'nav_active_indicator', 'nav_active_border', 'nav_pill_bg',
            ):
                self.assertIn(key, v, (style, key))
            self.assertEqual(v['nav_active_style'], style)
            self.assertGreaterEqual(contrast_ratio(v['nav_fg'], v['nav_bg']), 4.5)
            self.assertGreaterEqual(contrast_ratio(v['nav_active_fg'], v['nav_active_bg'] if v['nav_active_bg'] != 'transparent' else v['nav_bg']), 4.5)
            self.assertGreaterEqual(contrast_ratio(v['nav_active_icon_fg'], v['nav_active_icon_bg']), 4.5)

    def test_company_brand_highlight_is_used_when_requested(self):
        v = nav_vars(nav_style='clean', nav_highlight_source='accent', accent='#1F9D55')
        self.assertEqual(v['nav_active_bg'], '#1F9D55')
        self.assertGreaterEqual(contrast_ratio(v['nav_active_fg'], '#1F9D55'), 4.5)

    def test_dark_sidebar_default_black_auto_inverts(self):
        v = nav_vars(nav_style='dark', nav_highlight_source='auto')
        self.assertEqual(v['nav_bg'], '#0A0A0A')
        self.assertEqual(v['nav_active_bg'], '#FFFFFF')
        self.assertEqual(v['nav_active_fg'], '#0A0A0B')

    def test_evergreen_sidebar_preset_is_readable(self):
        v = nav_vars(nav_style='teal')
        self.assertEqual(v['nav_bg'], '#3B5B57')
        self.assertGreaterEqual(contrast_ratio(v['nav_fg'], v['nav_bg']), 4.5)
        self.assertGreaterEqual(contrast_ratio(v['nav_fg_muted'], v['nav_bg']), 4.5)

    def test_unreadable_explicit_colours_are_ignored(self):
        v = nav_vars(nav_style='clean', nav_text_color='#EEEEEE', nav_muted_color='#F5F5F5')
        self.assertEqual(v['nav_fg'], '#1C1C1C')
        self.assertEqual(v['nav_fg_muted'], '#6B6B6B')


class NavValidationTests(TestCase):
    def test_bad_hex_rejected(self):
        org = Organization.objects.create(name='HexNav', slug='hexnav')
        for field in ('nav_bg_color', 'nav_highlight_color'):
            form = OrganizationBrandingForm(valid_nav(**{field: 'red'}), {}, instance=org)
            self.assertFalse(form.is_valid(), field)
            self.assertIn(field, form.errors)

    def test_unreadable_custom_text_is_rejected(self):
        org = Organization.objects.create(name='ContrastNav', slug='contrastnav')
        form = OrganizationBrandingForm(
            valid_nav(nav_text_color='#EEEEEE'), {}, instance=org
        )
        self.assertFalse(form.is_valid())
        self.assertIn('nav_text_color', form.errors)

    def test_legacy_post_values_are_normalised_and_saved(self):
        org = Organization.objects.create(name='LegacyNav', slug='legacynav')
        form = OrganizationBrandingForm(
            valid_nav(nav_style='white', nav_highlight_style='pill',
                      nav_highlight_source='accent'),
            {}, instance=org
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        saved.refresh_from_db()
        self.assertEqual(saved.nav_style, 'clean')
        self.assertEqual(saved.nav_highlight_style, 'rounded_pill')
        self.assertTrue(saved.nav_customized)

    def test_model_default_is_clean_and_rounded_pill(self):
        org = Organization.objects.create(name='CleanCo', slug='cleanco')
        self.assertEqual(org.nav_style, 'clean')
        self.assertEqual(org.nav_highlight_style, 'rounded_pill')
        self.assertFalse(org.nav_customized)


class NavIsolationTests(TestCase):
    def test_each_active_style_renders_in_the_real_shell(self):
        org, user = make_org_with_owner('StyleCo', 'styleco', 'style_owner')
        c = Client()
        c.force_login(user)
        for style in ('rounded_pill', 'soft_pill', 'minimal', 'outline', 'custom'):
            org.nav_style = 'clean'
            org.nav_highlight_style = style
            org.save(update_fields=['nav_style', 'nav_highlight_style'])
            html = c.get('/dashboard/').content.decode('utf-8')
            self.assertIn(f'data-nav-active="{style}"', html, style)
            self.assertIn('--nav-bg: #FFFFFF;', html, style)
            self.assertIn('app-nav__link', html, style)

    def test_company_a_nav_does_not_affect_company_b(self):
        org_a, user_a = make_org_with_owner('NavA', 'nava', 'nava_owner')
        org_b, user_b = make_org_with_owner('NavB', 'navb', 'navb_owner')
        org_a.nav_style = 'clean'
        org_a.save(update_fields=['nav_style'])
        org_b.nav_style = 'dark'
        org_b.save(update_fields=['nav_style'])
        ca, cb = Client(), Client()
        ca.force_login(user_a)
        cb.force_login(user_b)
        self.assertIn('--nav-bg: #FFFFFF;', ca.get('/dashboard/').content.decode('utf-8'))
        self.assertIn('--nav-bg: #0A0A0A;', cb.get('/dashboard/').content.decode('utf-8'))

    def test_accent_change_does_not_change_nav_bg(self):
        org, user = make_org_with_owner('AccNav', 'accnav', 'accnav_owner')
        org.nav_style = 'clean'
        org.save(update_fields=['nav_style'])
        c = Client()
        c.force_login(user)
        before = c.get('/dashboard/').content.decode('utf-8')
        self.assertIn('--nav-bg: #FFFFFF;', before)
        c.post('/settings/branding/', valid_nav(
            name='AccNav', brand_color='#1F9D55', nav_style='clean'))
        html = c.get('/dashboard/').content.decode('utf-8')
        self.assertIn('--accent: #1F9D55;', html)
        self.assertIn('--nav-bg: #FFFFFF;', html)

    def test_preview_endpoint_returns_resolved_tokens(self):
        org, user = make_org_with_owner('PreviewCo', 'previewco', 'preview_owner')
        c = Client()
        c.force_login(user)
        response = c.get(reverse('organization_nav_preview'), {
            'nav_style': 'custom',
            'nav_bg_color': '#FFF9C4',
            'nav_highlight_style': 'outline',
            'nav_highlight_source': 'automatically-invalid',
            'nav_highlight_color': '#111111',
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['styles']['nav_bg'], '#FFF9C4')
        self.assertEqual(payload['styles']['nav_active_style'], 'outline')
        self.assertEqual(payload['styles']['nav_highlight_source'], 'auto')
        self.assertIn('text', payload['contrast'])

    def test_evergreen_appearance_is_selectable_and_previewable(self):
        org, user = make_org_with_owner('EvergreenCo', 'evergreenco', 'evergreen_owner')
        c = Client()
        c.force_login(user)
        settings_page = c.get('/settings/branding/').content.decode('utf-8')
        self.assertIn('value="teal"', settings_page)
        payload = c.get(reverse('organization_nav_preview'), {
            'nav_style': 'teal',
            'nav_highlight_style': 'rounded_pill',
            'nav_highlight_source': 'auto',
        }).json()
        self.assertEqual(payload['styles']['nav_bg'], '#3B5B57')
        self.assertGreaterEqual(payload['contrast']['text'], 4.5)

    def test_preview_endpoint_rejects_employee_role(self):
        org, owner = make_org_with_owner('PreviewRoleCo', 'previewroleco', 'preview_owner2')
        employee = User.objects.create_user('preview_employee', password='pw123456')
        OrganizationMembership.objects.create(
            user=employee, organization=org, role='employee'
        )
        c = Client()
        c.force_login(employee)
        self.assertEqual(c.get(reverse('organization_nav_preview')).status_code, 403)

    def test_restore_default_resets_navigation(self):
        org, user = make_org_with_owner('ResetCo', 'resetco', 'reset_owner')
        org.nav_style = 'custom'
        org.nav_bg_color = '#123456'
        org.nav_highlight_style = 'outline'
        org.nav_highlight_source = 'accent'
        org.nav_customized = True
        org.save()
        c = Client()
        c.force_login(user)
        response = c.post('/settings/branding/', {'action': 'restore_default'})
        self.assertEqual(response.status_code, 302)
        org.refresh_from_db()
        self.assertEqual(org.nav_style, 'clean')
        self.assertEqual(org.nav_highlight_style, 'rounded_pill')
        self.assertEqual(org.nav_highlight_source, 'auto')
        self.assertFalse(org.nav_customized)


class NavMigrationTests(TestCase):
    def test_legacy_rows_are_mapped_without_touching_explicit_custom_rows(self):
        migration = importlib.import_module('attendance.migrations.0036_nav_theme_v2')
        untouched = Organization.objects.create(
            name='Untouched', slug='untouched',
            nav_style='black', nav_bg_color='#0A0A0A',
            nav_highlight_style='pill', nav_highlight_source='auto',
            nav_highlight_color='#0A0A0A', setup_completed_steps=[],
        )
        old_clean = Organization.objects.create(
            name='Old Clean', slug='old-clean',
            nav_style='clean', nav_bg_color='#0A0A0A',
            nav_highlight_style='pill', nav_highlight_source='auto',
            nav_highlight_color='#0A0A0A', setup_completed_steps=[3],
        )
        custom = Organization.objects.create(
            name='Explicit Custom', slug='explicit-custom',
            nav_style='custom', nav_bg_color='#123456',
            nav_highlight_style='left_bar', nav_highlight_source='custom',
            nav_highlight_color='#ABCDEF', setup_completed_steps=[3],
        )

        migration.migrate_navigation(apps, None)

        untouched.refresh_from_db()
        old_clean.refresh_from_db()
        custom.refresh_from_db()
        self.assertEqual(untouched.nav_style, 'clean')
        self.assertEqual(untouched.nav_highlight_style, 'rounded_pill')
        self.assertFalse(untouched.nav_customized)
        self.assertEqual(old_clean.nav_style, 'clean')
        self.assertEqual(old_clean.nav_highlight_style, 'soft_pill')
        self.assertTrue(old_clean.nav_customized)
        self.assertEqual(custom.nav_style, 'custom')
        self.assertEqual(custom.nav_highlight_style, 'minimal')
        self.assertEqual(custom.nav_bg_color, '#123456')
        self.assertTrue(custom.nav_customized)
