import re

from django.contrib.auth.models import User
from django.test import Client, TestCase

from attendance.models import (
    AccessRequest,
    Organization,
    OrganizationMembership,
    PlatformAuditLog,
)

PLATFORM_URLS = [
    '/platform/',
    '/platform/companies/',
    '/platform/companies/create/',
    '/platform/requests/',
    '/platform/audit/',
    '/platform/settings/',
]


def make_owner(username='biz_owner', org_name='BizCo', slug='bizco'):
    org = Organization.objects.create(name=org_name, slug=slug)
    user = User.objects.create_user(username, email=f'{username}@example.com', password='pw123456')
    OrganizationMembership.objects.create(user=user, organization=org, role='owner')
    return user, org


class PlatformAccessTests(TestCase):
    def test_anonymous_gets_redirected_to_login(self):
        c = Client()
        for url in PLATFORM_URLS:
            resp = c.get(url)
            # login_required redirects; must never leak content
            self.assertIn(resp.status_code, (302, 404), url)

    def test_company_owner_gets_404_everywhere(self):
        user, _ = make_owner()
        c = Client()
        c.force_login(user)
        for url in PLATFORM_URLS:
            self.assertEqual(c.get(url).status_code, 404, url)

    def test_superuser_gets_in(self):
        User.objects.create_superuser('platadmin', email='p@example.com', password='pw123456')
        c = Client()
        c.force_login(User.objects.get(username='platadmin'))
        for url in PLATFORM_URLS:
            self.assertEqual(c.get(url).status_code, 200, url)


class SuspensionTests(TestCase):
    def test_suspended_company_cannot_log_in(self):
        user, org = make_owner()
        org.is_suspended = True
        org.save(update_fields=['is_suspended'])
        c = Client()
        resp = c.post('/login/', {'username': 'biz_owner', 'password': 'pw123456'})
        self.assertEqual(resp.status_code, 403)
        self.assertIn(b'suspended', resp.content.lower())

    def test_suspended_session_blocked_from_app(self):
        user, org = make_owner()
        c = Client()
        c.force_login(user)
        self.assertEqual(c.get('/dashboard/').status_code, 200)
        org.is_suspended = True
        org.save(update_fields=['is_suspended'])
        resp = c.get('/dashboard/')
        self.assertEqual(resp.status_code, 403)


class AccessRequestTests(TestCase):
    def test_anonymous_can_submit(self):
        c = Client()
        resp = c.post('/welcome/contact/', {
            'name': 'Ada', 'email': 'ada@example.com', 'message': 'We need HR software.',
            'company': 'Ada Ltd', 'phone': '0801', 'team_size': '20', 'website': '',
        })
        self.assertEqual(resp.status_code, 302)
        item = AccessRequest.objects.get(email='ada@example.com')
        self.assertEqual(item.company_name, 'Ada Ltd')
        self.assertEqual(item.status, 'new')

    def test_honeypot_silently_dropped(self):
        c = Client()
        c.post('/welcome/contact/', {
            'name': 'Bot', 'email': 'bot@example.com', 'message': 'spam', 'website': 'http://spam.example',
        })
        self.assertFalse(AccessRequest.objects.filter(email='bot@example.com').exists())

    def test_rate_limited(self):
        c = Client()
        for i in range(7):
            c.post('/welcome/contact/', {
                'name': f'P{i}', 'email': f'p{i}@example.com', 'message': 'hello there friend',
            }, REMOTE_ADDR='10.9.9.9')
        count = AccessRequest.objects.filter(email__startswith='p', email__endswith='@example.com').count()
        self.assertLessEqual(count, 5)


class CompanyCreateTests(TestCase):
    def test_create_sends_invite_and_owner_can_set_password(self):
        User.objects.create_superuser('platadmin', email='p@example.com', password='pw123456')
        c = Client()
        c.force_login(User.objects.get(username='platadmin'))
        from django.core import mail
        resp = c.post('/platform/companies/create/', {
            'name': 'NewCo', 'owner_name': 'Ngozi Eze', 'owner_email': 'ngozi@newco.example',
        })
        self.assertEqual(resp.status_code, 302)
        org = Organization.objects.get(name='NewCo')
        owner = User.objects.get(email='ngozi@newco.example')
        self.assertTrue(OrganizationMembership.objects.filter(
            user=owner, organization=org, role='owner').exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('ngozi@newco.example', mail.outbox[0].to)
        self.assertTrue(PlatformAuditLog.objects.filter(action='company.created', organization=org).exists())
        # Owner follows the invite link and sets a password
        m = re.search(r'/reset/(\S+)/(\S+)/', mail.outbox[0].body)
        self.assertIsNotNone(m)
        uidb64, token = m.group(1), m.group(2)
        anon = Client()
        set_url = f'/reset/{uidb64}/{token}/'
        resp = anon.get(set_url)
        self.assertEqual(resp.status_code, 302)
        set_url = resp['Location']
        self.assertEqual(anon.get(set_url).status_code, 200)
        resp = anon.post(set_url, {'new_password1': 'StrongPass999', 'new_password2': 'StrongPass999'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(anon.login(username=owner.username, password='StrongPass999'))
