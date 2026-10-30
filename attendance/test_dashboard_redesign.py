from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    AttendanceRecord,
    Category,
    Employee,
    Organization,
    OrganizationMembership,
    organization_today,
)
from .views import build_metric_trend


class DashboardRedesignTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name='Northwind Team', slug='northwind-team', setup_completed=True,
            dashboard_appearance='white', timezone='Africa/Lagos',
        )
        self.user = User.objects.create_user(
            username='northwind-hr', password='test-password', first_name='Ada',
        )
        OrganizationMembership.objects.create(
            user=self.user, organization=self.organization, role='owner', is_active=True,
        )
        category = Category.objects.create(
            organization=self.organization, name='Staff', code='STAFF',
            icon='bi-person', color='primary',
        )
        self.employee = Employee.objects.create(
            organization=self.organization, employee_id='NW-001', category=category,
            first_name='Mina', last_name='Okafor', email='mina@example.com',
            phone='08000000000', gender='FEMALE', hire_date=organization_today(self.organization),
            is_active=True,
        )
        check_in = timezone.make_aware(
            datetime.combine(organization_today(self.organization), time(8, 5)),
            ZoneInfo(self.organization.timezone),
        )
        AttendanceRecord.objects.create(
            organization=self.organization, employee=self.employee, check_in_time=check_in,
        )
        self.client.force_login(self.user)

    def test_dashboard_renders_live_metrics_and_selected_tenant_theme(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('data-dashboard-theme="white"', html)
        self.assertIn('<body class="rail"', html)
        self.assertIn('aria-label="Expand navigation"', html)
        self.assertIn('material-symbols-rounded', html)
        self.assertIn('Mina Okafor', html)
        self.assertIn('Attendance this week', html)
        self.assertIn('Department check-in', html)
        self.assertIn('overview-welcome__portrait', html)
        self.assertEqual(response.context['total_employees'], 1)
        self.assertEqual(response.context['present_count'], 1)
        self.assertEqual(response.context['late_count'], 0)
        self.assertEqual(response.context['no_checkin_count'], 0)
        checkin_kpi = response.context['dashboard_kpis'][1]
        self.assertIn('1 total', checkin_kpi['trend']['summary'])
        self.assertEqual(len(checkin_kpi['trend']['points']), 7)
        self.assertIn('Employees present · 7 days', html)

    def test_metric_trend_renders_measured_zero_activity(self):
        trend = build_metric_trend([], end_date=organization_today(self.organization))

        self.assertIsNotNone(trend)
        self.assertEqual([point['value'] for point in trend['points']], [0] * 7)
        self.assertIn('0 total', trend['summary'])

    def test_category_kpis_render_shared_historical_trends(self):
        response = self.client.get(reverse('category_dashboard', kwargs={'code': 'STAFF'}))

        self.assertEqual(response.status_code, 200)
        self.assertIn('Employees present - 7 days', response.content.decode())
        self.assertIn('Peak 0', response.content.decode())

    def test_manager_kpi_pages_render_the_shared_trend_component(self):
        for route_name in ('manager_dashboard', 'manager_team'):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertIn('Employees present - 7 days', response.content.decode())

