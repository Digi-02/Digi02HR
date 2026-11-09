import json
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from attendance.models import AuditLog, DigiDocDocument, Organization, OrganizationMembership, PersonalLetterhead, PersonalLetterheadUpload


def png_upload(name='personal.png', color='#235789'):
    buffer = BytesIO()
    Image.new('RGB', (210, 297), color).save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT='personal-test-media', PRIVATE_MEDIA_ROOT='personal-test-private')
class PersonalLetterheadTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Personal Letterhead Co', slug='personal-letterhead-co', setup_completed=True)
        self.hr = User.objects.create_user('personal_hr', password='pw123456')
        OrganizationMembership.objects.create(user=self.hr, organization=self.org, role='hr_admin')
        self.staff = User.objects.create_user('personal_staff', password='pw123456')
        self.staff_membership = OrganizationMembership.objects.create(user=self.staff, organization=self.org, role='employee')
        self.hr_client = Client()
        self.hr_client.force_login(self.hr)
        self.staff_client = Client()
        self.staff_client.force_login(self.staff)

    def tearDown(self):
        for letter in PersonalLetterhead.objects.all():
            if letter.image:
                letter.image.delete(save=False)
        super().tearDown()

    def upload(self, client=None, label='Personal stationery'):
        return (client or self.staff_client).post(reverse('my_letterhead'), {
            'action': 'upload', 'label': label, 'letterhead_file': png_upload(),
        })

    def test_staff_cannot_change_company_branding_or_colours(self):
        original = self.org.brand_color
        response = self.staff_client.post(reverse('organization_branding'), {
            'name': self.org.name, 'brand_color': '#FF0000', 'timezone': self.org.timezone,
        })
        self.assertEqual(response.status_code, 403)
        self.org.refresh_from_db()
        self.assertEqual(self.org.brand_color, original)

    def test_personal_letterhead_access_is_off_until_hr_grants_it(self):
        self.assertEqual(self.staff_client.get(reverse('my_letterhead')).status_code, 403)
        denied_upload = self.upload()
        self.assertEqual(denied_upload.status_code, 403)
        self.hr_client.post(reverse('personal_letterhead_admin'), {
            'action': 'grant', 'membership_id': self.staff_membership.pk,
        })
        self.staff_membership.refresh_from_db()
        self.assertTrue(self.staff_membership.can_use_personal_letterhead)
        self.assertEqual(self.staff_client.get(reverse('my_letterhead')).status_code, 200)

    def test_staff_can_upload_view_delete_and_use_own_private_letterhead(self):
        self.staff_membership.can_use_personal_letterhead = True
        self.staff_membership.save(update_fields=['can_use_personal_letterhead'])
        self.assertEqual(self.upload().status_code, 302)
        letter = PersonalLetterhead.objects.get(user=self.staff)
        self.assertIn(f'personal_letterheads/{self.org.pk}/{self.staff.pk}/', letter.image.name)
        self.assertNotIn('personal-test-media', str(letter.image.path))
        image = self.staff_client.get(reverse('personal_letterhead_image', args=[letter.pk]))
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image['Content-Type'], 'image/png')
        image.close()
        document = DigiDocDocument.objects.create(organization=self.org, created_by=self.staff, title='Personal letterhead proof', content_json={'type': 'doc', 'content': [{'type': 'paragraph', 'content': []}]})
        response = self.staff_client.post(reverse('digidoc_save', args=[document.pk]), data=json.dumps({
            'title': document.title, 'content': document.content_json, 'letterhead_enabled': True,
            'letterhead_page_mode': 'every', 'letterhead_first_slot': '1', 'letterhead_other_slot': '1',
            'letterhead_source': 'personal', 'personal_letterhead_id': str(letter.pk), 'version': 1,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        document.refresh_from_db()
        self.assertEqual(document.letterhead_source, 'personal')
        self.assertIn('1', document.personal_letterhead_snapshot)
        self.staff_client.post(reverse('my_letterhead'), {'action': 'delete', 'letterhead_id': str(letter.pk)})
        from attendance.digidoc import _render_pdf_isolated
        self.assertTrue(_render_pdf_isolated(document).startswith(b'%PDF-'))
        self.assertTrue(AuditLog.objects.filter(action='digidoc.personal_letterhead_deleted').exists())

    def test_staff_cannot_view_or_use_another_persons_letterhead(self):
        self.staff_membership.can_use_personal_letterhead = True
        self.staff_membership.save(update_fields=['can_use_personal_letterhead'])
        self.upload()
        other = User.objects.create_user('personal_staff_other', password='pw123456')
        other_membership = OrganizationMembership.objects.create(user=other, organization=self.org, role='employee', can_use_personal_letterhead=True)
        other_client = Client()
        other_client.force_login(other)
        letter = PersonalLetterhead.objects.get(user=self.staff)
        self.assertEqual(other_client.get(reverse('personal_letterhead_image', args=[letter.pk])).status_code, 403)
        self.assertNotContains(other_client.get(reverse('my_letterhead')), 'Personal stationery')
        document = DigiDocDocument.objects.create(organization=self.org, created_by=other, title='No cross-use', content_json={'type': 'doc', 'content': []})
        response = other_client.post(reverse('digidoc_save', args=[document.pk]), data=json.dumps({
            'title': document.title, 'content': document.content_json, 'letterhead_enabled': True,
            'letterhead_page_mode': 'every', 'letterhead_first_slot': '1', 'letterhead_other_slot': '1',
            'letterhead_source': 'personal', 'personal_letterhead_id': str(letter.pk), 'version': 1,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(other_membership.can_use_personal_letterhead)

    def test_hr_can_bulk_enable_default_and_manage_private_previews(self):
        response = self.hr_client.post(reverse('personal_letterhead_admin'), {'action': 'bulk_enable'})
        self.assertEqual(response.status_code, 302)
        self.staff_membership.refresh_from_db()
        self.assertTrue(self.staff_membership.can_use_personal_letterhead)
        self.hr_client.post(reverse('personal_letterhead_admin'), {'action': 'default', 'enabled': 'true'})
        self.org.refresh_from_db()
        self.assertTrue(self.org.personal_letterhead_default_enabled)
        new_staff = User.objects.create_user('default_grant_staff', password='pw123456')
        inherited = OrganizationMembership.objects.create(user=new_staff, organization=self.org, role='employee')
        self.assertTrue(inherited.can_use_personal_letterhead)
        self.upload()
        letter = PersonalLetterhead.objects.get(user=self.staff)
        response = self.hr_client.get(reverse('personal_letterhead_image', args=[letter.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertTrue(AuditLog.objects.filter(action='digidoc.personal_letterhead_bulk_enabled').exists())
        self.assertTrue(AuditLog.objects.filter(action='digidoc.personal_letterhead_default_changed').exists())

    def test_five_letterhead_limit_and_private_image_route_need_active_membership(self):
        self.staff_membership.can_use_personal_letterhead = True
        self.staff_membership.save(update_fields=['can_use_personal_letterhead'])
        for index in range(5):
            self.assertEqual(self.upload(label=f'Letterhead {index}').status_code, 302)
        self.assertEqual(self.upload(label='Sixth').status_code, 302)
        self.assertEqual(PersonalLetterhead.objects.filter(user=self.staff).count(), 5)
        self.staff_membership.is_active = False
        self.staff_membership.save(update_fields=['is_active'])
        letter = PersonalLetterhead.objects.filter(user=self.staff).first()
        response = self.staff_client.get(reverse('personal_letterhead_image', args=[letter.pk]), follow=True)
        self.assertEqual(response.status_code, 403)

    def test_personal_upload_rate_limit_and_real_image_validation(self):
        self.staff_membership.can_use_personal_letterhead = True
        self.staff_membership.save(update_fields=['can_use_personal_letterhead'])
        for _ in range(10):
            PersonalLetterheadUpload.objects.create(organization=self.org, user=self.staff)
        self.assertEqual(self.upload().status_code, 429)
        PersonalLetterheadUpload.objects.filter(organization=self.org, user=self.staff).delete()
        bad_upload = SimpleUploadedFile('fake.png', b'not really an image', content_type='image/png')
        response = self.staff_client.post(reverse('my_letterhead'), {'action': 'upload', 'letterhead_file': bad_upload})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PersonalLetterhead.objects.filter(user=self.staff).count(), 0)

    def test_hr_can_list_thumbnail_delete_and_revoke_personal_letterheads(self):
        self.staff_membership.can_use_personal_letterhead = True
        self.staff_membership.save(update_fields=['can_use_personal_letterhead'])
        self.upload()
        letter = PersonalLetterhead.objects.get(user=self.staff)
        page = self.hr_client.get(reverse('personal_letterhead_admin'))
        self.assertContains(page, 'Personal Letterheads')
        self.assertContains(page, reverse('personal_letterhead_image', args=[letter.pk]))
        preview = self.hr_client.get(reverse('personal_letterhead_image', args=[letter.pk]))
        self.assertEqual(preview.status_code, 200)
        preview.close()
        self.hr_client.post(reverse('personal_letterhead_admin'), {'action': 'revoke_access', 'membership_id': self.staff_membership.pk})
        self.staff_membership.refresh_from_db()
        self.assertFalse(self.staff_membership.can_use_personal_letterhead)
        self.assertEqual(self.staff_client.get(reverse('my_letterhead')).status_code, 403)
        self.hr_client.post(reverse('personal_letterhead_admin'), {'action': 'delete_letterhead', 'letterhead_id': str(letter.pk)})
        self.assertFalse(PersonalLetterhead.objects.filter(pk=letter.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='digidoc.personal_letterhead_revoke_access').exists())

    def test_editor_insert_has_company_and_personal_letterhead_groups(self):
        self.staff_membership.can_use_personal_letterhead = True
        self.staff_membership.save(update_fields=['can_use_personal_letterhead'])
        self.upload()
        document = DigiDocDocument.objects.create(organization=self.org, created_by=self.staff, title='Insert groups', content_json={'type': 'doc', 'content': []})
        response = self.staff_client.get(reverse('digidoc_editor', args=[document.pk]))
        self.assertContains(response, 'Company letterheads')
        self.assertContains(response, 'My letterheads')
        self.assertNotContains(response, 'Personal brand colour')
        self.assertNotContains(response, 'Primary colour')
        self.assertNotContains(response, 'Secondary colour')
