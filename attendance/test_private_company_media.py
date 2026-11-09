import importlib
import tempfile
from pathlib import Path

from django.apps import apps
from django.contrib.auth.models import User
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from attendance.models import Category, Employee, EmployeeDocument, Organization, OrganizationMembership
from attendance.storage import PrivateLetterheadStorage


class PrivateCompanyLogoTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name='Logo Private A', slug='logo-private-a', setup_completed=True)
        self.org_b = Organization.objects.create(name='Logo Private B', slug='logo-private-b', setup_completed=True)
        self.owner_a = User.objects.create_user('logo_owner_a', password='pw123456')
        self.owner_b = User.objects.create_user('logo_owner_b', password='pw123456')
        OrganizationMembership.objects.create(user=self.owner_a, organization=self.org_a, role='owner')
        OrganizationMembership.objects.create(user=self.owner_b, organization=self.org_b, role='owner')
        self.logo_bytes = b'private test logo bytes'
        self.org_a.logo.save('logo.png', ContentFile(self.logo_bytes), save=True)

    def tearDown(self):
        if self.org_a.logo:
            self.org_a.logo.delete(save=False)
        super().tearDown()

    def test_logo_requires_login_and_same_organization_membership(self):
        url = reverse('organization_logo', args=[self.org_a.pk])
        anonymous = Client().get(url)
        self.assertEqual(anonymous.status_code, 302)

        other_company = Client()
        other_company.force_login(self.owner_b)
        self.assertEqual(other_company.get(url).status_code, 404)
        self.assertEqual(other_company.get('/media/' + self.org_a.logo.name).status_code, 404)

        company_member = Client()
        company_member.force_login(self.owner_a)
        response = company_member.get('/media/' + self.org_a.logo.name)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), self.logo_bytes)
        self.assertIn('private', response['Cache-Control'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_branding_page_uses_the_authenticated_logo_view(self):
        client = Client()
        client.force_login(self.owner_a)

        response = client.get(reverse('organization_branding'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('organization_logo', args=[self.org_a.pk]))

    def test_platform_logo_view_is_separate_from_company_membership(self):
        platform_user = User.objects.create_superuser('logo_platform', email='platform@example.com', password='pw123456')
        client = Client()
        client.force_login(platform_user)
        response = client.get(reverse('platform_organization_logo', args=[self.org_a.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), self.logo_bytes)


class PrivateUploadStorageMigrationTests(TestCase):
    def test_migration_moves_all_existing_upload_fields_without_losing_bytes(self):
        organization = Organization.objects.create(name='Storage migration', slug='storage-migration')
        category = Category.objects.create(organization=organization, name='Staff', code='STAFF')
        employee = Employee.objects.create(
            organization=organization, employee_id='M-001', category=category, first_name='Mia', last_name='Move',
            email='mia@migration.example', phone='08000000000', gender='FEMALE',
        )
        document = EmployeeDocument.objects.create(employee=employee, title='Private contract', file='employees/1/documents/M-001/contract.pdf')
        files = {
            'organizations/1/logo_legacy.png': b'logo-original',
            'organizations/999/logo_orphan.png': b'orphan-logo-original',
            'employees/1/profile_photos/profile-original.png': b'photo-original',
            document.file.name: b'contract-original',
        }
        organization.logo.name = 'organizations/1/logo_legacy.png'
        organization.save(update_fields=['logo'])
        employee.profile_photo.name = 'employees/1/profile_photos/profile-original.png'
        employee.save(update_fields=['profile_photo'])

        with tempfile.TemporaryDirectory() as temp_root:
            public_root = Path(temp_root) / 'media'
            private_root = Path(temp_root) / 'private'
            public = FileSystemStorage(location=str(public_root))
            for name, content in files.items():
                public.save(name, ContentFile(content))

            with override_settings(MEDIA_ROOT=public_root, PRIVATE_MEDIA_ROOT=private_root):
                migration = importlib.import_module('attendance.migrations.0047_organization_allow_staff_digidoc_and_more')
                migration.move_uploads_to_private(apps, None)
                private = PrivateLetterheadStorage()
                for name, content in files.items():
                    self.assertTrue(private.exists(name), name)
                    with private.open(name, 'rb') as uploaded:
                        self.assertEqual(uploaded.read(), content)
                    self.assertFalse(public.exists(name), name)


class ProjectUploadStorageInventoryTests(TestCase):
    def test_all_user_upload_fields_are_outside_public_media(self):
        from attendance.models import CompanyLetterhead, DigiDocImageAsset, PersonalLetterhead

        inventory = [
            Organization._meta.get_field('logo'),
            Employee._meta.get_field('profile_photo'),
            EmployeeDocument._meta.get_field('file'),
            CompanyLetterhead._meta.get_field('image'),
            CompanyLetterhead._meta.get_field('image_second'),
            DigiDocImageAsset._meta.get_field('image'),
            PersonalLetterhead._meta.get_field('image'),
        ]
        public_root = Path(settings.MEDIA_ROOT).resolve()
        for field in inventory:
            storage_root = Path(field.storage.location).resolve()
            self.assertNotEqual(storage_root, public_root, field.name)
            self.assertNotIn(public_root, storage_root.parents, field.name)
