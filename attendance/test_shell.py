import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from attendance.models import (
    Category,
    Employee,
    FavoritePage,
    Organization,
    OrganizationMembership,
)


def make_org_with_owner(name, slug, username):
    org = Organization.objects.create(name=name, slug=slug, setup_completed=True)
    user = User.objects.create_user(
        username, email=f'{username}@example.com', password='pw123456'
    )
    OrganizationMembership.objects.create(user=user, organization=org, role='owner')
    return org, user


def make_employee_user(org, username):
    user = User.objects.create_user(
        username, email=f'{username}@example.com', password='pw123456'
    )
    category = Category.objects.create(
        organization=org, name='Staff', code='STAFF'
    )
    Employee.objects.create(
        organization=org,
        user=user,
        category=category,
        first_name='Ada',
        last_name='Employee',
        email=f'{username}@example.com',
        phone='08000000000',
        gender='FEMALE',
    )
    OrganizationMembership.objects.create(
        user=user, organization=org, role='employee'
    )
    return user


class ShellDefaultTests(TestCase):
    def test_clean_shell_renders_for_default_organisation(self):
        org, user = make_org_with_owner('Clean Shell Co', 'clean-shell-co', 'clean_shell')
        self.assertEqual(org.nav_style, 'clean')
        client = Client()
        client.force_login(user)

        response = client.get('/dashboard/')

        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('class="app-sidebar"', html)
        self.assertIn('data-nav-active="rounded_pill"', html)
        self.assertIn('--nav-bg: #FFFFFF;', html)
        self.assertIn('--nav-active-bg: #111111;', html)
        self.assertIn('--nav-active-fg: #FFFFFF;', html)
        self.assertIn('--nav-active-icon-bg: #FFFFFF;', html)
        self.assertIn('Favorites', html)
        self.assertNotIn('side-block--recent', html)
        self.assertIn('data-recent-list', html)
        self.assertIn('Dashboards', html)
        self.assertIn('data-page-key="overview"', html)
        self.assertIn('aria-current="page"', html)
        self.assertIn('--nav-fg-muted: #6B6B6B;', html)
        self.assertNotIn('ByeWind', html)

    def test_saved_classic_black_is_preserved(self):
        org, user = make_org_with_owner('Black Shell Co', 'black-shell-co', 'black_shell')
        org.nav_style = 'black'
        org.save(update_fields=['nav_style'])
        client = Client()
        client.force_login(user)

        html = client.get('/dashboard/').content.decode('utf-8')

        self.assertIn('--nav-bg: #0A0A0A;', html)
        self.assertIn('--nav-pill-bg: #FFFFFF;', html)

    def test_recent_storage_key_is_per_organisation(self):
        org_a, user = make_org_with_owner('Recent A', 'recent-a', 'recent_owner')
        org_b = Organization.objects.create(
            name='Recent B', slug='recent-b', setup_completed=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=org_b, role='owner'
        )
        client = Client()
        client.force_login(user)

        html_a = client.get('/dashboard/').content.decode('utf-8')
        self.assertIn(f'data-recent-key="digi02hr:recent:{org_a.pk}"', html_a)

        session = client.session
        session['active_organization_id'] = org_b.pk
        session.save()
        html_b = client.get('/dashboard/').content.decode('utf-8')
        self.assertIn(f'data-recent-key="digi02hr:recent:{org_b.pk}"', html_b)
        self.assertNotIn(f'data-recent-key="digi02hr:recent:{org_a.pk}"', html_b)


class ShellRoleTests(TestCase):
    def test_employee_only_user_gets_self_service_navigation(self):
        org = Organization.objects.create(
            name='Self Service Co', slug='self-service-co', setup_completed=True
        )
        user = make_employee_user(org, 'self_service_user')
        client = Client()
        client.force_login(user)

        html = client.get('/me/').content.decode('utf-8')

        self.assertIn('My workspace', html)
        self.assertIn('app-nav__label">My dashboard', html)
        self.assertNotIn('app-nav__label">Employees', html)
        self.assertNotIn('app-nav__label">Payroll runs', html)

    def test_hr_user_gets_hr_navigation(self):
        org, user = make_org_with_owner('Hr Shell Co', 'hr-shell-co', 'hr_shell')
        client = Client()
        client.force_login(user)

        html = client.get('/dashboard/').content.decode('utf-8')

        self.assertIn('app-nav__label">Employees', html)
        self.assertIn('app-nav__label">Payroll runs', html)
        self.assertIn('app-nav__label">Company branding', html)


