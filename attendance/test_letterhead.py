from io import BytesIO

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from PIL import Image
from pypdf import PdfReader

from attendance.letterhead import render_sample_pdf, sanitize_letterhead
from attendance.models import (
    AuditLog,
    CompanyLetterhead,
    CompanyLetterheadUpload,
    Organization,
    OrganizationMembership,
)


def image_bytes(fmt='PNG', size=(210, 297), color='navy', suffix=b''):
    buffer = BytesIO()
    Image.new('RGB', size, color=color).save(buffer, format=fmt)
    return buffer.getvalue() + suffix


def setup_owner(org_name='LetterCo', username='letter_owner'):
    org = Organization.objects.create(name=org_name, slug=org_name.lower(), setup_completed=True)
    user = User.objects.create_user(username, password='pw123456')
    OrganizationMembership.objects.create(user=user, organization=org, role='owner')
    return org, user


@override_settings(MEDIA_ROOT='test-media', PRIVATE_MEDIA_ROOT='test-private-media')
class LetterheadSecurityTests(TestCase):
    def tearDown(self):
        for asset in CompanyLetterhead.objects.all():
            if asset.image:
                asset.image.delete(save=False)
        super().tearDown()

    def test_branding_page_has_live_a4_guides_and_upload_controls(self):
        _, user = setup_owner('UiCo', 'ui_owner')
        client = Client()
        client.force_login(user)
        response = client.get('/settings/branding/')
        self.assertEqual(response.status_code, 200)
        page = response.content.decode('utf-8')
        self.assertIn('id="letterheadPage"', page)
        self.assertIn('data-width-mm="210" data-height-mm="297"', page)
        self.assertIn('name="letterhead_file"', page)
        self.assertIn('Recommended size: 2480 × 3508 px', page)
        self.assertIn('aria-label="Top page margin"', page)
        self.assertIn('letterhead-margin-input', page)
        self.assertIn('Open-source notices', page)
        notices = client.get('/open-source-notices/')
        self.assertEqual(notices.status_code, 200)
        self.assertContains(notices, 'ReportLab')
        self.assertContains(notices, 'BSD')

    def test_branding_page_screenshots_desktop_and_mobile(self):
        from pathlib import Path
        from playwright.sync_api import sync_playwright

        _, user = setup_owner('CaptureCo', 'capture_owner')
        client = Client()
        client.force_login(user)
        page_html = client.get('/settings/branding/').content.decode('utf-8')
        output = Path('screenshots/digidoc-phase1')
        output.mkdir(parents=True, exist_ok=True)
        design_css = Path('static/attendance/design-system.css').read_text(encoding='utf-8')
        console_errors = []
        page_errors = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            page.on('console', lambda message: console_errors.append(message.text) if message.type == 'error' else None)
            page.on('pageerror', lambda error: page_errors.append(str(error)))
            page.set_content(page_html, wait_until='domcontentloaded')
            page.add_style_tag(content=design_css)
            page.wait_for_timeout(400)
            page.screenshot(path=str(output / 'branding-1440.png'), full_page=True)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 1440)
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(200)
            page.screenshot(path=str(output / 'branding-390.png'), full_page=True)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
            page.locator('#letterheadFile').set_input_files({
                'name': 'wide.png', 'mimeType': 'image/png', 'buffer': image_bytes(size=(500, 100)),
            })
            page.locator('#letterheadRatioNotice').wait_for(state='visible')
            self.assertEqual(page.locator('#letterheadUploadPreviewImage').evaluate('(img) => getComputedStyle(img).objectFit'), 'contain')
            page.locator('#letterheadScaleMode').select_option('fill')
            self.assertEqual(page.locator('#letterheadUploadPreviewImage').evaluate('(img) => getComputedStyle(img).objectFit'), 'cover')
            page.locator('#letterheadFile').set_input_files({
                'name': 'a4.png', 'mimeType': 'image/png', 'buffer': image_bytes(),
            })
            page.locator('#letterheadRatioNotice').wait_for(state='hidden')
            browser.close()
        self.assertEqual(console_errors, [])
        self.assertEqual(page_errors, [])

    def test_accepts_real_image_despite_wrong_content_type_and_ignores_appended_payload(self):
        content = image_bytes(suffix=b'PK\x03\x04<script>payload</script>')
        upload = SimpleUploadedFile('../../shell.php.png', content, content_type='text/html')
        cleaned, detected, extension, width, height = sanitize_letterhead(upload)
        self.assertEqual((detected, extension, width, height), ('png', 'png', 210, 297))
        self.assertNotIn(b'payload', cleaned)
        self.assertNotIn(b'PK\x03\x04', cleaned)
        with Image.open(BytesIO(cleaned)) as result:
            self.assertEqual(result.format, 'PNG')

    def test_rejects_non_png_jpeg_signatures_renamed_to_png(self):
        attacks = [
            b'PK\x03\x04xlsx archive', b'PK\x03\x04zip archive',
            b'PK\x03\x04docx archive', b'<html>bad</html>', b'%PDF-1.7',
            b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
            b'GIF89a', b'RIFF....WEBP', b'MZ\x90\x00',
        ]
        for index, data in enumerate(attacks):
            with self.subTest(index=index):
                upload = SimpleUploadedFile('renamed.png', data, content_type='image/png')
                with self.assertRaises(Exception):
                    sanitize_letterhead(upload)

    def test_rejects_oversize_truncated_and_corrupt_images(self):
        too_big = SimpleUploadedFile('large.jpg', b'\xff\xd8\xff' + b'x' * (8 * 1024 * 1024), content_type='image/jpeg')
        with self.assertRaises(Exception):
            sanitize_letterhead(too_big)
        for data in (b'\x89PNG\r\n\x1a\ntruncated', b'\x89PNG\r\n\x1a\nnot-an-image'):
            with self.subTest(data=data[:12]):
                with self.assertRaises(Exception):
                    sanitize_letterhead(SimpleUploadedFile('broken.png', data))

    def test_dimension_limit_is_checked_before_full_decode(self):
        large = image_bytes(size=(5001, 5000))
        with self.assertRaises(Exception):
            sanitize_letterhead(SimpleUploadedFile('wide.png', large))

    def test_reencoded_jpeg_strips_exif_and_client_name_never_reaches_storage(self):
        org, user = setup_owner('ExifCo', 'exif_owner')
        client = Client()
        client.force_login(user)
        jpeg = Image.new('RGB', (210, 297), 'white')
        exif = Image.Exif()
        exif[270] = 'sensitive GPS payload'
        buf = BytesIO()
        jpeg.save(buf, format='JPEG', exif=exif)
        client.post('/settings/branding/', {
            'action': 'letterhead_upload', 'letterhead_file': SimpleUploadedFile(
                '../../report.jpg', buf.getvalue(), content_type='image/jpeg'),
            'letterhead_scale_mode': 'fit', 'letterhead_default_page_mode': 'first',
            'letterhead_margin_top_mm': '40', 'letterhead_margin_bottom_mm': '30',
            'letterhead_margin_left_mm': '20', 'letterhead_margin_right_mm': '20',
        })
        asset = CompanyLetterhead.objects.get(organization=org)
        audit = AuditLog.objects.get(action='branding.letterhead_uploaded')
        self.assertEqual(audit.metadata, {'format': 'jpeg', 'width': 210, 'height': 297})
        self.assertRegex(asset.image.name.rsplit('/', 1)[-1], r'^[0-9a-f]{32}\.jpg$')
        with asset.image.open('rb') as fh:
            stored = Image.open(fh)
            self.assertEqual(stored.format, 'JPEG')
            self.assertEqual(dict(stored.getexif()), {})
        self.assertFalse(CompanyLetterheadUpload.objects.filter(user=user).count() > 1)

    def test_authentication_tenant_scope_and_secure_image_headers(self):
        org_a, owner_a = setup_owner('TenantA', 'owner_a')
        org_b, owner_b = setup_owner('TenantB', 'owner_b')
        org_a.letterhead = CompanyLetterhead.objects.create(
            organization=org_a, image_format='png', image_width=210, image_height=297,
        )
        from django.core.files.base import ContentFile
        org_a.letterhead.image.save('ignored.png', ContentFile(image_bytes()), save=True)

        anonymous = Client().get('/settings/branding/letterhead/image/')
        self.assertIn(anonymous.status_code, (302, 404))
        client = Client()
        client.force_login(owner_b)
        response = client.get('/settings/branding/letterhead/image/?asset=company-a-uuid.png')
        self.assertEqual(response.status_code, 404)
        client.force_login(owner_a)
        response = client.get('/settings/branding/letterhead/image/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        response.close()

    def test_upload_rate_limit_and_csrf(self):
        org, user = setup_owner('RateCo', 'rate_owner')
        for _ in range(10):
            CompanyLetterheadUpload.objects.create(organization=org, user=user)
        client = Client()
        client.force_login(user)
        response = client.post('/settings/branding/', {'action': 'letterhead_upload'})
        self.assertEqual(response.status_code, 429)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)
        rejected = csrf_client.post('/settings/branding/', {'action': 'letterhead_remove'})
        self.assertEqual(rejected.status_code, 403)

    def test_sample_pdf_has_two_a4_pages_and_first_page_only_variant(self):
        org, _ = setup_owner('PdfCo', 'pdf_owner')
        asset = CompanyLetterhead.objects.create(
            organization=org, image_format='png', image_width=210, image_height=297,
            default_page_mode='first', margin_top_mm=40, margin_bottom_mm=30,
            margin_left_mm=20, margin_right_mm=20,
        )
        from django.core.files.base import ContentFile
        asset.image.save('private.png', ContentFile(image_bytes()), save=True)
        result = PdfReader(BytesIO(render_sample_pdf(asset, 'first')))
        self.assertEqual(len(result.pages), 2)
        self.assertAlmostEqual(float(result.pages[0].mediabox.width), 595.2756, places=1)
        self.assertAlmostEqual(float(result.pages[0].mediabox.height), 841.8898, places=1)
        self.assertTrue(result.pages[0].get('/Resources').get('/XObject'))
        self.assertFalse(result.pages[1].get('/Resources').get('/XObject'))
        self.assertEqual(result.metadata.title, 'DigiDoc letterhead sample')
        self.assertFalse(result.metadata.author)

    def test_sample_pdf_download_is_private_and_audited(self):
        org, user = setup_owner('AuditPdfCo', 'audit_pdf_owner')
        asset = CompanyLetterhead.objects.create(
            organization=org, image_format='png', image_width=210, image_height=297,
        )
        from django.core.files.base import ContentFile
        asset.image.save('private.png', ContentFile(image_bytes()), save=True)
        client = Client()
        client.force_login(user)
        response = client.get('/settings/branding/letterhead/sample.pdf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="digidoc-letterhead-sample.pdf"')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        generated_pdf = PdfReader(BytesIO(response.content))
        self.assertEqual(len(generated_pdf.pages), 2)
        self.assertEqual(generated_pdf.metadata.title, 'DigiDoc letterhead sample')
        audit = AuditLog.objects.get(action='branding.letterhead_sample_downloaded')
        self.assertEqual(audit.metadata, {'format': 'pdf', 'page_mode': 'every'})

    def test_sample_pdf_rate_and_concurrency_limits(self):
        org, user = setup_owner('LimitedPdfCo', 'limited_pdf_owner')
        asset = CompanyLetterhead.objects.create(
            organization=org, image_format='png', image_width=210, image_height=297,
        )
        from django.core.files.base import ContentFile
        asset.image.save('private.png', ContentFile(image_bytes()), save=True)
        client = Client()
        client.force_login(user)
        for _ in range(10):
            AuditLog.objects.create(
                organization=org, actor=user, area='organization',
                action='branding.letterhead_sample_downloaded', summary='sample',
            )
        self.assertEqual(client.get('/settings/branding/letterhead/sample.pdf').status_code, 429)
        AuditLog.objects.filter(actor=user, action='branding.letterhead_sample_downloaded').delete()
        cache.add('digidoc:letterhead-sample:slot:0', 'busy-0', timeout=30)
        cache.add('digidoc:letterhead-sample:slot:1', 'busy-1', timeout=30)
        try:
            self.assertEqual(client.get('/settings/branding/letterhead/sample.pdf').status_code, 429)
        finally:
            cache.delete('digidoc:letterhead-sample:slot:0')
            cache.delete('digidoc:letterhead-sample:slot:1')

    def test_every_page_and_wide_image_fit_css_settings(self):
        from attendance.letterhead import _page_background_settings, letterhead_page_css
        asset = CompanyLetterhead(
            image_format='png', image_width=1200, image_height=600,
            margin_top_mm=25, margin_bottom_mm=35, margin_left_mm=18, margin_right_mm=22,
            scale_mode='fit',
        )
        stylesheet = letterhead_page_css(asset, 'every')
        self.assertIn('size: A4', stylesheet)
        self.assertIn('margin: 25mm 22mm 35mm 18mm', stylesheet)
        self.assertEqual(_page_background_settings(stylesheet, 1), (True, 'contain'))
        self.assertEqual(_page_background_settings(stylesheet, 2), (True, 'contain'))
        asset.scale_mode = 'fill'
        first_only = letterhead_page_css(asset, 'first')
        self.assertEqual(_page_background_settings(first_only, 1), (True, 'cover'))
        self.assertEqual(_page_background_settings(first_only, 2), (False, 'contain'))
