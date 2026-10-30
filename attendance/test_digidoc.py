from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from attendance.digidoc import _render_pdf_isolated, validate_document_json
from attendance.models import CompanyLetterhead, DigiDocDocument, DigiDocImageAsset, Organization, OrganizationMembership
from attendance.shell import build_navigation
from PIL import Image
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZipFile
from xml.etree import ElementTree


class DigiDocPhaseTwoTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="DigiDoc Test", slug="digidoc-test", setup_completed=True)
        self.owner = User.objects.create_user("digidoc_owner", password="test-pass-123")
        OrganizationMembership.objects.create(user=self.owner, organization=self.organization, role="owner")
        self.client = Client()
        self.client.force_login(self.owner)

    def tearDown(self):
        for letterhead in CompanyLetterhead.objects.all():
            if letterhead.image:
                letterhead.image.delete(save=False)
        for asset in DigiDocImageAsset.objects.all():
            if asset.image:
                asset.image.delete(save=False)
        super().tearDown()

    def test_nav_registry_places_digidoc_in_people_for_hr_roles(self):
        sections, pages = build_navigation(self.owner, self.organization)
        people = next(section for section in sections if section["key"] == "people")
        item = next(item for item in people["items"] if item["key"] == "digidoc")
        self.assertEqual(item["label"], "DigiDoc")
        self.assertEqual(item["url"], reverse("digidoc_list"))
        self.assertEqual(item["icon"], "bi-journal-pen")
        self.assertEqual(pages["digidoc"]["group"], "People")

    def test_editor_uses_all_configured_navigation_presets_and_highlights(self):
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        for style, _label in Organization.NAV_STYLE_CHOICES:
            for highlight, _highlight_label in Organization.NAV_HIGHLIGHT_STYLE_CHOICES:
                with self.subTest(style=style, highlight=highlight):
                    self.organization.nav_style = style
                    self.organization.nav_highlight_style = highlight
                    self.organization.save(update_fields=["nav_style", "nav_highlight_style"])
                    response = self.client.get(reverse("digidoc_editor", args=[document.pk]))
                    self.assertEqual(response.status_code, 200)
                    markup = response.content.decode("utf-8")
                    self.assertIn(f'data-nav-appearance="{style}"', markup)
                    self.assertIn(f'data-nav-active="{highlight}"', markup)
                    self.assertIn("--nav-bg:", markup)

    def test_editor_has_security_headers_and_active_navigation(self):
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        response = self.client.get(reverse("digidoc_editor", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertContains(response, 'data-label="DigiDoc"')
        self.assertContains(response, 'aria-current="page"')

    def test_people_roles_without_documents_access_are_denied(self):
        user = User.objects.create_user("digidoc_manager", password="test-pass-123")
        OrganizationMembership.objects.create(user=user, organization=self.organization, role="manager")
        client = Client()
        client.force_login(user)
        response = client.get(reverse("digidoc_list"))
        self.assertEqual(response.status_code, 403)
        sections, pages = build_navigation(user, self.organization)
        self.assertNotIn("digidoc", pages)

    def test_allow_list_accepts_safe_content_and_rejects_unknown_nodes_attrs_and_urls(self):
        clean = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello", "marks": [{"type": "bold"}]}]}]}
        self.assertEqual(validate_document_json(clean), clean)
        attacks = [
            {"type": "doc", "content": [{"type": "script", "content": []}]},
            {"type": "doc", "content": [{"type": "paragraph", "onload": "alert(1)", "content": []}]},
            {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "bad", "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}]}]}]},
            {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "image", "attrs": {"src": "https://example.com/a.png"}}]}]},
        ]
        for attack in attacks:
            with self.subTest(attack=attack), self.assertRaises(ValidationError):
                validate_document_json(attack)

    def test_allow_list_round_trips_safe_formatting_and_rejects_css_values(self):
        document = {"type": "doc", "content": [{"type": "paragraph", "attrs": {"align": "center", "indent": 2, "line_spacing": "1.5"}, "content": [{"type": "text", "text": "Formatted", "marks": [{"type": "fontFamily", "attrs": {"value": "Times-Roman"}}, {"type": "fontSize", "attrs": {"value": 18}}, {"type": "textColor", "attrs": {"color": "#336699"}}, {"type": "highlight", "attrs": {"color": "#ffff00"}}]}]}]}
        clean = validate_document_json(document)
        self.assertEqual(clean["content"][0]["attrs"], {"align": "center", "indent": 2, "line_spacing": "1.5"})
        self.assertEqual(clean["content"][0]["content"][0]["marks"][-1]["attrs"]["color"], "#FFFF00")
        for mark in (
            {"type": "fontFamily", "attrs": {"value": "url(javascript:alert(1))"}},
            {"type": "fontSize", "attrs": {"value": 999}},
            {"type": "textColor", "attrs": {"color": "red; background:url(http://example.com)"}},
        ):
            attack = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "unsafe", "marks": [mark]}]}]}
            with self.subTest(mark=mark), self.assertRaises(ValidationError):
                validate_document_json(attack)

    def test_create_blank_document_redirects_to_editor_and_is_company_scoped(self):
        response = self.client.post(reverse("digidoc_create"))
        document = DigiDocDocument.objects.get(organization=self.organization)
        self.assertRedirects(response, reverse("digidoc_editor", args=[document.pk]))
        self.assertEqual(document.content_json, {"type": "doc", "content": [{"type": "paragraph", "content": []}]})

    def test_save_pdf_and_server_rendered_preview(self):
        response = self.client.post(reverse("digidoc_create"))
        document = DigiDocDocument.objects.get(organization=self.organization)
        payload = {"title": "Quarterly report", "version": 1, "letterhead_enabled": False, "letterhead_page_mode": "every", "content": {"type": "doc", "content": [{"type": "heading", "level": 1, "content": [{"type": "text", "text": "Quarterly report"}]}, {"type": "paragraph", "content": [{"type": "text", "text": "A safe PDF preview."}]}]}}
        saved = self.client.post(reverse("digidoc_save", args=[document.pk]), data=json.dumps(payload), content_type="application/json")
        self.assertEqual(saved.status_code, 200, saved.content)
        pdf = self.client.get(reverse("digidoc_pdf", args=[document.pk]))
        self.assertEqual(pdf.status_code, 200, pdf.content[:200])
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        preview = self.client.get(reverse("digidoc_preview", args=[document.pk]))
        self.assertEqual(preview.status_code, 200, preview.content[:200])
        self.assertContains(preview, "data:image/png;base64,")

    def test_editor_download_formats_are_clickable_and_return_valid_files(self):
        content = {"type": "doc", "content": [
            {"type": "heading", "level": 1, "content": [{"type": "text", "text": "Export heading"}]},
            {"type": "paragraph", "attrs": {"align": "center"}, "content": [{"type": "text", "text": "Exported bold text", "marks": [{"type": "bold"}]}]},
            {"type": "table", "content": [{"type": "tableRow", "content": [{"type": "tableCell", "content": [{"type": "text", "text": "Table cell"}]}]}]},
        ]}
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Export check", content_json=content)
        editor = self.client.get(reverse("digidoc_editor", args=[document.pk]))
        self.assertEqual(editor.status_code, 200)
        for file_format in ("docx", "odt", "rtf", "txt"):
            with self.subTest(file_format=file_format):
                download = self.client.get(reverse("digidoc_export", args=[document.pk, file_format]))
                self.assertEqual(download.status_code, 200, download.content[:200])
                self.assertIn(f"filename=\"Export_check.{file_format}\"", download["Content-Disposition"])
                self.assertIn(reverse("digidoc_export", args=[document.pk, file_format]).encode(), editor.content)
                if file_format in {"docx", "odt"}:
                    archive = ZipFile(BytesIO(download.content))
                    self.assertIsNone(archive.testzip())
                    xml_name = "word/document.xml" if file_format == "docx" else "content.xml"
                    xml = ElementTree.fromstring(archive.read(xml_name))
                    self.assertIn("Exported bold text", "".join(xml.itertext()))
                    self.assertIn("Table cell", "".join(xml.itertext()))
                elif file_format == "rtf":
                    self.assertTrue(download.content.startswith(b"{\\rtf1"))
                    self.assertIn(b"Exported bold text", download.content)
                else:
                    self.assertIn("Exported bold text", download.content.decode("utf-8"))

    def test_editor_flows_an_oversized_paragraph_onto_a_second_a4_page(self):
        from playwright.sync_api import sync_playwright

        long_text = "w" * 14000
        document = DigiDocDocument.objects.create(
            organization=self.organization,
            created_by=self.owner,
            title="Pagination check",
            content_json={"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": long_text}]}]},
        )
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", markup)
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_content(markup, wait_until="domcontentloaded")
            page.add_style_tag(content=css)
            page.add_script_tag(content=js)
            page.wait_for_function("document.querySelectorAll('#dd-sheet > .dd-page').length > 1")
            pages = page.locator("#dd-sheet > .dd-page")
            self.assertGreater(pages.count(), 1)
            self.assertEqual(page.locator("#dd-sheet").text_content(), long_text)
            first_height = pages.nth(0).evaluate("node => node.getBoundingClientRect().height")
            self.assertAlmostEqual(first_height, 1123, delta=2)
            browser.close()

    def test_three_page_pdf_table_image_and_letterhead_modes_render_to_png(self):
        from pathlib import Path
        import pypdfium2 as pdfium

        image_buffer = BytesIO()
        Image.new("RGB", (48, 48), "orange").save(image_buffer, format="PNG")
        asset = DigiDocImageAsset(organization=self.organization, uploaded_by=self.owner, image_format="png", image_width=48, image_height=48)
        asset.image.save("source.png", ContentFile(image_buffer.getvalue()), save=True)
        letterhead_buffer = BytesIO()
        Image.new("RGB", (210, 297), "#385a9c").save(letterhead_buffer, format="PNG")
        letterhead = CompanyLetterhead.objects.create(organization=self.organization, image_format="png", image_width=210, image_height=297, scale_mode="fit", margin_top_mm=40, margin_bottom_mm=30, margin_left_mm=20, margin_right_mm=20)
        letterhead.image.save("letterhead.png", ContentFile(letterhead_buffer.getvalue()), save=True)
        content = {"type": "doc", "content": [
            {"type": "heading", "level": 1, "content": [{"type": "text", "text": "Three page check"}]},
            {"type": "table", "content": [{"type": "tableRow", "content": [{"type": "tableCell", "content": [{"type": "text", "text": "Name"}]}, {"type": "tableCell", "content": [{"type": "text", "text": "Value"}]}]}, {"type": "tableRow", "content": [{"type": "tableCell", "content": [{"type": "text", "text": "Item"}]}, {"type": "tableCell", "content": [{"type": "text", "text": "123"}]}]}]},
            {"type": "image", "attrs": {"asset_id": str(asset.pk), "alt": "Orange test image"}},
            {"type": "hardBreak"}, {"type": "paragraph", "content": [{"type": "text", "text": "Second page content"}]},
            {"type": "hardBreak"}, {"type": "paragraph", "content": [{"type": "text", "text": "Third page content"}]},
        ]}
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Page proof", content_json=content)
        output = Path("screenshots/digidoc-phase2")
        output.mkdir(parents=True, exist_ok=True)
        for mode, enabled in (("none", False), ("every", True), ("first", True)):
            document.letterhead_enabled = enabled
            document.letterhead_page_mode = "first" if mode == "first" else "every"
            pdf_data = _render_pdf_isolated(document)
            rendered = pdfium.PdfDocument(pdf_data)
            self.assertEqual(len(rendered), 3)
            pixels = []
            for index, page in enumerate(rendered):
                image = page.render(scale=0.35).to_pil().convert("RGB")
                image.save(output / f"proof-{mode}-{index+1}.png")
                pixels.append(image.getpixel((2, 2)))
                text = page.get_textpage().get_text_range()
                if index == 0:
                    self.assertIn("Three page check", text)
                elif index == 1:
                    self.assertIn("Second page content", text)
                else:
                    self.assertIn("Third page content", text)
            if mode == "every":
                self.assertTrue(all(pixel[2] > pixel[0] for pixel in pixels))
            elif mode == "first":
                self.assertTrue(pixels[0][2] > pixels[0][0])
                self.assertGreater(pixels[1][0], 235)
            else:
                self.assertTrue(all(min(pixel) > 235 for pixel in pixels))
            rendered.close()

    def test_private_image_upload_stores_reencoded_png_and_scoped_image_endpoint(self):
        source = BytesIO()
        Image.new("RGB", (20, 20), "navy").save(source, format="PNG")
        source.write(b"<script>never stored</script>")
        response = self.client.post(reverse("digidoc_image_upload"), {"image": SimpleUploadedFile("../../evil.png", source.getvalue(), content_type="text/html")})
        self.assertEqual(response.status_code, 200, response.content)
        asset_id = response.json()["id"]
        image = self.client.get(reverse("digidoc_image", args=[asset_id]))
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image["Content-Type"], "image/png")
        self.assertNotIn(b"never stored", image.content)

    def test_editor_ribbon_screenshots_and_responsive_layout(self):
        from playwright.sync_api import sync_playwright

        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        shell_js = Path("attendance/static/attendance/digidoc-shell.js").read_text(encoding="utf-8")
        editor_js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        ribbon_js = Path("attendance/static/attendance/digidoc-ribbon.js").read_text(encoding="utf-8")
        output = Path("screenshots/digidoc-phase1")
        output.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.set_content(markup, wait_until="domcontentloaded")
            page.add_style_tag(content=css)
            page.add_script_tag(content=shell_js)
            page.add_script_tag(content=editor_js)
            page.add_script_tag(content=ribbon_js)
            self.assertEqual(page.locator("#dd-font-family option").count(), 3)
            self.assertEqual(page.locator("#dd-font-size option").count(), 11)
            self.assertTrue(page.locator('.app-nav__link[data-label="DigiDoc"]').is_visible())
            self.assertEqual(page.locator('.app-nav__link[data-label="DigiDoc"]').get_attribute("aria-current"), "page")
            for width in (1440, 1280, 390):
                page.set_viewport_size({"width": width, "height": 900 if width > 700 else 844})
                for tab_name in ("home", "insert", "layout", "view", "file"):
                    page.locator(f'[data-tab="{tab_name}"]').click()
                    page.wait_for_timeout(80)
                    self.assertEqual(page.locator(f'[data-tab="{tab_name}"]').get_attribute("aria-selected"), "true")
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                    if tab_name != "file":
                        self.assertEqual(page.locator(".dd-ribbon-panel:visible").evaluate("el => Math.round(el.getBoundingClientRect().height)"), 92)
                    page.screenshot(path=str(output / f"ribbon-{tab_name}-{width}.png"), full_page=True)
                page.locator('[data-tab="home"]').click()
                page.locator("#dd-ribbon-toggle").click()
                self.assertTrue(page.locator("#dd-ribbon").evaluate("el => el.classList.contains('is-collapsed')"))
                page.screenshot(path=str(output / f"ribbon-collapsed-{width}.png"), full_page=True)
                page.locator("#dd-ribbon-toggle").click()
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#dd-nav-toggle").click()
            self.assertTrue(page.locator("body").evaluate("el => el.classList.contains('dd-nav-open')"))
            page.locator("#sidebarClose").click()
            self.assertEqual(page_errors, [])
            browser.close()