class FavoritePageTests(TestCase):
    def test_toggle_favorite_adds_and_removes(self):
        org, user = make_org_with_owner('Fav Co', 'fav-co', 'fav_owner')
        client = Client()
        client.force_login(user)

        response = client.post(
            '/favorites/toggle/',
            {'page_key': 'employees'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['favorited'])
        self.assertTrue(
            FavoritePage.objects.filter(
                user=user, organization=org, page_key='employees'
            ).exists()
        )

        html = client.get('/dashboard/').content.decode('utf-8')
        self.assertIn('data-favorite-key="employees"', html)

        response = client.post(
            '/favorites/toggle/',
            {'page_key': 'employees'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['favorited'])
        self.assertFalse(
            FavoritePage.objects.filter(
                user=user, organization=org, page_key='employees'
            ).exists()
        )

    def test_favorites_are_isolated_per_organisation(self):
        org_a, user = make_org_with_owner('Fav A', 'fav-a', 'fav_isolation')
        org_b = Organization.objects.create(
            name='Fav B', slug='fav-b', setup_completed=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=org_b, role='owner'
        )
        client = Client()
        client.force_login(user)

        client.post(
            '/favorites/toggle/',
            {'page_key': 'employees'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(FavoritePage.objects.filter(user=user, organization=org_a).count(), 1)
        self.assertEqual(FavoritePage.objects.filter(user=user, organization=org_b).count(), 0)

        session = client.session
        session['active_organization_id'] = org_b.pk
        session.save()
        html = client.get('/dashboard/').content.decode('utf-8')
        self.assertNotIn('data-favorite-key="employees"', html)

    def test_invalid_page_key_is_rejected(self):
        org, user = make_org_with_owner('Fav Bad', 'fav-bad', 'fav_bad')
        client = Client()
        client.force_login(user)

        response = client.post(
            '/favorites/toggle/',
            {'page_key': 'not-a-real-page'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(FavoritePage.objects.filter(user=user).exists())

    def test_favorite_requires_login(self):
        response = Client().post('/favorites/toggle/', {'page_key': 'employees'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_toggle_removes_an_existing_favorite(self):
        org, user = make_org_with_owner('Fav Unique', 'fav-unique', 'fav_unique')
        FavoritePage.objects.create(user=user, organization=org, page_key='employees')
        client = Client()
        client.force_login(user)

        client.post(
            '/favorites/toggle/',
            {'page_key': 'employees'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(
            FavoritePage.objects.filter(
                user=user, organization=org, page_key='employees'
            ).count(),
            0,
        )


class GlobalSearchTests(TestCase):
    def test_search_returns_real_pages_for_hr(self):
        org, user = make_org_with_owner('Search Co', 'search-co', 'search_owner')
        client = Client()
        client.force_login(user)

        response = client.get('/search/', {'q': 'emp'})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        labels = [result['label'] for result in data['results']]
        self.assertIn('Employees', labels)
        self.assertLessEqual(len(data['results']), 8)
        for result in data['results']:
            self.assertTrue(result['url'].startswith('/'))

    def test_search_requires_two_characters(self):
        org, user = make_org_with_owner('Short Co', 'short-co', 'short_owner')
        client = Client()
        client.force_login(user)

        data = client.get('/search/', {'q': 'e'}).json()

        self.assertEqual(data['results'], [])
        self.assertEqual(data['min_length'], 2)

    def test_search_output_keeps_query_as_data(self):
        org, user = make_org_with_owner('Escape Co', 'escape-co', 'escape_owner')
        client = Client()
        client.force_login(user)

        response = client.get('/search/', {'q': '<script>alert(1)</script>'})
        payload = json.loads(response.content.decode('utf-8'))

        self.assertEqual(payload['query'], '<script>alert(1)</script>')
        self.assertEqual(payload['results'], [])

    def test_search_never_offers_hr_pages_to_employee_only_user(self):
        org = Organization.objects.create(
            name='Search Self', slug='search-self', setup_completed=True
        )
        user = make_employee_user(org, 'search_self')
        client = Client()
        client.force_login(user)

        data = client.get('/search/', {'q': 'employees'}).json()
        labels = [result['label'] for result in data['results']]

        self.assertNotIn('Employees', labels)
        self.assertNotIn('Payroll runs', labels)
        self.assertIn('My dashboard', [result['label'] for result in client.get('/search/', {'q': 'dashboard'}).json()['results']])

    def test_search_requires_login(self):
        response = Client().get('/search/', {'q': 'employees'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])
