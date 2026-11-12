from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from attendance.digidoc import _build_pdf, _render_pdf_isolated, validate_document_json
from attendance.digidoc_exports import _validate_rtf, docx as export_docx, odt as export_odt, plain_text, rtf_text as export_rtf
from attendance.models import CompanyLetterhead, DigiDocDocument, DigiDocImageAsset, DigiDocWritingSettings, Organization, OrganizationMembership
from attendance.shell import build_navigation
from PIL import Image
from io import BytesIO
import json
import base64
import os
import posixpath
import shutil
import subprocess
import tempfile
from pathlib import Path
import re
from zipfile import ZipFile
from xml.etree import ElementTree
from unittest.mock import patch
from docx import Document
from types import SimpleNamespace


def _assert_docx_integrity(test_case, data, *, libreoffice=True):
    with ZipFile(BytesIO(data)) as archive:
        test_case.assertIsNone(archive.testzip())
        names = set(archive.namelist())
        for name in names:
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(archive.read(name))
        rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
        for rels_name in (name for name in names if name.endswith(".rels")):
            base = posixpath.dirname(posixpath.dirname(rels_name)) if "/_rels/" in rels_name else ""
            for relation in ElementTree.fromstring(archive.read(rels_name)).findall("r:Relationship", rel_ns):
                if relation.get("TargetMode") == "External":
                    continue
                target = posixpath.normpath(posixpath.join(base, relation.get("Target", "")))
                test_case.assertIn(target, names, f"Broken DOCX relationship {rels_name}: {target}")
    reopened = Document(BytesIO(data))
    test_case.assertIsNotNone(reopened)
    if not libreoffice:
        return reopened
    candidates = [shutil.which("soffice"), shutil.which("libreoffice")]
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates.extend((os.path.join(program_files, "LibreOffice", "program", "soffice.exe"),
                       os.path.join(program_files, "LibreOffice", "program", "soffice.com")))
    soffice = next((candidate for candidate in candidates if candidate and os.path.isfile(candidate)), None)
    if not soffice:
        return reopened
    with tempfile.TemporaryDirectory(prefix="digidoc-docx-") as work:
        source = Path(work) / "validation.docx"
        source.write_bytes(data)
        profile = (Path(work) / "lo-profile").as_uri()
        result = subprocess.run(
            [soffice, "--headless", "--nologo", "--nodefault", "--nofirststartwizard",
             f"-env:UserInstallation={profile}", "--convert-to", "pdf", "--outdir", work, str(source)],
            capture_output=True, text=True, timeout=120,
        )
        test_case.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        test_case.assertTrue((Path(work) / "validation.pdf").is_file(), result.stderr or result.stdout)
    return reopened


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

    def test_page_layout_spacing_and_indent_values_are_strict(self):
        def doc(attrs=None, paragraph_attrs=None):
            root = {"type": "doc", "attrs": attrs or {}, "content": [{"type": "paragraph", "attrs": paragraph_attrs or {}, "content": []}]}
            validate_document_json(root)
            return root

        doc({"page_size": "A3", "orientation": "landscape", "margins": {"top_cm": 1.0, "right_cm": 2.0, "bottom_cm": 1.0, "left_cm": 2.0}}, {"space_before_pt": 200, "space_after_pt": 0, "left_indent_cm": 10, "right_indent_cm": 0, "first_line_indent_cm": -2.54})
        invalid = [
            ({"page_size": "Tabloid"}, {}), ({"orientation": "diagonal"}, {}),
            ({"margins": {"top_cm": float("nan"), "right_cm": 1, "bottom_cm": 1, "left_cm": 1}}, {}),
            ({}, {"space_before_pt": 201}), ({}, {"space_after_pt": True}),
            ({}, {"left_indent_cm": 10.01}), ({}, {"right_indent_cm": -0.1}),
            ({}, {"first_line_indent_cm": -2.55}),
        ]
        for layout, paragraph in invalid:
            with self.subTest(layout=layout, paragraph=paragraph), self.assertRaises(ValidationError):
                doc(layout, paragraph)

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

    def test_manager_membership_gets_digidoc_without_direct_reports(self):
        user = User.objects.create_user("digidoc_manager", password="test-pass-123")
        OrganizationMembership.objects.create(user=user, organization=self.organization, role="manager")
        client = Client()
        client.force_login(user)
        response = client.get(reverse("digidoc_list"))
        self.assertEqual(response.status_code, 200)
        sections, pages = build_navigation(user, self.organization)
        self.assertIn("digidoc", pages)
        for role in ("owner", "hr_admin", "payroll_officer", "employee"):
            role_user = User.objects.create_user(f"role_matrix_{role}", password="test-pass-123")
            OrganizationMembership.objects.create(user=role_user, organization=self.organization, role=role)
            role_client = Client()
            role_client.force_login(role_user)
            self.assertEqual(role_client.get(reverse("digidoc_list")).status_code, 200, role)
        viewer = User.objects.create_user("role_matrix_viewer", password="test-pass-123")
        OrganizationMembership.objects.create(user=viewer, organization=self.organization, role="viewer")
        viewer_client = Client()
        viewer_client.force_login(viewer)
        self.assertEqual(viewer_client.get(reverse("digidoc_list")).status_code, 403)

    def test_document_library_uses_preview_cards_and_working_filters(self):
        first = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Quarterly report", content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        other = User.objects.create_user("second_author", first_name="Second", last_name="Author", password="test-pass-123")
        OrganizationMembership.objects.create(user=other, organization=self.organization, role="owner")
        second = DigiDocDocument.objects.create(organization=self.organization, created_by=other, title="Policy draft", content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        response = self.client.get(reverse("digidoc_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recent documents")
        self.assertContains(response, "Quarterly report")
        self.assertNotContains(response, "Policy draft")
        self.assertContains(response, reverse("digidoc_thumbnail", args=[first.pk]))
        self.assertContains(response, "dd-document-grid")
        owned = self.client.get(reverse("digidoc_list"), {"owner": "me", "sort": "title"})
        self.assertContains(owned, "Quarterly report")
        self.assertNotContains(owned, "Policy draft")
        by_owner = self.client.get(reverse("digidoc_list"), {"owner": str(other.pk)})
        self.assertNotContains(by_owner, "Policy draft")
        self.assertContains(by_owner, "Quarterly report")

    def test_other_hr_author_cannot_open_or_export_document(self):
        hr_a = User.objects.create_user("hr_author_a", password="test-pass-123")
        OrganizationMembership.objects.create(user=hr_a, organization=self.organization, role="hr_admin")
        author = User.objects.create_user("hr_author_b", password="test-pass-123")
        OrganizationMembership.objects.create(user=author, organization=self.organization, role="hr_admin")
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=author, title="Private B")
        self.client.force_login(hr_a)
        for route in ("digidoc_editor", "digidoc_preview", "digidoc_thumbnail", "digidoc_pdf"):
            response = self.client.get(reverse(route, args=[document.pk]))
            self.assertEqual(response.status_code, 403, route)
        self.assertEqual(self.client.post(reverse("digidoc_delete", args=[document.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("digidoc_list")), "Private B")

    def test_orphan_is_read_only_to_hr_and_can_be_claimed(self):
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=None, title="Legacy orphan")
        response = self.client.get(reverse("digidoc_list"))
        self.assertContains(response, "DigiDoc documents are now private")
        self.assertContains(response, "Take ownership")
        editor = self.client.get(reverse("digidoc_editor", args=[document.pk]))
        self.assertEqual(editor.status_code, 200)
        self.assertContains(editor, 'data-read-only="true"')
        self.assertEqual(self.client.post(reverse("digidoc_save", args=[document.pk]), data="{}", content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(reverse("digidoc_delete", args=[document.pk])).status_code, 403)
        hr = User.objects.create_user("orphan_hr_admin", password="test-pass-123")
        OrganizationMembership.objects.create(user=hr, organization=self.organization, role="hr_admin")
        hr_client = Client()
        hr_client.force_login(hr)
        self.assertContains(hr_client.get(reverse("digidoc_list")), "Legacy orphan")
        self.assertEqual(hr_client.post(reverse("digidoc_save", args=[document.pk]), data="{}", content_type="application/json").status_code, 403)
        self.client.post(reverse("digidoc_claim", args=[document.pk]))
        document.refresh_from_db()
        self.assertEqual(document.created_by, self.owner)

    def test_superuser_without_membership_cannot_access_normal_digidoc_views(self):
        user = User.objects.create_superuser("platform_only", "platform@example.test", "test-pass-123")
        client = Client()
        client.force_login(user)
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Owner document")
        self.assertEqual(client.get(reverse("digidoc_list"), follow=True).status_code, 403)
        self.assertEqual(client.get(reverse("digidoc_editor", args=[document.pk]), follow=True).status_code, 403)

    def test_saved_letterhead_snapshot_survives_replace_and_removal(self):
        from attendance.models import Category
        from PIL import Image
        from django.core.files.base import ContentFile
        from pypdf import PdfReader
        image = BytesIO()
        Image.new("RGB", (210, 297), "navy").save(image, format="PNG")
        letterhead = CompanyLetterhead.objects.create(organization=self.organization, image_format="png", image_width=210, image_height=297)
        letterhead.image.save("saved-letterhead.png", ContentFile(image.getvalue()), save=True)
        self.client.post(reverse("digidoc_create"))
        document = DigiDocDocument.objects.filter(created_by=self.owner).latest("created_at")
        self.assertTrue(document.letterhead_snapshot)
        original = _render_pdf_isolated(document)
        image.seek(0)
        Image.new("RGB", (210, 297), "red").save(image, format="PNG")
        letterhead.image.save("replacement.png", ContentFile(image.getvalue()), save=True)
        replaced = _render_pdf_isolated(document)
        editor = self.client.get(reverse("digidoc_editor", args=[document.pk]))
        self.assertContains(editor, reverse("digidoc_letterhead_image", args=[document.pk, "1"]))
        saved_art = self.client.get(reverse("digidoc_letterhead_image", args=[document.pk, "1"]))
        self.assertEqual(saved_art.status_code, 200)
        self.assertEqual(Image.open(BytesIO(saved_art.content)).getpixel((10, 10)), Image.open(BytesIO(base64.b64decode(document.letterhead_snapshot["1"]["data"]))).getpixel((10, 10)))
        saved_art.close()
        CompanyLetterhead.objects.filter(pk=letterhead.pk).delete()
        saved_after_revoke = self.client.post(reverse("digidoc_save", args=[document.pk]), data=json.dumps({
            "title": document.title, "content": document.content_json, "letterhead_enabled": True,
            "letterhead_page_mode": document.letterhead_page_mode, "letterhead_first_slot": "1",
            "letterhead_other_slot": "1", "version": document.version,
        }), content_type="application/json")
        self.assertEqual(saved_after_revoke.status_code, 200)
        document.refresh_from_db()
        revoked = _render_pdf_isolated(document)
        for pdf in (original, replaced, revoked):
            self.assertTrue(pdf.startswith(b"%PDF-"))
            self.assertTrue(PdfReader(BytesIO(pdf)).pages[0].images)

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
        self.assertEqual(cleaned["content"][0]["attrs"], {"asset_id": image_id, "alt": "Report chart", "width_percent": 65, "align": "right", "crop": "landscape", "layout": "inline", "wrap_side": "right", "margin_pt": 0, "anchor": "paragraph", "x_pt": 0, "y_pt": 0, "space_before_pt": 0, "space_after_pt": 0})
        for key, value in (("width_percent", 0), ("width_percent", 101), ("width_percent", 10.5), ("width_percent", True), ("align", "justify"), ("align", []), ("crop", "url(https://bad.test)"), ("crop", {}), ("style", "width:100%")):
            attrs = {"asset_id": image_id, "alt": "Chart", key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                validate_document_json({"type": "doc", "content": [{"type": "image", "attrs": attrs}]})

    def test_image_layout_attributes_are_strict_and_legacy_images_get_safe_defaults(self):
        image_id = "8d1b0a3c-b2b2-4bce-9f1e-f299654ea96c"
        legacy = validate_document_json({"type": "doc", "content": [{"type": "image", "attrs": {"asset_id": image_id, "alt": "Legacy"}}]})
        self.assertEqual(legacy["content"][0]["attrs"]["layout"], "inline")
        self.assertEqual(legacy["content"][0]["attrs"]["space_before_pt"], 0)
        for key, value in (("layout", "url(https://bad.test)"), ("wrap_side", "center"), ("margin_pt", 72.1), ("margin_pt", "12px"), ("anchor", "body"), ("x_pt", -1), ("y_pt", 2001), ("space_before_pt", True), ("space_after_pt", 201), ("alt", "nul\x00byte"), ("alt", "javascript:alert(1)")):
            attrs = {"asset_id": image_id, "alt": "safe", key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                validate_document_json({"type": "doc", "content": [{"type": "image", "attrs": attrs}]})
        floating = [{"type": "image", "attrs": {"asset_id": image_id, "alt": "float", "layout": "wrap"}} for _ in range(21)]
        with self.assertRaises(ValidationError):
            validate_document_json({"type": "doc", "content": floating})
        with self.assertRaises(ValidationError):
            validate_document_json({"type": "doc", "content": [{"type": "hardBreak"} for _ in range(50)]})
        with self.assertRaises(ValidationError):
            validate_document_json({"type": "doc", "content": [{"type": "image", "attrs": {"asset_id": image_id, "alt": "bad", "x_pt": float("nan")}}]})

    def test_all_export_formats_embed_scoped_inline_images_and_preserve_spacing(self):
        from attendance.digidoc import _build_pdf, _render_pdf_isolated
        image_buffer = BytesIO()
        Image.new("RGBA", (48, 32), (250, 120, 20, 180)).save(image_buffer, format="PNG")
        asset = DigiDocImageAsset(organization=self.organization, uploaded_by=self.owner, image_format="png", image_width=48, image_height=32)
        asset.image.save("all-formats.png", ContentFile(image_buffer.getvalue()), save=True)
        image_nodes = []
        for align in ("left", "center", "right"):
            for crop in ("none", "square", "landscape", "portrait"):
                image_nodes.append({"type": "image", "attrs": {"asset_id": str(asset.pk), "alt": f"{align} {crop}", "align": align, "crop": crop, "width_percent": 60, "space_before_pt": 8, "space_after_pt": 12}})
        content = {"type": "doc", "content": [
            {"type": "paragraph", "attrs": {"align": "center"}, "content": [{"type": "text", "text": "Before inline "}, image_nodes.pop(0), {"type": "text", "text": " after inline"}]},
            *image_nodes,
        ]}
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Image exports", content_json=content)
        export_assets = {str(asset.pk): image_buffer.getvalue()}
        pdf = _build_pdf(document, self.organization, pdf_assets=export_assets)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"/Subtype /Image", pdf)
        inline_document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Inline image PDF", content_json={"type":"doc", "content":[{"type":"paragraph", "content":[{"type":"text", "text":"Before "}, {"type":"image", "attrs":{"asset_id":str(asset.pk), "alt":"Inline image", "space_before_pt":4, "space_after_pt":6}}, {"type":"text", "text":" after"}]}]})
        isolated_pdf = _render_pdf_isolated(inline_document)
        self.assertTrue(isolated_pdf.startswith(b"%PDF-"))
        self.assertIn(b"/Subtype /Image", isolated_pdf)
        for file_format in ("docx", "odt", "rtf", "txt"):
            with self.subTest(file_format=file_format):
                response = self.client.get(reverse("digidoc_export", args=[document.pk, file_format]))
                self.assertEqual(response.status_code, 200, response.content[:300])
                if file_format == "docx":
                    archive = ZipFile(BytesIO(response.content))
                    self.assertIsNone(archive.testzip())
                    self.assertGreaterEqual(len([name for name in archive.namelist() if name.startswith("word/media/")]), 12)
                    ElementTree.fromstring(archive.read("word/document.xml"))
                    relationships = ElementTree.fromstring(archive.read("word/_rels/document.xml.rels"))
                    self.assertTrue(all(rel.attrib.get("TargetMode") != "External" for rel in relationships))
                    self.assertIn(b"descr=\"left none\"", archive.read("word/document.xml"))
                elif file_format == "odt":
                    archive = ZipFile(BytesIO(response.content))
                    self.assertIsNone(archive.testzip())
                    self.assertGreaterEqual(len([name for name in archive.namelist() if name.startswith("Pictures/")]), 12)
                    ElementTree.fromstring(archive.read("content.xml"))
                elif file_format == "rtf":
                    _validate_rtf(response.content)
                    self.assertGreaterEqual(response.content.count(b"\\pict"), 12)
                    self.assertIn(b"\\pngblip", response.content)
                    with self.assertRaises(ValueError):
                        _validate_rtf(b"{\\rtf1\\object unsafe}")
                else:
                    text = response.content.decode("utf-8")
                    self.assertIn("[Image: left none]", text)
                    self.assertLessEqual(text.count("\n\n\n\n\n\n"), 12)

    def test_export_uses_only_assets_owned_by_the_current_organization(self):
        other_org = Organization.objects.create(name="Other DigiDoc", slug="other-digidoc", setup_completed=True)
        foreign = DigiDocImageAsset(organization=other_org, uploaded_by=self.owner, image_format="png", image_width=10, image_height=10)
        image_data = BytesIO()
        Image.new("RGB", (10, 10), "red").save(image_data, format="PNG")
        foreign.image.save("foreign.png", ContentFile(image_data.getvalue()), save=True)
        content = {"type": "doc", "content": [{"type": "image", "attrs": {"asset_id": str(foreign.pk), "alt": "Confidential"}}]}
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, content_json=content)
        response = self.client.get(reverse("digidoc_export", args=[document.pk, "docx"]))
        self.assertEqual(response.status_code, 200)
        archive = ZipFile(BytesIO(response.content))
        self.assertFalse(any(name.startswith("word/media/") for name in archive.namelist()))
        self.assertIn("[Image unavailable: Confidential]", "".join(ElementTree.fromstring(archive.read("word/document.xml")).itertext()))

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
                self.assertEqual(download["Content-Type"], {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "odt": "application/vnd.oasis.opendocument.text", "rtf": "application/rtf", "txt": "text/plain; charset=utf-8"}[file_format])
                self.assertIn(f"filename=\"Export_check.{file_format}\"", download["Content-Disposition"])
                self.assertIn(reverse("digidoc_export", args=[document.pk, file_format]).encode(), editor.content)
                if file_format in {"docx", "odt"}:
                    archive = ZipFile(BytesIO(download.content))
                    self.assertIsNone(archive.testzip())
                    xml_name = "word/document.xml" if file_format == "docx" else "content.xml"
                    xml = ElementTree.fromstring(archive.read(xml_name))
                    self.assertIn("Exported bold text", "".join(xml.itertext()))
                    self.assertIn("Table cell", "".join(xml.itertext()))
                    if file_format == "docx":
                        _assert_docx_integrity(self, download.content)
                elif file_format == "rtf":
                    self.assertTrue(download.content.startswith(b"{\\rtf1"))
                    self.assertIn(b"Exported bold text", download.content)
                else:
                    self.assertIn("Exported bold text", download.content.decode("utf-8"))

    def test_phase4_find_replace_links_special_characters_and_safe_paste(self):
        from playwright.sync_api import sync_playwright
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Editor tools", content_json={"type": "doc", "attrs": {"header": "Repeated injected header", "footer": "Repeated footer words", "page_numbers": True}, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "foo Foo foo"}]}]})
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8"))
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        editor_js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        ribbon_js = Path("attendance/static/attendance/digidoc-ribbon.js").read_text(encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(4000)
            page.set_content(markup, wait_until="domcontentloaded")
            page.add_style_tag(content=css)
            page.add_script_tag(content=editor_js)
            page.add_script_tag(content=ribbon_js)
            self.assertRegex(page.locator("#dd-status-word-count").inner_text(), r"3 words . 11 characters")
            page.keyboard.press("Control+F")
            page.locator("#dd-find-query").fill("foo")
            page.locator("#dd-match-case").check()
            page.locator("#dd-replace-query").fill("HR")
            page.locator("#dd-replace-all").click()
            paragraph = page.locator("#dd-sheet p").first
            self.assertEqual(paragraph.inner_text(), "HR Foo HR")
            self.assertRegex(page.locator("#dd-status-word-count").inner_text(), r"3 words . 9 characters")
            self.assertIn("2 replacements", page.locator("#dd-find-result").inner_text())
            page.locator("#dd-find-close").click()
            page.evaluate("""() => {const text=document.querySelector('#dd-sheet p').firstChild,range=document.createRange(),selection=getSelection();range.setStart(text,0);range.setEnd(text,2);selection.removeAllRanges();selection.addRange(range);}""")
            page.wait_for_function("document.getElementById('dd-selection-count').textContent.includes('characters selected')")
            self.assertRegex(page.locator("#dd-selection-count").inner_text(), r"1 word . 2 characters selected")
            page.locator("#dd-tab-insert").click()
            page.evaluate("""() => { const p=document.querySelector('#dd-sheet p'),text=p.firstChild,range=document.createRange(),selection=getSelection();range.setStart(text,text.length);range.collapse(true);selection.removeAllRanges();selection.addRange(range);document.dispatchEvent(new Event('selectionchange')); }""")
            page.locator("#dd-special-characters").click()
            page.locator("#dd-special-panel button").filter(has_text=chr(169)).click()
            self.assertIn(chr(169), paragraph.inner_text())
            date_text = page.evaluate("new Intl.DateTimeFormat(document.documentElement.lang||'en-GB',{dateStyle:'long'}).format(new Date())")
            page.locator("#dd-insert-date").click()
            self.assertIn(date_text, paragraph.inner_text())
            page.evaluate("""() => { const p=document.querySelector('#dd-sheet p'),range=document.createRange(),selection=getSelection();range.selectNodeContents(p);selection.removeAllRanges();selection.addRange(range);const event=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:new DataTransfer()});event.clipboardData.setData('text/plain','HR <img src=x onerror=alert(1)>');event.clipboardData.setData('text/html','<img src=x onerror=alert(1)><script>alert(1)</script><b>bad</b>');document.querySelector('#dd-sheet').dispatchEvent(event); }""")
            self.assertEqual(page.locator("#dd-sheet img").count(), 0)
            self.assertNotIn("<script>", page.locator("#dd-sheet").inner_text())
            page.evaluate("""() => {const p=document.querySelector('#dd-sheet p'),text=p.firstChild,range=document.createRange(),selection=getSelection();range.setStart(text,0);range.setEnd(text,2);selection.removeAllRanges();selection.addRange(range);document.dispatchEvent(new Event('selectionchange'));}""")
            page.on("dialog", lambda dialog: dialog.accept("https://example.com/path"))
            page.locator("#dd-link").click()
            link = page.locator("#dd-sheet a[href='https://example.com/path']")
            self.assertEqual(link.get_attribute("rel"), "noopener noreferrer")
            page.evaluate("""() => {const p=document.querySelector('#dd-sheet p'),text=p.firstChild,range=document.createRange(),selection=getSelection();range.setStart(text,text.length);range.collapse(true);selection.removeAllRanges();selection.addRange(range);document.dispatchEvent(new Event('selectionchange'));}""")
            page.locator("#dd-line").click()
            self.assertEqual(page.locator("#dd-sheet hr").count(), 1)
            browser.close()

    def test_phase4_editor_downloads_all_five_formats(self):
        from playwright.sync_api import sync_playwright
        from pypdf import PdfReader
        from odf.opendocument import load as load_odt
        from striprtf.striprtf import rtf_to_text

        image = BytesIO()
        Image.new("RGB", (210, 297), "white").save(image, format="PNG")
        letterhead = CompanyLetterhead.objects.create(organization=self.organization, image_format="png", image_width=210, image_height=297, margin_top_mm=35, margin_bottom_mm=25, margin_left_mm=18, margin_right_mm=18)
        letterhead.image.save("phase4-letterhead.png", ContentFile(image.getvalue()), save=True)
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Phase 4 acceptance", content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", markup)
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        scripts = [Path(f"attendance/static/attendance/{name}").read_text(encoding="utf-8") for name in ("digidoc-editor.js", "digidoc-ribbon.js")]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.set_content(markup, wait_until="domcontentloaded")
            page.evaluate("window.__phase4Errors=[];window.addEventListener('error',e=>window.__phase4Errors.push(e.message));window.fetch=async(url,options={})=>{if(options.body)window.__phase4Payload=JSON.parse(options.body);return new Response(JSON.stringify({ok:true,version:2,updated_at:'Saved'}),{status:200,headers:{'Content-Type':'application/json'}})}")
            page.add_style_tag(content=css)
            for script in scripts:
                page.add_script_tag(content=script)
            editor = page.locator("#dd-sheet")
            first = page.locator("#dd-sheet .dd-page p").first
            first.click()
            page.keyboard.press("Control+A")
            page.keyboard.type("dear HR. this is a DigiDoc acceptance letter.")
            page.keyboard.press("Enter")
            page.locator('[data-command="insertOrderedList"]').click()
            page.keyboard.type("First listed item")
            page.keyboard.press("Enter")
            page.keyboard.type("Second listed item")
            page.keyboard.press("Enter")
            page.keyboard.press("Enter")
            page.locator("#dd-font-family").select_option(label="Roboto")
            page.locator("#dd-tab-insert").click()
            page.locator("#dd-table").click()
            page.locator('#dd-table-grid button[data-rows="2"][data-columns="2"]').click()
            page.locator("#dd-sheet table td").first.click()
            page.keyboard.type("Table item")
            page.locator("#dd-tab-layout").click()
            page.locator("#dd-header-text").fill("HR confidential")
            page.locator("#dd-footer-text").fill("Acceptance copy")
            page.locator("#dd-page-numbers").check()
            page.locator("#dd-margin-preset").select_option("Narrow")
            page.locator("#dd-tab-insert").click()
            page.locator("#dd-letterhead-menu").click()
            artifact_path = Path("artifacts/digidoc-phase4-e2e")
            artifact_path.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(artifact_path / "DigiDoc_Phase4_editor_1440.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(artifact_path / "DigiDoc_Phase4_editor_390.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})
            payload = page.evaluate("""() => {
              const textNode = (node) => ({type:'text', text:node.textContent || '', marks:[{type:'fontFamily',attrs:{value:document.getElementById('dd-font-family').value}}]});
              const blocks = Array.from(document.querySelectorAll('#dd-sheet > .dd-page')).flatMap(page => Array.from(page.children)).filter(el => !el.classList.contains('dd-page-zones') && !el.classList.contains('dd-page-header') && !el.classList.contains('dd-page-footer')).flatMap(el => el.matches('p') ? Array.from(el.children).filter(child=>child.matches('ol,ul,table,hr')).length ? [...Array.from(el.childNodes).filter(node=>node.nodeType===Node.TEXT_NODE&&node.textContent.trim()).map(node=>Object.assign(document.createElement('span'),{textContent:node.textContent})),...Array.from(el.children).filter(child=>child.matches('ol,ul,table,hr'))] : [el] : [el]);
              const content = [];
              for (const block of blocks) {
                if (block.matches('p,h1,h2,h3')) { const nested=Array.from(block.children).find(child=>child.matches('ol,ul,table,hr')); if(nested){ if(block.textContent.replace(nested.textContent,'').trim())content.push({type:'paragraph',content:[textNode({textContent:block.textContent.replace(nested.textContent,'').trim()})]}); blocks.push(nested); } else content.push({type:block.tagName==='P'?'paragraph':'heading', ...(block.tagName!=='P'?{level:Number(block.tagName.slice(1))}:{}), content:block.textContent.trim()?[textNode(block)]:[]}); }
                else if (block.matches('ol,ul')) content.push({type:block.tagName==='OL'?'orderedList':'bulletList',attrs:block.tagName==='OL'?{start:Number(block.getAttribute('start')||1)}:{},content:Array.from(block.children).filter(el=>el.tagName==='LI').map(li=>({type:'listItem',content:[{type:'paragraph',content:[{type:'text',text:li.textContent.trim()}]}]}))});
                else if (block.matches('table')) content.push({type:'table',attrs:{width_percent:100,column_widths:Array.from(block.querySelectorAll(':scope > colgroup > col')).map(col=>Math.round(parseFloat(col.style.width)||50)),border_color:'#aab1ba',border_width:1},content:Array.from(block.rows).map(row=>({type:'tableRow',content:Array.from(row.cells).map(cell=>({type:'tableCell',content:cell.textContent.trim()?[{type:'text',text:cell.textContent.trim()}]:[]}))}))});
              }
              return {title:document.getElementById('dd-title').value,letterhead_enabled:document.getElementById('dd-letterhead').checked,content:{type:'doc',attrs:{page_size:document.getElementById('dd-page-size').value,orientation:document.getElementById('dd-orientation').value,margins:{top_cm:Number(document.getElementById('dd-margin-top').value),right_cm:Number(document.getElementById('dd-margin-right').value),bottom_cm:Number(document.getElementById('dd-margin-bottom').value),left_cm:Number(document.getElementById('dd-margin-left').value)},header:document.getElementById('dd-header-text').value,footer:document.getElementById('dd-footer-text').value,page_numbers:document.getElementById('dd-page-numbers').checked},content}};
            }""")
            self.assertEqual(page.evaluate("window.__phase4Errors"), [])
            self.assertTrue(payload["letterhead_enabled"])
            self.assertEqual(payload["content"]["attrs"]["header"], "HR confidential")
            self.assertTrue(any(node["type"] == "orderedList" for node in payload["content"]["content"]), page.locator("#dd-sheet").evaluate("el => el.innerHTML"))
            self.assertTrue(any(node["type"] == "table" for node in payload["content"]["content"]))
            content = validate_document_json(payload["content"])
            browser.close()

        document.title = payload["title"]
        document.content_json = content
        document.letterhead_enabled = True
        document.letterhead_snapshot = {"1": {"scale_mode": "fit", "margin_top_mm": 35, "margin_bottom_mm": 25, "margin_left_mm": 18, "margin_right_mm": 18, "image_format": "png", "image_width": 210, "image_height": 297}}
        document.save()
        outputs = {}
        for file_format in ("docx", "odt", "rtf", "txt"):
            response = self.client.get(reverse("digidoc_export", args=[document.pk, file_format]))
            self.assertEqual(response.status_code, 200, response.content[:200])
            outputs[file_format] = response.content
        with patch("attendance.digidoc._render_pdf_isolated", side_effect=lambda saved_doc: _build_pdf(saved_doc, self.organization)):
            pdf_response = self.client.get(reverse("digidoc_pdf", args=[document.pk]))
        self.assertEqual(pdf_response.status_code, 200, pdf_response.content[:200])
        outputs["pdf"] = pdf_response.content
        target = Path("artifacts/digidoc-phase4-e2e")
        target.mkdir(parents=True, exist_ok=True)
        for extension, data in outputs.items():
            path = target / f"DigiDoc_Phase4_acceptance.{extension}"
            path.write_bytes(data)
            self.assertGreater(path.stat().st_size, 0)
        reopened = Document(BytesIO(outputs["docx"]))
        self.assertTrue(any("First listed item" in paragraph.text for paragraph in reopened.paragraphs))
        odt_document = load_odt(BytesIO(outputs["odt"]))
        self.assertIsNotNone(odt_document.text)
        with ZipFile(BytesIO(outputs["odt"])) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("Table item", "".join(ElementTree.fromstring(archive.read("content.xml")).itertext()))
        _validate_rtf(outputs["rtf"])
        self.assertIn("Table item", rtf_to_text(outputs["rtf"].decode("ascii")))
        self.assertIn("Table item", outputs["txt"].decode("utf-8"))
        self.assertIn("Table item", "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(outputs["pdf"])).pages))

    def test_headers_footers_page_numbers_export_to_all_formats(self):
        content = validate_document_json({"type": "doc", "attrs": {"page_size": "A4", "orientation": "portrait", "margins": {"top_cm": 2.5, "right_cm": 2.5, "bottom_cm": 2.5, "left_cm": 2.5}, "header": "HR Confidential", "footer": "DigiDoc test", "page_numbers": True}, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Header footer body"}]}]})
        self.assertEqual(content["attrs"]["header"], "HR Confidential")
        docx_bytes = export_docx(content)
        with ZipFile(BytesIO(docx_bytes)) as archive:
            header = ElementTree.fromstring(archive.read("word/header1.xml"))
            footer = ElementTree.fromstring(archive.read("word/footer1.xml"))
            self.assertIn("HR Confidential", "".join(header.itertext()))
            self.assertIn("DigiDoc test", "".join(footer.itertext()))
            self.assertEqual(len(footer.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}instrText")), 2)
        self.assertEqual("HR Confidential" in plain_text(content) and "DigiDoc test" in plain_text(content), True)
        self.assertIn("Page \\chpgn of", export_rtf(content).decode("ascii"))
        odt_bytes = export_odt(content)
        with ZipFile(BytesIO(odt_bytes)) as archive:
            styles = ElementTree.fromstring(archive.read("styles.xml"))
            self.assertIn("HR Confidential", "".join(styles.itertext()))
            self.assertTrue(styles.findall(".//{urn:oasis:names:tc:opendocument:xmlns:text:1.0}page-count"))
        pdf_doc = SimpleNamespace(title="Phase 4", content_json=content, letterhead_enabled=False, letterhead_first_slot="1", letterhead_page_mode="every", letterhead_other_slot="1")
        pdf = _build_pdf(pdf_doc, self.organization)
        from pypdf import PdfReader
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("HR Confidential", text)
        self.assertIn("Page 1 of 1", text)
        self.assertIn("DigiDoc test", text)

    def test_link_validation_and_editor_tools_are_present(self):
        valid = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "secure", "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}]}]}]}
        validate_document_json(valid)
        for href in ("javascript:alert(1)", "data:text/html,boom", "ftp://example.com"):
            attack = json.loads(json.dumps(valid)); attack["content"][0]["content"][0]["marks"][0]["attrs"]["href"] = href
            with self.subTest(href=href), self.assertRaises(ValidationError): validate_document_json(attack)
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Phase 4 controls", content_json={"type": "doc", "attrs": {"header": "Existing header", "footer": "Existing footer", "page_numbers": True}, "content": [{"type": "paragraph", "content": []}]})
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        for control in ("dd-find", "dd-replace", "dd-special-characters", "dd-insert-date", "dd-paste", "dd-format-painter", "dd-header-text", "dd-footer-text", "dd-page-numbers"):
            self.assertIn(f'id="{control}"', markup)
        self.assertNotIn("coming next", markup)
        self.assertNotIn('id="dd-image-move"', markup)

    def test_table_widths_and_merges_are_explicit_in_docx_and_odt_exports(self):
        cell = lambda label, attrs=None: {"type": "tableCell", **({"attrs": attrs} if attrs else {}), "content": [{"type": "text", "text": label}]}
        table = lambda rows, widths, width=100: {"type": "table", "attrs": {"width_percent": width, "column_widths": widths, "border_color": "#667788", "border_width": 2}, "content": [{"type": "tableRow", "content": row} for row in rows]}
        contents = [
            table([[cell("One")]], [100]),
            table([[cell("Left"), cell("Right")]], [30, 70], 80),
            table([[cell("A"), cell("B"), cell("C"), cell("D"), cell("E")]], [10, 15, 20, 25, 30]),
            table([[cell("Merged", {"colspan": 2, "shading": "#FFFF00"}), cell("Tail")], [cell("X"), cell("Y"), cell("Z")]], [25, 25, 50]),
        ]
        nested = {"type": "bulletList", "content": [{"type": "listItem", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Table in list"}]},
            table([[cell("Nested left"), cell("Nested right")]], [40, 60]),
        ]}]}
        content = validate_document_json({"type": "doc", "content": contents + [nested]})
        docx_bytes = export_docx(content)
        with ZipFile(BytesIO(docx_bytes)) as archive:
            document_xml = ElementTree.fromstring(archive.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            tables = document_xml.findall(".//w:tbl", ns)
            self.assertEqual(len(tables), 5)
            expected = ([9360], [2246, 5242], [936, 1404, 1872, 2340, 2808], [2340, 2340, 4680], [3744, 5616])
            for table_xml, widths in zip(tables, expected):
                self.assertEqual([int(col.get("{%s}w" % ns["w"])) for col in table_xml.findall("./w:tblGrid/w:gridCol", ns)], widths)
                self.assertIsNotNone(table_xml.find("./w:tblPr/w:tblLayout[@w:type='fixed']", ns))
                self.assertIsNotNone(table_xml.find("./w:tblPr/w:tblW[@w:type='pct']", ns))
            self.assertEqual(tables[1].find("./w:tblPr/w:tblW", ns).get("{%s}w" % ns["w"]), "4000")
            self.assertEqual(tables[3].find(".//w:gridSpan", ns).get("{%s}val" % ns["w"]), "2")
            self.assertEqual(tables[3].find(".//w:shd", ns).get("{%s}fill" % ns["w"]), "FFFF00")
            self.assertEqual(len(Document(BytesIO(docx_bytes)).tables), 5)

        odt_bytes = export_odt(content)
        with ZipFile(BytesIO(odt_bytes)) as archive:
            odt_xml = ElementTree.fromstring(archive.read("content.xml"))
            ns = {"table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0"}
            odt_tables = odt_xml.findall(".//table:table", ns)
            self.assertEqual(len(odt_tables), 5)
            self.assertEqual(len(odt_tables[2].findall("./table:table-column", ns)), 5)
            self.assertEqual(odt_tables[3].find(".//table:table-cell", ns).get("{%s}number-columns-spanned" % ns["table"]), "2")
            self.assertTrue(odt_tables[1].get("{%s}style-name" % ns["table"]))
            style_ns = {"style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0"}
            table_styles = odt_xml.findall(".//style:style[@style:family='table']", style_ns)
            self.assertTrue(table_styles)
            self.assertTrue(any(style.find("style:table-properties", style_ns).get("{%s}width" % style_ns["style"]).endswith("cm") for style in table_styles if style.find("style:table-properties", style_ns) is not None))
            cell_properties = odt_xml.findall(".//style:table-cell-properties", style_ns)
            self.assertTrue(any(properties.get("{%s}border" % "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0") != "none" for properties in cell_properties))
            self.assertTrue(any(properties.get("{%s}background-color" % "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0") == "#FFFF00" for properties in cell_properties))

        rtf_bytes = export_rtf(content)
        _validate_rtf(rtf_bytes)
        self.assertIn(b"\\cellx", rtf_bytes)
        self.assertIn(b"\\trwWidth7488", rtf_bytes)
        self.assertIn(b"Nested left", rtf_bytes)
        self.assertIn("Nested left | Nested right", plain_text(content))

        pdf_document = DigiDocDocument(organization=self.organization, created_by=self.owner, title="Table width", content_json=content)
        with patch("attendance.digidoc.Table", wraps=__import__("reportlab.platypus", fromlist=["Table"]).Table) as table_spy:
            _build_pdf(pdf_document, self.organization)
        built_tables = [call for call in table_spy.call_args_list]
        self.assertEqual(len(built_tables), 5)
        self.assertAlmostEqual(sum(built_tables[1].kwargs["colWidths"]), (595.2756 - 2 * 2.5 * 28.3465) * .8, delta=1)

    def test_table_attributes_are_strictly_validated(self):
        invalid = [
            {"width_percent": 101},
            {"column_widths": [40, 40]},
            {"border_width": 9},
        ]
        for attrs in invalid:
            with self.subTest(attrs=attrs), self.assertRaises(ValidationError):
                validate_document_json({"type": "doc", "content": [{"type": "table", "attrs": attrs, "content": []}]})
        with self.assertRaises(ValidationError):
            validate_document_json({"type": "doc", "content": [{"type": "table", "attrs": {"column_widths": [100]}, "content": [
                {"type": "tableRow", "content": [{"type": "tableCell", "content": []}, {"type": "tableCell", "content": []}]},
            ]}]})

    def test_table_grid_toolbar_and_structural_controls_work_in_editor(self):
        from playwright.sync_api import sync_playwright
        document = DigiDocDocument.objects.create(
            organization=self.organization, created_by=self.owner, title="Table controls",
            content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
        )
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", markup)
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        ribbon_js = Path("attendance/static/attendance/digidoc-ribbon.js").read_text(encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.add_init_script("window.fetch = async () => new Response(JSON.stringify({version: 1, updated_at: 'Saved'}), {status: 200})")
            page.set_content(markup, wait_until="domcontentloaded")
            page.add_style_tag(content=css)
            page.add_script_tag(content=js)
            page.add_script_tag(content=ribbon_js)
            page.locator('[data-tab="insert"]').click()
            page.locator("#dd-table").click()
            page.locator('#dd-table-grid button[data-rows="2"][data-columns="3"]').click()
            table = page.locator("#dd-sheet table")
            self.assertEqual(table.count(), 1)
            self.assertEqual(table.evaluate("el => [el.rows.length, el.rows[0].cells.length, el.style.width, el.style.tableLayout]"), [2, 3, "100%", "fixed"])
            cell = table.locator("td").nth(0)
            cell.click()
            self.assertTrue(page.locator("#dd-table-toolbar").is_visible())
            page.locator('[data-table-action="row-after"]').click()
            self.assertEqual(table.locator("tr").count(), 3)
            page.locator('[data-table-action="col-after"]').click()
            self.assertEqual(table.locator("tr").nth(0).locator("td").count(), 4)
            page.locator("#dd-table-width").fill("75")
            page.locator("#dd-table-width").dispatch_event("change")
            self.assertEqual(table.evaluate("el => el.style.width"), "75%")
            page.locator("#dd-table-shading").fill("#ffdd00")
            self.assertIn("rgb(255, 221, 0)", cell.evaluate("el => el.style.backgroundColor"))
            page.evaluate("""() => {
              const cells=document.querySelectorAll('#dd-sheet table tr:first-child td'),range=document.createRange(),selection=window.getSelection();
              range.selectNodeContents(cells[0]);range.setEnd(cells[1].firstChild||cells[1],cells[1].firstChild?cells[1].firstChild.length:0);selection.removeAllRanges();selection.addRange(range);
            }""")
            page.locator('[data-table-action="merge"]').click()
            self.assertGreaterEqual(int(table.locator("tr").nth(0).locator("td").nth(0).get_attribute("colspan") or "1"), 2)
            page.locator('[data-table-action="split"]').click()
            self.assertEqual(table.locator("tr").nth(0).locator("td").nth(0).get_attribute("colspan"), "1")
            browser.close()

    def test_empty_table_cells_keep_a_text_line_height_on_load(self):
        from playwright.sync_api import sync_playwright
        document = DigiDocDocument.objects.create(
            organization=self.organization, created_by=self.owner, title="Empty table cells",
            content_json={"type": "doc", "content": [
                {"type": "table", "content": [{"type": "tableRow", "content": [
                    {"type": "tableCell", "content": []},
                    {"type": "tableCell", "content": [{"type": "text", "text": "Filled"}]},
                ]}]},
            ]},
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
            cells = page.locator("#dd-sheet table td")
            self.assertTrue(cells.nth(0).evaluate("el => el.querySelector('br') !== null"))
            empty_height = cells.nth(0).evaluate("el => Math.round(el.getBoundingClientRect().height)")
            filled_height = cells.nth(1).evaluate("el => Math.round(el.getBoundingClientRect().height)")
            self.assertEqual(empty_height, filled_height)
            browser.close()

    def test_table_size_picker_is_not_clipped_by_ribbon(self):
        from playwright.sync_api import sync_playwright
        document = DigiDocDocument.objects.create(
            organization=self.organization, created_by=self.owner, title="Table picker",
            content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
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
            page.add_script_tag(content=ribbon_js)
            page.locator('[data-tab="insert"]').click()
            page.locator("#dd-table").click()
            state = page.evaluate("""() => {
              const grid=document.getElementById('dd-table-grid');
              const rect=grid.getBoundingClientRect();
              const hit=document.elementFromPoint(rect.left+rect.width/2, rect.top+rect.height/2);
              return {height:rect.height, inViewport:rect.top>=0&&rect.bottom<=window.innerHeight, hitInside:grid.contains(hit)};
            }""")
            self.assertGreaterEqual(state["height"], 200)
            self.assertTrue(state["inViewport"])
            self.assertTrue(state["hitInside"])
            page.locator('#dd-table-grid button[data-rows="10"][data-columns="10"]').click()
            self.assertEqual(page.locator("#dd-sheet table tr").count(), 10)
            browser.close()

    def test_editor_sidebar_matches_shell_nav_styling(self):
        from playwright.sync_api import sync_playwright
        document = DigiDocDocument.objects.create(
            organization=self.organization, created_by=self.owner, title="Nav parity",
            content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
        )
        editor_markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        list_markup = self.client.get(reverse("digidoc_list")).content.decode("utf-8")
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        nav_styles_js = """() => {
          const links=Array.from(document.querySelectorAll('.app-nav__link'));
          const link=links.find(item=>!item.classList.contains('is-active'));
          const active=links.find(item=>item.classList.contains('is-active'));
          const icon=link.querySelector('.app-nav__icon');
          const activeIcon=active&&active.querySelector('.app-nav__icon');
          const iconStyle=getComputedStyle(icon);
          return {
            iconRadius:iconStyle.borderRadius,
            iconBg:iconStyle.backgroundColor,
            iconColor:iconStyle.color,
            linkColor:getComputedStyle(link).color,
            linkRadius:getComputedStyle(link).borderRadius,
            activeIconBg:activeIcon?getComputedStyle(activeIcon).backgroundColor:null,
            activeIconColor:activeIcon?getComputedStyle(activeIcon).color:null,
          };
        }"""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            def load(markup, stylesheet=None):
                markup = re.sub(r"<script[^>]*>.*?</script>", "", markup, flags=re.S)
                markup = re.sub(r"<link[^>]*>", "", markup)
                page.set_content(markup, wait_until="domcontentloaded")
                if stylesheet:
                    page.add_style_tag(content=stylesheet)
                page.add_style_tag(content="*,*::before,*::after{transition:none!important}")
                page.evaluate("() => document.querySelectorAll('#pageLoader').forEach(el => el.remove())")
                styles = page.evaluate(nav_styles_js)
                page.hover(".app-nav__link:not(.is-active)")
                styles["hoverBg"] = page.evaluate("() => getComputedStyle(document.querySelector('.app-nav__link:not(.is-active)')).backgroundColor")
                styles["hoverIconBg"] = page.evaluate("() => getComputedStyle(document.querySelector('.app-nav__link:not(.is-active) .app-nav__icon')).backgroundColor")
                return styles
            editor_styles = load(editor_markup, css)
            shell_styles = load(list_markup)
            self.assertEqual(editor_styles, shell_styles)
            browser.close()

    def test_docx_lists_use_numbering_definitions_and_preserve_nesting_and_restarts(self):
        paragraph = lambda value: {"type": "paragraph", "content": [{"type": "text", "text": value}]}
        item = lambda *children: {"type": "listItem", "content": list(children)}
        content = {"type": "doc", "content": [
            paragraph("Before"),
            {"type": "bulletList", "content": [
                item(paragraph("bullet one"), {"type": "bulletList", "content": [item(paragraph("nested bullet"))]}),
                item(paragraph("bullet two")),
            ]},
            {"type": "orderedList", "attrs": {"start": 4}, "content": [item(paragraph("number four")), item(paragraph("number five"))]},
            {"type": "orderedList", "content": [item(paragraph("restarted number"))]},
            paragraph("After"),
        ]}
        data = export_docx(content)
        archive = ZipFile(BytesIO(data))
        _assert_docx_integrity(self, data)
        self.assertIsNone(archive.testzip())
        self.assertIn("word/numbering.xml", archive.namelist())
        document = ElementTree.fromstring(archive.read("word/document.xml"))
        numbering = ElementTree.fromstring(archive.read("word/numbering.xml"))
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = document.findall(".//w:p", namespace)
        list_paragraphs = [node for node in paragraphs if "bullet" in "".join(node.itertext()).lower() or "number" in "".join(node.itertext()).lower()]
        self.assertEqual(len(list_paragraphs), 6)
        levels = [int(node.find("w:pPr/w:numPr/w:ilvl", namespace).get("{" + namespace["w"] + "}val")) for node in list_paragraphs]
        self.assertEqual(levels, [0, 1, 0, 0, 0, 0])
        num_ids = [node.find("w:pPr/w:numPr/w:numId", namespace).get("{" + namespace["w"] + "}val") for node in list_paragraphs]
        self.assertNotEqual(num_ids[3], num_ids[5])
        self.assertTrue(numbering.findall(".//w:abstractNum/w:lvl/w:numFmt[@w:val='bullet']", namespace))
        self.assertTrue(numbering.findall(".//w:abstractNum/w:lvl/w:numFmt[@w:val='decimal']", namespace))
        text_export = plain_text(content)
        self.assertIn("4. number four", text_export)
        self.assertIn("  \u2022 nested bullet", text_export)
        rtf_export = export_rtf(content)
        self.assertIn(b"4. number four", rtf_export)
        self.assertIn(b"\\li1440\\fi-360\\tx1440", rtf_export)
        pdf = _build_pdf(SimpleNamespace(title="List check", content_json=content, letterhead_enabled=False), self.organization)
        from pypdf import PdfReader
        pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("4.", pdf_text)
        self.assertIn("number four", pdf_text)

    def test_alphabetic_and_roman_list_styles_are_native_and_export_to_text(self):
        item = lambda value: {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": value}]}]}
        content = {"type": "doc", "content": [
            {"type": "orderedList", "attrs": {"list_style": "upper-alpha", "start": 4}, "content": [item("Alpha four"), item("Alpha five")]},
            {"type": "orderedList", "attrs": {"list_style": "lower-roman", "start": 2}, "content": [item("Roman two")]},
            {"type": "bulletList", "attrs": {"list_style": "square"}, "content": [item("Square item")]},
        ]}
        validate_document_json(content)
        text_export = plain_text(content)
        self.assertIn("D. Alpha four", text_export)
        self.assertIn("E. Alpha five", text_export)
        self.assertIn("ii. Roman two", text_export)
        archive = ZipFile(BytesIO(export_docx(content)))
        numbering = ElementTree.fromstring(archive.read("word/numbering.xml"))
        word_ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        self.assertTrue(numbering.findall('.//w:numFmt[@w:val="upperLetter"]', word_ns))
        self.assertTrue(numbering.findall('.//w:numFmt[@w:val="lowerRoman"]', word_ns))
        self.assertTrue(numbering.findall('.//w:lvlText[@w:val="\u25aa"]', word_ns))
        rtf_export = export_rtf(content)
        self.assertIn(b"D. Alpha four", rtf_export)
        self.assertIn(b"ii. Roman two", rtf_export)

    def test_docx_download_reopens_complex_and_edge_case_documents(self):
        image_buffer = BytesIO()
        Image.new("RGB", (12, 12), "navy").save(image_buffer, format="PNG")
        upload = self.client.post(reverse("digidoc_image_upload"), {
            "image": SimpleUploadedFile("docx-image.png", image_buffer.getvalue(), content_type="image/png"),
        })
        self.assertEqual(upload.status_code, 200, upload.content)
        asset_id = upload.json()["id"]
        tiny_png = image_buffer.getvalue()
        rich_text = {
            "type": "text", "text": "Unicode caf\u00e9 \u2014 \u65e5\u672c\u8a9e \U0001f600",
            "marks": [
                {"type": "bold"}, {"type": "italic"}, {"type": "underline"}, {"type": "strike"}, {"type": "superscript"}, {"type": "subscript"},
                {"type": "link", "attrs": {"href": "https://example.test/path?q=hello&lang=en"}},
                {"type": "fontFamily", "attrs": {"value": "Times-Roman"}},
                {"type": "fontSize", "attrs": {"value": 18}},
                {"type": "textColor", "attrs": {"color": "#336699"}},
                {"type": "highlight", "attrs": {"color": "#FFFF00"}},
            ],
        }
        comprehensive = {"type": "doc", "content": [
            {"type": "paragraph", "content": [rich_text]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": []},
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Parent item"}]},
                    {"type": "orderedList", "attrs": {"start": 3}, "content": [
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Nested numbered item"}]}]},
                    ]},
                ]},
            ]},
            {"type": "table", "content": [{"type": "tableRow", "content": [
                {"type": "tableCell", "content": [{"type": "text", "text": "Cell A"}]},
                {"type": "tableCell", "content": [{"type": "text", "text": "Cell B"}]},
            ]}]},
            {"type": "image", "attrs": {"asset_id": asset_id, "alt": "Test image"}},
        ]}
        snapshot = {"1": {"data": base64.b64encode(tiny_png).decode("ascii"), "meta": {
            "scale_mode": "fit", "margin_top_mm": 40, "margin_bottom_mm": 30,
            "margin_left_mm": 20, "margin_right_mm": 20,
        }}}
        long_content = []
        for page_index in range(49):
            long_content.extend([
                {"type": "paragraph", "content": [{"type": "text", "text": f"Long Unicode page {page_index + 1}: caf\u00e9 \u2014 \u65e5\u672c\u8a9e \U0001f600 " + "x" * 1800}]},
                {"type": "hardBreak"},
            ])
        long_content.append({"type": "paragraph", "content": [{"type": "text", "text": "Final page after forty-nine explicit breaks."}]})
        cases = [
            ("Complex document", comprehensive, True),
            ("Empty document", {"type": "doc", "content": []}, False),
            ("Empty list and table", {"type": "doc", "content": [
                {"type": "table", "content": [{"type": "tableRow", "content": [{"type": "tableCell", "content": []}]}]},
                {"type": "orderedList", "content": [{"type": "listItem", "content": []}]},
            ]}, False),
            ("Long Unicode document", {"type": "doc", "content": long_content}, False),
        ]
        for title, content, has_letterhead in cases:
            with self.subTest(title=title):
                document = DigiDocDocument.objects.create(
                    organization=self.organization, created_by=self.owner, title=title,
                    content_json=content, letterhead_enabled=has_letterhead,
                    letterhead_snapshot=snapshot if has_letterhead else {},
                )
                response = self.client.get(reverse("digidoc_export", args=[document.pk, "docx"]))
                self.assertEqual(response.status_code, 200, response.content[:300])
                self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                self.assertIn(f"filename=\"{title.replace(' ', '_')}.docx\"", response["Content-Disposition"])
                reopened = _assert_docx_integrity(self, response.content)
                if title == "Complex document":
                    self.assertTrue(any("Unicode caf\u00e9 \u2014 \u65e5\u672c\u8a9e \U0001f600" in paragraph.text for paragraph in reopened.paragraphs))
                    self.assertEqual(len(reopened.tables), 1)
                    self.assertEqual(len(reopened.inline_shapes), 1)
                    with ZipFile(BytesIO(response.content)) as archive:
                        xml = ElementTree.fromstring(archive.read("word/document.xml"))
                        word_ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                        for mark_tag in ("b", "i", "u", "strike", "vertAlign", "sz", "color", "shd"):
                            self.assertTrue(xml.findall(f".//w:{mark_tag}", word_ns), mark_tag)
                        self.assertTrue(xml.findall(".//w:hyperlink", word_ns))
                        relations = ElementTree.fromstring(archive.read("word/_rels/document.xml.rels"))
                        self.assertTrue(any("https://example.test/path" in (relation.get("Target") or "") for relation in relations))
                        numbering = ElementTree.fromstring(archive.read("word/numbering.xml"))
                        self.assertTrue(numbering.findall('.//w:lvlOverride[@w:ilvl="1"]/w:startOverride[@w:val="3"]', word_ns))

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

    def test_inline_format_toggle_stays_under_50ms_on_fifty_pages(self):
        from playwright.sync_api import sync_playwright

        blocks = [{"type": "paragraph", "content": [{"type": "text", "text": "Page one formatting target"}]}]
        for index in range(49):
            blocks.extend([{"type": "hardBreak"}, {"type": "paragraph", "content": [{"type": "text", "text": f"Generated page {index + 2} content"}]}])
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="50-page format timing", content_json={"type": "doc", "content": blocks})
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", markup)
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        shell_js = Path("attendance/static/attendance/digidoc-shell.js").read_text(encoding="utf-8")
        editor_js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        ribbon_js = Path("attendance/static/attendance/digidoc-ribbon.js").read_text(encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_content(markup, wait_until="domcontentloaded")
            page.add_style_tag(content=css)
            page.add_script_tag(content=shell_js)
            page.add_script_tag(content=editor_js)
            self.assertEqual(page.locator(".dd-page").count(), 50)
            timings = page.evaluate("""() => {
              const target=document.querySelector('#dd-sheet .dd-page p');
              const selection=window.getSelection();
              const measure=command=>{
                const button=document.querySelector(`[data-command="${command}"]`);
                return Array.from({length:8},()=>{
                  const range=document.createRange();range.selectNodeContents(target);
                  selection.removeAllRanges();selection.addRange(range);
                  const start=performance.now();button.click();return performance.now()-start;
                });
              };
              return {bold:measure('bold'),italic:measure('italic')};
            }""")
            for kind, samples in timings.items():
                median = (sorted(samples)[3] + sorted(samples)[4]) / 2
                print(f"50-page {kind} toggle timings (ms): {samples}; median={median:.2f}; max={max(samples):.2f}")
                self.assertLessEqual(max(samples), 50, f"{kind} toggle timings exceeded 50 ms: {samples}")
            browser.close()

    def test_autocorrect_and_autocapitalization_undo_immediately(self):
        from playwright.sync_api import sync_playwright

        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", markup)
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        editor_js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(markup)
            page.add_style_tag(content=css)
            page.add_script_tag(content=editor_js)
            paragraph = page.locator("#dd-sheet p").first
            state = paragraph.evaluate("el => { el.replaceChildren(); const text=document.createTextNode('teh '); el.append(text); const range=document.createRange(); range.setStart(text,4); range.collapse(true); const selection=window.getSelection(); selection.removeAllRanges(); selection.addRange(range); document.querySelector('#dd-sheet').dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:' '})); return text; }")
            self.assertEqual(paragraph.evaluate("el => el.textContent"), "the ")
            page.evaluate("() => document.querySelector('#dd-sheet').dispatchEvent(new KeyboardEvent('keydown',{key:'Backspace',bubbles:true,cancelable:true}))")
            self.assertEqual(paragraph.inner_text(), "teh")
            paragraph.evaluate("el => { const text=el.firstChild; text.data='teh dont '; const range=document.createRange(); range.setStart(text,text.length); range.collapse(true); const selection=window.getSelection(); selection.removeAllRanges(); selection.addRange(range); document.querySelector('#dd-sheet').dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:' '})); }")
            self.assertTrue(paragraph.evaluate("el => el.textContent").endswith("don't "), paragraph.evaluate("el => el.textContent"))
            page.evaluate("() => document.querySelector('#dd-sheet').dispatchEvent(new KeyboardEvent('keydown',{key:'z',ctrlKey:true,bubbles:true,cancelable:true}))")
            self.assertTrue(paragraph.evaluate("el => el.textContent").endswith(" dont "))
            paragraph.evaluate("el => { const text=el.firstChild; text.data='hello. w'; const range=document.createRange(); range.setStart(text,8); range.collapse(true); const selection=window.getSelection(); selection.removeAllRanges(); selection.addRange(range); document.querySelector('#dd-sheet').dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'w'})); }")
            self.assertEqual(paragraph.evaluate("el => el.textContent"), "hello. W")
            paragraph.evaluate("el => { const text=el.firstChild; text.data='Dr. s'; const range=document.createRange(); range.setStart(text,5); range.collapse(true); const selection=window.getSelection(); selection.removeAllRanges(); selection.addRange(range); document.querySelector('#dd-sheet').dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'s'})); }")
            self.assertEqual(paragraph.evaluate("el => el.textContent"), "Dr. s")
            browser.close()

    def test_layout_controls_apply_page_margin_spacing_and_letterhead_rules(self):
        from playwright.sync_api import sync_playwright

        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, title="Layout controls", content_json={"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Select this paragraph"}]}]})
        markup = self.client.get(reverse("digidoc_editor", args=[document.pk])).content.decode("utf-8")
        markup = re.sub(r"<script[^>]*src=[^>]*></script>", "", markup)
        css = Path("attendance/static/attendance/digidoc.css").read_text(encoding="utf-8")
        shell_js = Path("attendance/static/attendance/digidoc-shell.js").read_text(encoding="utf-8")
        editor_js = Path("attendance/static/attendance/digidoc-editor.js").read_text(encoding="utf-8")
        ribbon_js = Path("attendance/static/attendance/digidoc-ribbon.js").read_text(encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.add_init_script("window.fetch=async()=>new Response(JSON.stringify({version:1,updated_at:'Saved'}),{status:200,headers:{'Content-Type':'application/json'}})")
            page.set_content(markup, wait_until="domcontentloaded")
            page.add_style_tag(content=css)
            page.add_script_tag(content=shell_js)
            page.add_script_tag(content=editor_js)
            page.add_script_tag(content=ribbon_js)
            page.locator('[data-tab="layout"]').click()
            page.locator("#dd-page-size").select_option("A3")
            self.assertEqual(page.locator("#dd-sheet > .dd-page").evaluate("el => Math.round(el.getBoundingClientRect().width)"), 1123)
            page.locator("#dd-orientation").select_option("landscape")
            self.assertEqual(page.locator("#dd-sheet > .dd-page").evaluate("el => Math.round(el.getBoundingClientRect().width)"), 1587)
            page.locator("#dd-margin-preset").select_option("Narrow")
            self.assertEqual(page.locator("#dd-margin-left").input_value(), "1.27")
            page.locator("#dd-margin-top").fill("3.2")
            page.locator("#dd-margin-top").dispatch_event("change")
            self.assertEqual(page.locator("#dd-margin-preset").input_value(), "Custom")
            self.assertEqual(page.locator("#dd-sheet > .dd-page").evaluate("el => Math.round(parseFloat(getComputedStyle(el).paddingTop))"), 121)
            page.evaluate("""() => {
              const box=document.querySelector('#dd-sheet > .dd-page p'),selection=getSelection(),range=document.createRange();
              range.selectNodeContents(box);selection.removeAllRanges();selection.addRange(range);
              const company=document.querySelector('#dd-letterhead-menu');company.dataset.letterheadAvailable='true';company.disabled=false;
              const letterhead=document.querySelector('#dd-letterhead');letterhead.disabled=false;letterhead.checked=true;
              window.confirm=()=>false;
            }""")
            page.locator("#dd-page-size").select_option("Letter")
            self.assertEqual(page.locator("#dd-page-size").input_value(), "A3")
            self.assertTrue(page.locator("#dd-letterhead").is_checked())
            page.evaluate("window.confirm=()=>true")
            page.locator("#dd-page-size").select_option("Letter")
            self.assertFalse(page.locator("#dd-letterhead").is_checked())
            self.assertEqual(page.locator("#dd-page-size").input_value(), "Letter")
            self.assertIn("A4 portrait", page.locator("#dd-letterhead-layout-note").text_content())
            page.locator('[data-tab="layout"]').click()
            page.locator("#dd-space-before").fill("200")
            page.locator("#dd-space-before").dispatch_event("change")
            self.assertEqual(page.locator("#dd-sheet p").first.get_attribute("data-space-before-pt"), "200")
            page.locator("#dd-indent-left-cm").fill("2.4")
            page.locator("#dd-indent-left-cm").dispatch_event("change")
            self.assertEqual(page.locator("#dd-sheet p").first.get_attribute("data-indent-left-cm"), "2.4")
            browser.close()

    def test_editor_splits_a_paragraph_at_the_footer_instead_of_moving_it_whole(self):
        from playwright.sync_api import sync_playwright
        document = DigiDocDocument.objects.create(
            organization=self.organization,
            created_by=self.owner,
            title="Footer flow check",
            content_json={"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "first paragraph " * 160}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "SECOND_START " + ("continuation " * 100) + " SECOND_END"}]},
            ]},
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
            first_page = page.locator("#dd-sheet > .dd-page").nth(0)
            second_page = page.locator("#dd-sheet > .dd-page").nth(1)
            self.assertIn("SECOND_START", first_page.inner_text())
            self.assertIn("SECOND_END", second_page.inner_text())
            combined = page.locator("#dd-sheet").evaluate("el => [...el.querySelectorAll(':scope > .dd-page')].map(p => [...p.childNodes].filter(n => !n.classList?.contains('dd-page-zones')).map(n => n.textContent).join('')).join('')")
            self.assertEqual(combined, ("first paragraph " * 160) + "SECOND_START " + ("continuation " * 100) + " SECOND_END")
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
            self.assertNotIn("**", page.locator("#dd-sheet").evaluate("el => el.innerHTML"))
            self.assertNotIn("###", page.locator("#dd-sheet").evaluate("el => el.innerHTML"))
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
            self.assertNotIn("boundary", page.locator("#dd-sheet").evaluate("el => el.innerHTML"))
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
            page.locator("#dd-sheet .dd-page p").first.evaluate("p => { p.textContent = 'w'.repeat(14000); const range = document.createRange(); range.selectNodeContents(p); range.collapse(false); const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); p.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:'w'})); }")
            page.wait_for_function("document.querySelectorAll('#dd-sheet > .dd-page').length > 1")
            selection_page = page.evaluate("() => getSelection().anchorNode.parentElement.closest('.dd-page')?.dataset.pageNumber")
            self.assertEqual(selection_page, str(page.locator("#dd-sheet > .dd-page").count()), "Pagination should keep the caret at the end of the flowed text")
            page.keyboard.press("Enter")
            page.keyboard.type("Continued on the next page")
            selection_page = page.evaluate("() => getSelection().anchorNode.parentElement.closest('.dd-page')?.dataset.pageNumber")
            final_page = page.locator("#dd-sheet > .dd-page").count()
            self.assertEqual(selection_page, str(final_page), "Typing at the end of flowed text should keep the caret on its continuation page")
            self.assertIn("Continued on the next page", page.locator("#dd-sheet > .dd-page").last.inner_text())
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
            self.assertEqual(page.locator("#dd-font-size").get_attribute("min"), "8")
            self.assertEqual(page.locator("#dd-font-size").get_attribute("max"), "96")
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
            page.locator('[data-tab="home"]').click()
            for width, height in ((1440, 900), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.locator("#dd-download-toggle").click()
                menu = page.locator("#dd-download-menu")
                page.wait_for_timeout(50)
                bounds = menu.evaluate("el => { const r=el.getBoundingClientRect(); return {left:r.left,right:r.right,top:r.top,bottom:r.bottom}; }")
                self.assertGreaterEqual(bounds["left"], 0)
                self.assertLessEqual(bounds["right"], width)
                self.assertTrue(menu.locator('[role="menuitem"]').first.is_visible())
                for index in range(menu.locator('[role="menuitem"]').count()):
                    item = menu.locator('[role="menuitem"]').nth(index)
                    hit_test = item.evaluate("el => { const r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.left+Math.min(8,r.width/2),r.top+r.height/2);return {ok:el.contains(hit),box:{left:r.left,right:r.right,top:r.top,bottom:r.bottom},hit:hit&&hit.outerHTML.slice(0,120)}; }")
                    self.assertTrue(hit_test["ok"], f"Viewport {width}, menu item {index}: {hit_test}")
                page.screenshot(path=str(output / f"dropdown-after-{width}.png"), full_page=True)
                page.keyboard.press("Escape")
                self.assertFalse(page.locator("#dd-download").evaluate("el => el.open"))
            page.locator("#dd-download-toggle").focus()
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(30)
            self.assertEqual(page.evaluate("document.activeElement.textContent.trim()"), "PDF")
            page.keyboard.press("End")
            self.assertIn(".txt", page.evaluate("document.activeElement.textContent").lower())
            page.keyboard.press("Escape")
            self.assertTrue(page.locator("#dd-download-toggle").evaluate("el => el === document.activeElement"))
            self.assertEqual(page_errors, [])
            browser.close()

    def test_writing_assistance_defaults_are_visible_and_company_rules_are_validated(self):
        document = DigiDocDocument.objects.create(organization=self.organization, created_by=self.owner, content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        editor = self.client.get(reverse("digidoc_editor", args=[document.pk]))
        self.assertEqual(editor.status_code, 200)
        self.assertContains(editor, 'id="dd-autocapitalize" type="checkbox" checked')
        self.assertContains(editor, 'id="dd-autocorrect" type="checkbox" checked')
        self.assertContains(editor, 'id="dd-language"')
        settings_url = reverse("digidoc_writing_settings")
        page = self.client.get(settings_url)
        self.assertEqual(page.status_code, 200)
        saved = self.client.post(settings_url, {
            "language": "en-NG", "autocapitalize_enabled": "on", "autocorrect_enabled": "on",
            "spellcheck_enabled": "on", "rules": "teh => the\ndont => don't",
        })
        self.assertEqual(saved.status_code, 200)
        settings = DigiDocWritingSettings.objects.get(organization=self.organization)
        self.assertEqual(settings.language, "en-NG")
        self.assertEqual(settings.autocorrect_rules, [{"from": "teh", "to": "the"}, {"from": "dont", "to": "don't"}])
        from attendance.digidoc import _validated_autocorrect_rules
        for malicious in ("x => <script>", "x => javascript:alert(1)", "same => same", "x\u202ey => bad"):
            with self.subTest(malicious=malicious), self.assertRaises(ValidationError):
                _validated_autocorrect_rules(malicious)

    def test_font_allowlist_includes_phase_two_families_and_size_ceiling(self):
        for family in ("Arimo", "Tinos", "Cousine", "Carlito", "Caladea", "Noto Sans", "Noto Serif", "Lora", "Raleway", "EB Garamond", "Libre Baskerville", "PT Serif", "Crimson Text"):
            validate_document_json({"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Font", "marks": [{"type": "fontFamily", "attrs": {"value": family}}]}]}]})
        validate_document_json({"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Big", "marks": [{"type": "fontSize", "attrs": {"value": 96}}]}]}]})
        with self.assertRaises(ValidationError):
            validate_document_json({"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Too big", "marks": [{"type": "fontSize", "attrs": {"value": 97}}]}]}]})

    def test_pdf_embeds_the_self_hosted_font_used_by_a_text_run(self):
        content = {"type": "doc", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": "Arimo embedded", "marks": [{"type": "fontFamily", "attrs": {"value": "Arimo"}}]},
            {"type": "text", "text": " and PT Serif embedded", "marks": [{"type": "fontFamily", "attrs": {"value": "PT Serif"}}]},
        ]}]}
        document = SimpleNamespace(title="Embedded fonts", content_json=content, letterhead_enabled=False)
        from pypdf import PdfReader
        pdf = _build_pdf(document, self.organization)
        fonts = PdfReader(BytesIO(pdf)).pages[0]["/Resources"]["/Font"].get_object()
        embedded = []
        for font in fonts.values():
            font = font.get_object()
            descriptor = font.get("/FontDescriptor")
            if descriptor is None and font.get("/DescendantFonts"):
                descriptor = font["/DescendantFonts"][0].get_object().get("/FontDescriptor")
            if descriptor is not None and "/FontFile2" in descriptor.get_object():
                embedded.append(str(font.get("/BaseFont", "")))
        self.assertTrue(any("Arimo" in name for name in embedded), embedded)
        self.assertTrue(any("PTSerif" in name for name in embedded), embedded)
