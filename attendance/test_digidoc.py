from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from attendance.digidoc import _render_pdf_isolated, validate_document_json
from attendance.digidoc_exports import plain_text
from attendance.models import CompanyLetterhead, DigiDocDocument, DigiDocImageAsset, Organization, OrganizationMembership
from attendance.shell import build_navigation
from PIL import Image
from io import BytesIO
import json
import base64
from pathlib import Path
import re
from zipfile import ZipFile
from xml.etree import ElementTree
from unittest.mock import patch


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

    def test_document_library_uses_preview_cards_and_working_filters(self):
        first = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Quarterly report", content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        other = User.objects.create_user("second_author", first_name="Second", last_name="Author", password="test-pass-123")
        OrganizationMembership.objects.create(user=other, organization=self.organization, role="owner")
        second = DigiDocDocument.objects.create(organization=self.organization, created_by=other, title="Policy draft", content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        response = self.client.get(reverse("digidoc_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recent documents")
        self.assertContains(response, "Quarterly report")
        self.assertContains(response, "Policy draft")
        self.assertContains(response, reverse("digidoc_thumbnail", args=[first.pk]))
        self.assertContains(response, "dd-document-grid")
        owned = self.client.get(reverse("digidoc_list"), {"owner": "me", "sort": "title"})
        self.assertContains(owned, "Quarterly report")
        self.assertNotContains(owned, "Policy draft")
        by_owner = self.client.get(reverse("digidoc_list"), {"owner": str(other.pk)})
        self.assertContains(by_owner, "Policy draft")
        self.assertNotContains(by_owner, "Quarterly report")

    def test_document_thumbnail_is_private_scoped_and_cached(self):
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        png = b"\x89PNG\r\n\x1a\nthumbnail"
        with patch("attendance.digidoc._render_pdf_isolated", return_value=b"%PDF-test") as pdf, patch("attendance.digidoc._render_preview_images_isolated", return_value=[{"number": 1, "data": base64.b64encode(png).decode()}]) as render:
            response = self.client.get(reverse("digidoc_thumbnail", args=[document.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertEqual(response["Cache-Control"], "private, max-age=3600")
            self.assertEqual(response.content, png)
            self.client.get(reverse("digidoc_thumbnail", args=[document.pk]))
            pdf.assert_called_once()
            render.assert_called_once_with(b"%PDF-test", first_page_only=True)

    def test_document_thumbnail_renders_the_actual_first_page(self):
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Thumbnail source", content_json={"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "A preview of this document"}]}]})
        response = self.client.get(reverse("digidoc_thumbnail", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))

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

    def test_checklist_is_validated_and_exports_with_checkbox_markers(self):
        content = {"type": "doc", "content": [{"type": "bulletList", "attrs": {"list_style": "checklist"}, "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Review the report"}]}]},
        ]}]}
        clean = validate_document_json(content)
        self.assertEqual(clean["content"][0]["attrs"], {"list_style": "checklist"})
        self.assertIn("[ ] Review the report", plain_text(clean))
        invalid = {"type": "doc", "content": [{"type": "bulletList", "attrs": {"list_style": "script"}, "content": []}]}
        with self.assertRaises(ValidationError):
            validate_document_json(invalid)

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

    def test_image_adjustments_accept_only_safe_dimensions_alignment_and_crop(self):
        image_id = "8d1b0a3c-b2b2-4bce-9f1e-f299654ea96c"
        content = {"type": "doc", "content": [{"type": "image", "attrs": {"asset_id": image_id, "alt": "Report chart", "width_percent": 65, "align": "right", "crop": "landscape"}}]}
        cleaned = validate_document_json(content)
        self.assertEqual(cleaned["content"][0]["attrs"], {"asset_id": image_id, "alt": "Report chart", "width_percent": 65, "align": "right", "crop": "landscape"})
        for key, value in (("width_percent", 0), ("width_percent", 101), ("width_percent", 10.5), ("width_percent", True), ("align", "justify"), ("align", []), ("crop", "url(https://bad.test)"), ("crop", {}), ("style", "width:100%")):
            attrs = {"asset_id": image_id, "alt": "Chart", key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                validate_document_json({"type": "doc", "content": [{"type": "image", "attrs": attrs}]})

    def test_inserted_image_can_be_resized_aligned_cropped_and_dragged(self):
        from playwright.sync_api import sync_playwright

        source = BytesIO()
        Image.new("RGB", (160, 90), "orange").save(source, format="PNG")
        asset = DigiDocImageAsset.objects.create(organization=self.organization, uploaded_by=self.owner, image_format="png", image_width=160, image_height=90)
        asset.image.save("image-adjust.png", ContentFile(source.getvalue()), save=True)
        content = {"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Before image"}]},
            {"type": "image", "attrs": {"asset_id": str(asset.pk), "alt": "Orange sample"}},
            {"type": "paragraph", "content": [{"type": "text", "text": "After image"}]},
        ]}
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Image controls", content_json=content)
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", markup)
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        editor_js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        ribbon_js = Path("attendance/static/attendance/digidoc-ribbon.js").read_text(encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.add_init_script("window.__saveCount=0;window.fetch = async () => {window.__saveCount++;return new Response(JSON.stringify({version: 1, updated_at: 'Saved'}), {status: 200, headers: {'Content-Type': 'application/json'}})}")
            page.set_content(markup, wait_until="domcontentloaded")
            page.add_style_tag(content=css)
            page.add_script_tag(content=editor_js)
            page.add_script_tag(content=ribbon_js)
            page.locator('[data-tab="insert"]').click()
            frame = page.locator(".dd-image-frame")
            frame.click()
            self.assertTrue(page.locator("#dd-image-tools").is_visible())
            page.locator("#dd-image-width").evaluate("el => { el.value = '55'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
            page.locator("#dd-image-align").select_option("right")
            page.locator("#dd-image-crop").select_option("square")
            self.assertEqual(frame.get_attribute("data-width-percent"), "55")
            self.assertEqual(frame.get_attribute("data-image-align"), "right")
            self.assertEqual(frame.get_attribute("data-crop"), "square")
            image_box = frame.bounding_box()
            target_box = page.locator("#dd-sheet .dd-page > p").nth(1).bounding_box()
            page.mouse.move(image_box["x"] + image_box["width"] / 2, image_box["y"] + image_box["height"] / 2)
            page.mouse.down()
            page.mouse.move(target_box["x"] + 20, target_box["y"] + target_box["height"] - 1, steps=8)
            page.mouse.up()
            self.assertEqual(frame.evaluate("el => [...el.parentElement.children].filter(child => !child.classList.contains('dd-page-zones')).indexOf(el)"), 2)
            self.assertEqual(page.locator(".dd-inline-image").count(), 1)
            browser.close()

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

    def test_preview_route_uses_secure_static_viewer_assets(self):
        from unittest.mock import patch

        document = DigiDocDocument.objects.create(
            organization=self.organization,
            created_by=self.owner,
            title="Professional preview",
            content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
        )
        with patch("attendance.digidoc._render_pdf_isolated", return_value=b"%PDF-preview"), patch(
            "attendance.digidoc._render_preview_images_isolated",
            return_value=[{"number": 1, "data": "AA=="}],
        ):
            response = self.client.get(reverse("digidoc_preview", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "attendance/digidoc-preview.css")
        self.assertContains(response, "attendance/digidoc-preview.js")
        self.assertContains(response, "preview-next")
        self.assertContains(response, "Download PDF")
        self.assertIn("style-src 'self'", response["Content-Security-Policy"])
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])

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
        ribbon_js = Path("attendance/static/attendance/digidoc-ribbon.js").read_text(encoding="utf-8")
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

    def test_pasting_markdown_letter_formats_headings_bold_and_left_alignment(self):
        from playwright.sync_api import sync_playwright

        document = DigiDocDocument.objects.create(
            organization=self.organization,
            created_by=self.owner,
            title="Letter formatting",
            content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
        )
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", markup)
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        pasted = "**[YOUR FULL NAME]**\n[Your Address]\n[City, State]\n\n[Date]\n\n**Dear Hiring Manager,**\n\n### LETTER OF ACCEPTANCE\n\nI am pleased to accept the position.\n\n- Confirm the role\n- Agree to the start date"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.add_init_script("window.fetch = async () => new Response(JSON.stringify({version: 2, updated_at: 'Saved'}), {status: 200, headers: {'Content-Type': 'application/json'}})")
            page.set_content(markup, wait_until="domcontentloaded")
            page.add_style_tag(content=css)
            page.add_script_tag(content=js)
            page.evaluate("""text => {
              const editor=document.querySelector('#dd-sheet'), paragraph=editor.querySelector('.dd-page p');
              paragraph.focus();const range=document.createRange();range.selectNodeContents(paragraph);range.collapse(false);
              const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
              const clipboard=new DataTransfer();clipboard.setData('text/plain',text);
              editor.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clipboard,bubbles:true,cancelable:true}));
            }""", pasted)
            self.assertEqual(page.locator("#dd-sheet strong").all_inner_texts(), ["[YOUR FULL NAME]", "Dear Hiring Manager,"])
            self.assertEqual(page.locator("#dd-sheet h3").inner_text(), "LETTER OF ACCEPTANCE")
            self.assertNotIn("**", page.locator("#dd-sheet").inner_text())
            self.assertNotIn("###", page.locator("#dd-sheet").inner_text())
            self.assertEqual(page.locator("#dd-sheet ul li").all_inner_texts(), ["Confirm the role", "Agree to the start date"])
            self.assertTrue(page.locator("#dd-sheet p, #dd-sheet h3").evaluate_all("els => els.every(el => getComputedStyle(el).textAlign === 'left')"))
            browser.close()

    def test_letterhead_editor_shows_nonprinting_header_and_footer_guides(self):
        from playwright.sync_api import sync_playwright

        image_buffer = BytesIO()
        Image.new("RGB", (210, 297), "white").save(image_buffer, format="PNG")
        letterhead = CompanyLetterhead.objects.create(
            organization=self.organization,
            image_format="png",
            image_width=210,
            image_height=297,
            margin_top_mm=40,
            margin_bottom_mm=30,
            margin_left_mm=20,
            margin_right_mm=20,
        )
        letterhead.image.save("guide-letterhead.png", ContentFile(image_buffer.getvalue()), save=True)
        document = DigiDocDocument.objects.create(
            organization=self.organization,
            created_by=self.owner,
            title="Letterhead guides",
            letterhead_enabled=True,
            letterhead_page_mode="every",
            content_json={"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "First page"}]},
                {"type": "hardBreak"},
                {"type": "paragraph", "content": [{"type": "text", "text": "Second page"}]},
            ]},
        )
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", markup)
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        ribbon_js = Path("attendance/static/attendance/digidoc-ribbon.js").read_text(encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.add_init_script("window.fetch = async (url, options = {}) => { if (options.body) window.__savedDocument = JSON.parse(options.body); return new Response(JSON.stringify({version: 2, updated_at: 'Saved'}), {status: 200, headers: {'Content-Type': 'application/json'}}); }")
            page.set_content(markup, wait_until="domcontentloaded")
            page.add_style_tag(content=css)
            page.add_script_tag(content=js)
            page.add_script_tag(content=ribbon_js)
            guides = page.locator(".dd-page-zones")
            self.assertEqual(guides.count(), 2)
            self.assertTrue(guides.nth(0).is_visible())
            self.assertTrue(guides.nth(0).evaluate("el => el.getAttribute('aria-hidden') === 'true' && el.contentEditable === 'false'"))
            self.assertEqual(guides.nth(0).evaluate("el => getComputedStyle(el).getPropertyValue('--dd-letterhead-header-guide').trim()"), "40mm")
            self.assertEqual(guides.nth(0).evaluate("el => getComputedStyle(el).getPropertyValue('--dd-letterhead-footer-guide').trim()"), "30mm")
            self.assertIn("Header guide", guides.nth(0).evaluate("el => getComputedStyle(el, '::before').content"))
            self.assertIn("Footer guide", guides.nth(0).evaluate("el => getComputedStyle(el, '::after').content"))
            self.assertNotIn("boundary", page.locator("#dd-sheet").inner_text())
            second_page = page.locator("#dd-sheet > .dd-page").nth(1)
            page_box, text_box = second_page.bounding_box(), second_page.locator("p").bounding_box()
            self.assertGreaterEqual(text_box["y"], page_box["y"] + 150)
            self.assertLessEqual(text_box["y"] + text_box["height"], page_box["y"] + 1123 - 112)
            page.emulate_media(media="print")
            self.assertFalse(guides.nth(0).is_visible())
            page.emulate_media(media="screen")
            page.locator('[data-tab="insert"]').click()
            page.locator("#dd-letterhead-other").select_option("none")
            self.assertTrue(guides.nth(0).is_visible())
            self.assertFalse(guides.nth(1).is_visible())
            browser.close()

    def test_editor_alignment_color_and_undo_redo_apply_to_selection(self):
        from playwright.sync_api import sync_playwright

        document = DigiDocDocument.objects.create(
            organization=self.organization,
            created_by=self.owner,
            title="Formatting controls",
            content_json={"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "First paragraph"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Second paragraph"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Third paragraph"}]},
            ]},
        )
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", markup)
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        editor_js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        ribbon_js = Path("attendance/static/attendance/digidoc-ribbon.js").read_text(encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.add_init_script("window.fetch = async () => new Response(JSON.stringify({version: 1, updated_at: 'Saved'}), {status: 200, headers: {'Content-Type': 'application/json'}})")
            page.set_content(markup, wait_until="domcontentloaded")
            page.add_style_tag(content=css)
            page.add_script_tag(content=editor_js)
            page.add_script_tag(content=ribbon_js)
            page.locator("#dd-sheet").evaluate("sheet => { const ps=sheet.querySelectorAll('p'); const range=document.createRange(); range.setStart(ps[0].firstChild,0); range.setEnd(ps[1].firstChild,ps[1].firstChild.length); const selection=getSelection(); selection.removeAllRanges(); selection.addRange(range); }")
            page.locator("#dd-align-menu-toggle").click()
            page.locator('[data-align-choice="center"]').click()
            self.assertEqual(page.locator("#dd-sheet .dd-page p").evaluate_all("els => els.map(el => el.dataset.align || '')"), ["center", "center", ""])
            page.locator("#dd-undo").click()
            self.assertEqual(page.locator("#dd-sheet .dd-page p").evaluate_all("els => els.map(el => el.dataset.align || '')"), ["", "", ""])
            page.locator("#dd-redo").click()
            self.assertEqual(page.locator("#dd-sheet .dd-page p").evaluate_all("els => els.map(el => el.dataset.align || '')"), ["center", "center", ""])

            page.locator("#dd-sheet .dd-page p").first.evaluate("p => { const range=document.createRange(); range.selectNodeContents(p); const selection=getSelection(); selection.removeAllRanges(); selection.addRange(range); document.getElementById('dd-sheet').focus(); }")
            color = page.locator("#dd-text-color")
            color.evaluate("el => el.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))")
            color.evaluate("el => {el.value='#c0c0c0';el.dispatchEvent(new Event('change',{bubbles:true}));}")
            color.evaluate("el => el.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))")
            color.evaluate("el => {el.value='#202124';el.dispatchEvent(new Event('change',{bubbles:true}));}")
            self.assertEqual(page.locator("#dd-sheet [data-dd-text-color]").count(), 1)
            self.assertEqual(page.locator("#dd-sheet [data-dd-text-color]").first.evaluate("el => getComputedStyle(el).color"), "rgb(32, 33, 36)")
            page.locator("#dd-undo").click()
            self.assertEqual(page.locator("#dd-sheet [data-dd-text-color]").first.evaluate("el => getComputedStyle(el).color"), "rgb(192, 192, 192)")
            page.locator("#dd-redo").click()
            self.assertEqual(page.locator("#dd-sheet [data-dd-text-color]").first.evaluate("el => getComputedStyle(el).color"), "rgb(32, 33, 36)")
            page.locator("#dd-spacing-menu-toggle").click()
            page.locator('[data-spacing-choice="1.5"]').click()
            self.assertEqual(page.locator("#dd-sheet .dd-page p").first.get_attribute("data-line-spacing"), "1.5")

            page.locator("#dd-sheet .dd-page p").first.evaluate("p => { const range=document.createRange(); range.selectNodeContents(p); const selection=getSelection(); selection.removeAllRanges(); selection.addRange(range); }")
            page.wait_for_timeout(25)
            page.locator('[data-tab="insert"]').click()
            dialogs = []
            page.once("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.accept("https://example.com")))
            page.locator("#dd-link").click()
            self.assertTrue(dialogs, "Link control did not open its URL dialog")
            self.assertEqual(page.locator('#dd-sheet a[href="https://example.com"]').count(), 1)
            page.locator("#dd-sheet .dd-page p").nth(1).evaluate("p => { const text=p.firstChild; const range=document.createRange(); range.setStart(text,7); range.collapse(true); const selection=getSelection(); selection.removeAllRanges(); selection.addRange(range); }")
            page.locator("#dd-break").click()
            self.assertEqual(page.locator("#dd-sheet > .dd-page").count(), 2)
            self.assertIn("Second", page.locator("#dd-sheet > .dd-page").nth(0).inner_text())
            self.assertIn("paragraph", page.locator("#dd-sheet > .dd-page").nth(1).inner_text())
            page.evaluate("window.__saveClickCount = 0; document.getElementById('digidoc').addEventListener('digidoc:save', () => window.__saveClickCount++)")
            page.locator("#dd-save-now").click()
            page.wait_for_function("window.__saveClickCount > 0")
            browser.close()

    def test_enter_creates_a_paragraph_without_forcing_a_new_page(self):
        from playwright.sync_api import sync_playwright

        letterhead_buffer = BytesIO()
        Image.new("RGB", (80, 120), "white").save(letterhead_buffer, format="PNG")
        letterhead = CompanyLetterhead.objects.create(
            organization=self.organization,
            image=SimpleUploadedFile("enter-test-letterhead.png", letterhead_buffer.getvalue(), content_type="image/png"),
            image_format="png",
            image_width=80,
            image_height=120,
            margin_top_mm=40,
            margin_bottom_mm=30,
            margin_left_mm=20,
            margin_right_mm=20,
        )
        document = DigiDocDocument.objects.create(
            organization=self.organization,
            created_by=self.owner,
            title="Enter key regression",
            content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
            letterhead_enabled=True,
            letterhead_first_slot="1",
            letterhead_other_slot="1",
        )
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", markup)
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        editor_js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.set_content(markup, wait_until="domcontentloaded")
            page.add_style_tag(content=css)
            page.add_script_tag(content=editor_js)
            paragraph = page.locator("#dd-sheet .dd-page p").first
            paragraph.click(position={"x": 5, "y": 5})
            page.keyboard.type("Acceptance letter to Divine Ohien")
            page.keyboard.press("Enter")
            page.keyboard.type("Dear Divine, your appointment is confirmed.")
            page.keyboard.press("Enter")
            page.keyboard.type("Please report on Monday morning.")
            pages = page.locator("#dd-sheet > .dd-page")
            self.assertEqual(pages.count(), 1, "Ordinary Enter presses should add paragraphs on the current page")
            self.assertEqual(page.locator("#dd-sheet .dd-page p").count(), 3)
            self.assertIn("Acceptance letter to Divine Ohien", pages.first.inner_text())
            self.assertIn("Dear Divine, your appointment is confirmed.", pages.first.inner_text())
            self.assertIn("Please report on Monday morning.", pages.first.inner_text())
            selection_page = page.evaluate("() => getSelection().anchorNode.parentElement.closest('.dd-page')?.dataset.pageNumber")
            self.assertEqual(selection_page, "1", "The caret should stay on the page while there is room")
            self.assertEqual(page.locator("#dd-sheet > .dd-page").first.get_attribute("data-letterhead-slot"), "1")
            self.assertNotEqual(page.locator("#dd-sheet > .dd-page").first.evaluate("el => getComputedStyle(el).backgroundImage"), "none")
            browser.close()

    def test_preview_viewer_zoom_navigation_and_print_layout(self):
        from playwright.sync_api import sync_playwright

        css = Path("attendance/static/attendance/digidoc-preview.css").read_text(encoding="utf-8")
        js = Path("attendance/static/attendance/digidoc-preview.js").read_text(encoding="utf-8")
        markup = f'''<!doctype html><html><body>
          <header class="preview-toolbar"><button id="preview-previous"></button><button id="preview-next"></button><button id="preview-zoom-out"></button><output id="preview-zoom-value"></output><button id="preview-zoom-in"></button><button id="preview-fit"></button><button id="preview-print"></button></header>
          <main class="preview-stage" id="preview-stage"><div class="preview-pages">
            <section class="preview-page"><p class="preview-page-caption">Page 1</p><img alt="Page one"></section>
            <section class="preview-page"><p class="preview-page-caption">Page 2</p><img alt="Page two"></section>
          </div></main><span id="preview-current-page"></span></body></html>'''
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.set_content(markup, wait_until="commit")
            page.add_style_tag(content=css)
            page.add_script_tag(content=js)
            image = page.locator(".preview-page img").first
            self.assertAlmostEqual(image.bounding_box()["width"], 794, delta=1)
            page.locator("#preview-next").click()
            self.assertEqual(page.locator("#preview-current-page").inner_text(), "2")
            page.locator("#preview-zoom-in").click()
            self.assertAlmostEqual(image.bounding_box()["width"], 993, delta=1)
            page.locator("#preview-fit").click()
            self.assertAlmostEqual(image.bounding_box()["width"], 794, delta=1)
            page.emulate_media(media="print")
            self.assertFalse(page.locator(".preview-toolbar").is_visible())
            self.assertAlmostEqual(image.bounding_box()["width"], 794, delta=2)
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
            document.letterhead_first_slot = "1"
            document.letterhead_other_slot = "none" if mode == "first" else "1"
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
            self.assertGreaterEqual(page.locator("#dd-font-family option").count(), 15)
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
