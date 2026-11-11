"""Company-scoped DigiDoc document views and strict editor JSON handling."""

import html
import json
import logging
import math
import re
import secrets
import unicodedata
import uuid
import base64
import ctypes
import os
import subprocess
import sys
import zipfile
from types import SimpleNamespace
from urllib.parse import quote
from datetime import timedelta
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import json_script
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, A5, A3, letter as LETTER, legal as LEGAL, landscape as page_landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Image as PdfImage, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .digidoc_exports import docx as export_docx, odt as export_odt, plain_text as export_text, rtf_text as export_rtf
from .models import AuditLog, CompanyLetterhead, DigiDocDocument, DigiDocImageAsset, DigiDocWritingSettings, OrganizationMembership, PersonalLetterhead, default_digidoc_autocorrect_rules
from .organization import DIGIDOC_ROLES, HR_ROLES
from .shell import shell_context

logger = logging.getLogger(__name__)


MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 20
MAX_NODES = 10000
MAX_TITLE = 200
MAX_PAGES = 50
MAX_MARKS = 12
MAX_FLOATING_IMAGES = 20
ALLOWED_TYPES = {"doc", "paragraph", "heading", "text", "hardBreak", "horizontalRule", "bulletList", "orderedList", "listItem", "table", "tableRow", "tableCell", "image"}
ALLOWED_MARKS = {"bold", "italic", "underline", "strike", "superscript", "subscript", "link", "fontFamily", "fontSize", "textColor", "highlight"}
ALIGNMENTS = {"left", "center", "right", "justify"}
FONT_FAMILIES = {
    "Helvetica", "Times-Roman", "Courier", "Roboto", "Open Sans", "Lato",
    "Montserrat", "Merriweather", "Nunito", "Oswald", "Source Sans 3",
    "Poppins", "Playfair Display", "Roboto Mono", "Inter",
    "Arimo", "Tinos", "Cousine", "Carlito", "Caladea", "Noto Sans", "Noto Serif",
    "Lora", "Raleway", "EB Garamond", "Libre Baskerville", "PT Serif", "Crimson Text",
}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LINE_SPACING = {"single", "1.15", "1.5", "double"}
PAGE_SIZES = {"A4", "A5", "A3", "Letter", "Legal"}
PAGE_SIZE_POINTS = {"A4": A4, "A5": A5, "A3": A3, "Letter": LETTER, "Legal": LEGAL}
PAGE_ORIENTATIONS = {"portrait", "landscape"}
MARGIN_KEYS = {"top_cm", "right_cm", "bottom_cm", "left_cm"}
PARAGRAPH_SPACING_KEYS = {"space_before_pt", "space_after_pt"}
PARAGRAPH_INDENT_KEYS = {"left_indent_cm", "right_indent_cm", "first_line_indent_cm"}
CHILDREN = {
    "doc": {"paragraph", "heading", "bulletList", "orderedList", "table", "image", "hardBreak", "horizontalRule"},
    "paragraph": {"text", "hardBreak", "image"}, "heading": {"text", "hardBreak"},
    "bulletList": {"listItem"}, "orderedList": {"listItem"},
    "listItem": {"paragraph", "bulletList", "orderedList"},
    "table": {"tableRow"}, "tableRow": {"tableCell"}, "tableCell": {"text", "hardBreak"},
}


def _scope(request):
    # Never let employee-profile inference, staff flags, or superuser status
    # create a DigiDoc tenant context.
    organization_id = request.session.get("active_organization_id")
    memberships = request.user.organization_memberships.filter(is_active=True, role__in=DIGIDOC_ROLES, organization__is_active=True)
    membership = memberships.filter(organization_id=organization_id).first() if organization_id else None
    if not membership:
        membership = memberships.order_by("organization__name").first()
    if not membership:
        raise PermissionDenied
    from .models import Organization
    organization = Organization.objects.get(pk=membership.organization_id)
    if membership.role not in HR_ROLES and not organization.allow_staff_digidoc:
        raise PermissionDenied("DigiDoc is disabled for staff in this company.")
    return organization


def _owned_document(request, organization, document_id):
    document = DigiDocDocument.objects.filter(pk=document_id, organization=organization).first()
    if document and document.created_by_id == request.user.pk:
        return document
    if document and document.created_by_id is None and request.user.organization_memberships.filter(organization=organization, is_active=True, role__in=HR_ROLES).exists():
        return document
    raise PermissionDenied


def _letterhead_snapshot(letterhead):
    if not letterhead:
        return {}
    snapshot = {}
    for slot, field_name in (("1", "image"), ("2", "image_second")):
        image = getattr(letterhead, field_name)
        if image:
            with image.open("rb") as source:
                data = source.read(8 * 1024 * 1024 + 1)
            if not data or len(data) > 8 * 1024 * 1024:
                raise ValidationError("The saved letterhead exceeds the PDF input limit.")
            snapshot[slot] = {
                "data": base64.b64encode(data).decode("ascii"),
                "meta": {"scale_mode": letterhead.scale_mode, "margin_top_mm": letterhead.margin_top_mm,
                         "margin_bottom_mm": letterhead.margin_bottom_mm, "margin_left_mm": letterhead.margin_left_mm,
                         "margin_right_mm": letterhead.margin_right_mm},
            }
    return snapshot


def _personal_letterhead_snapshot(letterhead):
    if not letterhead:
        return {}
    with letterhead.image.open("rb") as source:
        data = source.read(8 * 1024 * 1024 + 1)
    if not data or len(data) > 8 * 1024 * 1024:
        raise ValidationError("The saved personal letterhead exceeds the PDF input limit.")
    return {"1": {"data": base64.b64encode(data).decode("ascii"), "meta": {
        "scale_mode": "fit", "margin_top_mm": 40, "margin_bottom_mm": 30,
        "margin_left_mm": 20, "margin_right_mm": 20,
    }}}


def _snapshot_letterhead_display(snapshot):
    if not snapshot:
        return None
    meta = (snapshot.get("1") or next(iter(snapshot.values())))['meta']
    return SimpleNamespace(
        scale_mode=meta["scale_mode"], margin_top_mm=meta["margin_top_mm"],
        margin_bottom_mm=meta["margin_bottom_mm"], margin_left_mm=meta["margin_left_mm"],
        margin_right_mm=meta["margin_right_mm"], image="1" in snapshot,
        image_second="2" in snapshot,
    )


def _clean_title(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = "".join(ch for ch in value if unicodedata.category(ch) not in {"Cc", "Cf", "Cs"})
    return " ".join(value.split())[:MAX_TITLE] or "Untitled document"


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValidationError("Invalid document link.")
    if not re.match(r"^(https?://|mailto:)[^\s<>]+$", value, re.I):
        raise ValidationError("Only web and email links are allowed.")
    return value


def validate_document_json(value):
    """Accept only the small, typed document tree understood by this editor."""
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValidationError("The document data is invalid.") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise ValidationError("The document exceeds the 2 MB limit.")
    count = [0]
    image_count = [0]
    page_breaks = [0]
    floating_images = [0]

    def visit(node, depth=0, list_depth=0):
        count[0] += 1
        if count[0] > MAX_NODES or depth > MAX_DEPTH or not isinstance(node, dict):
            raise ValidationError("The document structure is too large or deeply nested.")
        kind = node.get("type")
        if not isinstance(kind, str) or kind not in ALLOWED_TYPES:
            raise ValidationError("Unsupported document element.")
        allowed_keys = {"type", "content"}
        if kind == "doc":
            allowed_keys.add("attrs")
        if kind == "text":
            allowed_keys |= {"text", "marks"}
        if kind == "heading":
            allowed_keys |= {"level", "content", "attrs"}
        if kind in {"paragraph", "tableCell", "bulletList", "orderedList"}:
            allowed_keys |= {"attrs"}
        if kind == "image":
            allowed_keys |= {"attrs"}
        if set(node) - allowed_keys:
            raise ValidationError("Unsupported document property.")
        cleaned = {"type": kind}
        if kind == "text":
            text = node.get("text", "")
            if not isinstance(text, str) or len(text) > 100000:
                raise ValidationError("Text is too long.")
            cleaned["text"] = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in {"Cc", "Cf", "Cs"})
            marks = node.get("marks", [])
            if not isinstance(marks, list) or len(marks) > MAX_MARKS:
                raise ValidationError("Invalid text formatting.")
            clean_marks = []
            for mark in marks:
                if not isinstance(mark, dict) or not isinstance(mark.get("type"), str) or mark.get("type") not in ALLOWED_MARKS or set(mark) - {"type", "attrs"}:
                    raise ValidationError("Unsupported text formatting.")
                item = {"type": mark["type"]}
                if mark["type"] == "link":
                    attrs = mark.get("attrs")
                    if not isinstance(attrs, dict) or set(attrs) != {"href"}:
                        raise ValidationError("Invalid link formatting.")
                    item["attrs"] = {"href": _safe_url(attrs["href"])}
                elif mark["type"] in {"fontFamily", "fontSize", "textColor", "highlight"}:
                    attrs = mark.get("attrs")
                    key = {"fontFamily": "value", "fontSize": "value", "textColor": "color", "highlight": "color"}[mark["type"]]
                    if not isinstance(attrs, dict) or set(attrs) != {key}:
                        raise ValidationError("Invalid text formatting.")
                    value = attrs[key]
                    if mark["type"] == "fontFamily" and (not isinstance(value, str) or value not in FONT_FAMILIES):
                        raise ValidationError("Unsupported font family.")
                    if mark["type"] == "fontSize" and (type(value) is not int or not 8 <= value <= 96):
                        raise ValidationError("Font size must be an integer from 8 to 96 pt.")
                    if mark["type"] in {"textColor", "highlight"} and (not isinstance(value, str) or not COLOR_RE.fullmatch(value)):
                        raise ValidationError("Unsupported text colour.")
                    item["attrs"] = {key: value.upper() if key == "color" else value}
                elif "attrs" in mark:
                    raise ValidationError("Unsupported formatting property.")
                clean_marks.append(item)
            if clean_marks:
                cleaned["marks"] = clean_marks
            return cleaned
        if kind == "heading":
            level = node.get("level", 1)
            if type(level) is not int or level not in {1, 2, 3}:
                raise ValidationError("Unsupported heading level.")
            cleaned["level"] = level
        if kind == "hardBreak":
            page_breaks[0] += 1
            if page_breaks[0] >= MAX_PAGES:
                raise ValidationError("A document can contain up to 50 pages.")
        attrs = node.get("attrs")
        if "attrs" in node and attrs is None:
            raise ValidationError("Element properties must be an object.")
        if kind == "image" and attrs is None:
            raise ValidationError("Image references are required.")
        if attrs is not None:
            if not isinstance(attrs, dict):
                raise ValidationError("Unsupported element property.")
            if kind == "image":
                image_attrs = {"asset_id", "alt", "width_percent", "align", "crop", "layout", "wrap_side", "margin_pt", "anchor", "x_pt", "y_pt", "space_before_pt", "space_after_pt"}
                if not {"asset_id", "alt"} <= set(attrs) or set(attrs) - image_attrs:
                    raise ValidationError("Invalid image reference.")
                if any(isinstance(item, str) and "\x00" in item for item in attrs.values()):
                    raise ValidationError("Image properties cannot contain null bytes.")
                if any(isinstance(item, str) and re.search(r"(?:url\s*\(|https?://|data:|javascript:)", item, re.I) for item in attrs.values()):
                    raise ValidationError("Image properties cannot contain URLs or CSS values.")
                try:
                    if not isinstance(attrs["asset_id"], str):
                        raise ValueError("asset_id must be text")
                    asset_id = str(uuid.UUID(attrs["asset_id"]))
                except (ValueError, TypeError, AttributeError) as exc:
                    raise ValidationError("Invalid image reference.") from exc
                alt = attrs.get("alt", "")
                if not isinstance(alt, str) or len(alt) > 300:
                    raise ValidationError("Invalid image description.")
                image_count[0] += 1
                if image_count[0] > 30:
                    raise ValidationError("A document can contain up to 30 images.")
                width_percent = attrs.get("width_percent", 100)
                alignment = attrs.get("align", "center")
                crop = attrs.get("crop", "none")
                layout = attrs.get("layout", "inline")
                wrap_side = attrs.get("wrap_side", "right")
                margin_pt = attrs.get("margin_pt", 0)
                anchor = attrs.get("anchor", "paragraph")
                x_pt = attrs.get("x_pt", 0)
                y_pt = attrs.get("y_pt", 0)
                space_before_pt = attrs.get("space_before_pt", 0)
                space_after_pt = attrs.get("space_after_pt", 0)
                if type(width_percent) is not int or not 10 <= width_percent <= 100:
                    raise ValidationError("Image width must be between 10 and 100 percent.")
                if not isinstance(alignment, str) or alignment not in {"left", "center", "right"}:
                    raise ValidationError("Unsupported image alignment.")
                if not isinstance(crop, str) or crop not in {"none", "square", "landscape", "portrait"}:
                    raise ValidationError("Unsupported image crop shape.")
                if not isinstance(layout, str) or layout not in {"inline", "wrap", "break", "behind", "front"}:
                    raise ValidationError("Unsupported image layout.")
                if not isinstance(wrap_side, str) or wrap_side not in {"left", "right"}:
                    raise ValidationError("Unsupported image wrap side.")
                if not isinstance(anchor, str) or anchor not in {"paragraph", "page"}:
                    raise ValidationError("Unsupported image anchor.")
                for field, field_value, low, high in (
                    ("margin_pt", margin_pt, 0, 72), ("x_pt", x_pt, 0, 2000),
                    ("y_pt", y_pt, 0, 2000), ("space_before_pt", space_before_pt, 0, 200),
                    ("space_after_pt", space_after_pt, 0, 200),
                ):
                    if type(field_value) is not int or not low <= field_value <= high:
                        raise ValidationError(f"Invalid image {field.replace('_', ' ')}.")
                if layout in {"wrap", "behind", "front"}:
                    floating_images[0] += 1
                    if floating_images[0] > MAX_FLOATING_IMAGES:
                        raise ValidationError("A document can contain up to 20 floating images.")
                cleaned["attrs"] = {
                    "asset_id": asset_id,
                    "alt": "".join(ch for ch in alt if ch in "\n\t" or unicodedata.category(ch) not in {"Cc", "Cf", "Cs"}),
                    "width_percent": width_percent,
                    "align": alignment,
                    "crop": crop,
                    "layout": layout,
                    "wrap_side": wrap_side,
                    "margin_pt": margin_pt,
                    "anchor": anchor,
                    "x_pt": x_pt,
                    "y_pt": y_pt,
                    "space_before_pt": space_before_pt,
                    "space_after_pt": space_after_pt,
                }
            elif kind == "doc":
                allowed_attrs = {"page_size", "orientation", "margins"}
                if set(attrs) - allowed_attrs:
                    raise ValidationError("Unsupported page layout property.")
                clean_attrs = {}
                if "page_size" in attrs:
                    if not isinstance(attrs["page_size"], str) or attrs["page_size"] not in PAGE_SIZES:
                        raise ValidationError("Unsupported page size.")
                    clean_attrs["page_size"] = attrs["page_size"]
                if "orientation" in attrs:
                    if not isinstance(attrs["orientation"], str) or attrs["orientation"] not in PAGE_ORIENTATIONS:
                        raise ValidationError("Unsupported page orientation.")
                    clean_attrs["orientation"] = attrs["orientation"]
                if "margins" in attrs:
                    margins = attrs["margins"]
                    if not isinstance(margins, dict) or set(margins) != MARGIN_KEYS:
                        raise ValidationError("Invalid page margins.")
                    clean_margins = {}
                    for field, value in margins.items():
                        if type(value) not in {int, float} or not math.isfinite(value) or not 0.5 <= value <= 5.5:
                            raise ValidationError("Page margins must be between 0.5 and 5.5 cm.")
                        clean_margins[field] = round(float(value), 2)
                    clean_attrs["margins"] = clean_margins
                cleaned["attrs"] = clean_attrs
            else:
                if kind in {"paragraph", "heading", "tableCell"}:
                    allowed_attrs = {"align", "indent", "line_spacing", "style"} | PARAGRAPH_SPACING_KEYS | PARAGRAPH_INDENT_KEYS
                elif kind == "bulletList":
                    allowed_attrs = {"list_style"}
                elif kind == "orderedList":
                    allowed_attrs = {"start", "list_style"}
                else:
                    allowed_attrs = set()
                if set(attrs) - allowed_attrs:
                    raise ValidationError("Unsupported element property.")
                clean_attrs = {}
                if "list_style" in attrs:
                    choices = {"disc", "circle", "square", "checklist"} if kind == "bulletList" else {"decimal", "lower-alpha", "upper-alpha", "lower-roman", "upper-roman"} if kind == "orderedList" else set()
                    if attrs["list_style"] not in choices:
                        raise ValidationError("Unsupported list style.")
                    clean_attrs["list_style"] = attrs["list_style"]
                if "align" in attrs:
                    if not isinstance(attrs["align"], str) or attrs["align"] not in ALIGNMENTS:
                        raise ValidationError("Unsupported alignment.")
                    clean_attrs["align"] = attrs["align"]
                if "indent" in attrs:
                    if type(attrs["indent"]) is not int or attrs["indent"] not in range(5):
                        raise ValidationError("Unsupported paragraph indent.")
                    clean_attrs["indent"] = attrs["indent"]
                if "line_spacing" in attrs:
                    if not isinstance(attrs["line_spacing"], str) or attrs["line_spacing"] not in LINE_SPACING:
                        raise ValidationError("Unsupported line spacing.")
                    clean_attrs["line_spacing"] = attrs["line_spacing"]
                if "style" in attrs:
                    styles = {"normal", "subtitle"} if kind == "paragraph" else {"title"}
                    if attrs["style"] not in styles:
                        raise ValidationError("Unsupported paragraph style.")
                    clean_attrs["style"] = attrs["style"]
                if "start" in attrs:
                    if type(attrs["start"]) is not int or not 1 <= attrs["start"] <= 9999:
                        raise ValidationError("Ordered list start must be from 1 to 9999.")
                    clean_attrs["start"] = attrs["start"]
                for field in PARAGRAPH_SPACING_KEYS:
                    if field in attrs:
                        if type(attrs[field]) is not int or not 0 <= attrs[field] <= 200:
                            raise ValidationError("Paragraph spacing must be an integer from 0 to 200 pt.")
                        clean_attrs[field] = attrs[field]
                for field in PARAGRAPH_INDENT_KEYS:
                    if field in attrs:
                        value = attrs[field]
                        low = -2.54 if field == "first_line_indent_cm" else 0
                        if type(value) not in {int, float} or not math.isfinite(value) or not low <= value <= 10:
                            raise ValidationError("Paragraph indents are outside the allowed range.")
                        clean_attrs[field] = round(float(value), 2)
                cleaned["attrs"] = clean_attrs
        children = node.get("content", [])
        if not isinstance(children, list) or len(children) > MAX_NODES:
            raise ValidationError("Invalid document contents.")
        if kind in {"doc", "paragraph", "heading", "bulletList", "orderedList", "listItem", "table", "tableRow", "tableCell"}:
            allowed_children = CHILDREN.get(kind, set())
            if any(not isinstance(child, dict) or not isinstance(child.get("type"), str) or child.get("type") not in allowed_children for child in children):
                raise ValidationError("This document element contains an unsupported child.")
            if kind == "table" and len(children) > 100:
                raise ValidationError("A table can have up to 100 rows.")
            if kind == "tableRow" and len(children) > 20:
                raise ValidationError("A table row can have up to 20 cells.")
            next_list_depth = list_depth + (1 if kind in {"bulletList", "orderedList"} else 0)
            if next_list_depth > 9:
                raise ValidationError("Lists can be nested up to 9 levels.")
            cleaned["content"] = [visit(child, depth + 1, next_list_depth) for child in children]
        elif children:
            raise ValidationError("This element cannot have child content.")
        return cleaned

    result = visit(value)
    if result["type"] != "doc":
        raise ValidationError("Invalid document root.")
    return result


def _ensure_company_images(content, organization):
    image_ids = []
    def walk(node):
        if node["type"] == "image": image_ids.append(node["attrs"]["asset_id"])
        for child in node.get("content", []): walk(child)
    walk(content)
    found = set(str(value) for value in DigiDocImageAsset.objects.filter(organization=organization, pk__in=image_ids).values_list("pk", flat=True))
    if found != set(image_ids):
        raise ValidationError("One or more document images are unavailable.")


def _doc_context(request, organization, **extra):
    return {"organization": organization, "page_title": "DigiDoc", **shell_context(request, organization), **extra}


@login_required
def digidoc_list(request):
    organization = _scope(request)
    query = _clean_title(request.GET.get("q", "")) if request.GET.get("q") else ""
    documents = DigiDocDocument.objects.filter(organization=organization).filter(created_by=request.user).select_related("created_by")
    can_claim = request.user.organization_memberships.filter(organization=organization, is_active=True, role__in=HR_ROLES).exists()
    if can_claim:
        documents = DigiDocDocument.objects.filter(organization=organization).filter(Q(created_by=request.user) | Q(created_by__isnull=True)).select_related("created_by")
    if query:
        documents = documents.filter(title__icontains=query)
    owner = ""
    sort = request.GET.get("sort", "recent")
    if sort == "title":
        documents = documents.order_by("title", "-updated_at")
    else:
        sort = "recent"
        documents = documents.order_by("-updated_at")
    page = Paginator(documents, 24).get_page(request.GET.get("page"))
    owners = ()
    notice = False
    if can_claim:
        notice = not request.session.get(f"digidoc_privacy_notice_{organization.pk}")
        request.session[f"digidoc_privacy_notice_{organization.pk}"] = True
    return render(request, "attendance/digidoc_list.html", _doc_context(request, organization,
        documents=page.object_list, document_page=page, query=query, owner=owner, sort=sort, owners=owners, can_claim=can_claim, privacy_notice=notice))


@login_required
def digidoc_thumbnail(request, document_id):
    organization = _scope(request)
    document = _owned_document(request, organization, document_id)
    revision = document.updated_at.isoformat() if document.updated_at else "new"
    cache_key = f"digidoc:thumbnail:{document.pk}:{document.version}:{revision}"
    image = cache.get(cache_key)
    if image is None:
        try:
            pdf_data = _render_pdf_isolated(document)
            pages = _render_preview_images_isolated(pdf_data, first_page_only=True)
            image = base64.b64decode(pages[0]["data"], validate=True)
            cache.set(cache_key, image, timeout=60 * 60 * 24)
        except Exception:
            return HttpResponse(status=404)
    response = HttpResponse(image, content_type="image/png")
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def digidoc_letterhead_image(request, document_id, slot):
    organization = _scope(request)
    document = _owned_document(request, organization, document_id)
    if slot not in {"1", "2"}:
        return HttpResponse(status=404)
    item = (document.letterhead_snapshot or {}).get(slot)
    if not item:
        return HttpResponse(status=404)
    try:
        data = base64.b64decode(item["data"], validate=True)
    except (KeyError, ValueError):
        return HttpResponse(status=404)
    response = HttpResponse(data, content_type="image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def digidoc_personal_letterhead_image(request, document_id):
    organization = _scope(request)
    document = _owned_document(request, organization, document_id)
    item = (document.personal_letterhead_snapshot or {}).get("1")
    if not item:
        return HttpResponse(status=404)
    try:
        data = base64.b64decode(item["data"], validate=True)
    except (KeyError, ValueError):
        return HttpResponse(status=404)
    response = HttpResponse(data, content_type="image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def digidoc_create(request):
    organization = _scope(request)
    company_letterhead = CompanyLetterhead.objects.filter(organization=organization).first()
    letterhead = company_letterhead
    doc = DigiDocDocument.objects.create(
        organization=organization,
        created_by=request.user,
        title="Untitled document",
        content_json={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
        letterhead_enabled=bool(letterhead and letterhead.image),
        letterhead_page_mode=letterhead.default_page_mode if letterhead else "every",
        letterhead_first_slot="1",
        letterhead_other_slot="none" if letterhead and letterhead.default_page_mode == "first" else "1",
        letterhead_snapshot=_letterhead_snapshot(letterhead),
    )
    return redirect("digidoc_editor", document_id=doc.pk)


@login_required
@require_POST
def digidoc_claim(request, document_id):
    organization = _scope(request)
    if not request.user.organization_memberships.filter(organization=organization, is_active=True, role__in=HR_ROLES).exists():
        raise PermissionDenied
    doc = get_object_or_404(DigiDocDocument, pk=document_id, organization=organization, created_by__isnull=True)
    doc.created_by = request.user
    doc.save(update_fields=["created_by"])
    return redirect("digidoc_list")


@login_required
@ensure_csrf_cookie
def digidoc_editor(request, document_id):
    organization = _scope(request)
    doc = _owned_document(request, organization, document_id)
    try:
        content = validate_document_json(doc.content_json)
    except ValidationError:
        content = {"type": "doc", "content": [{"type": "paragraph", "content": []}]}
    company_letterhead = CompanyLetterhead.objects.filter(organization=organization).first()
    letterhead = company_letterhead
    company_snapshot_display = _snapshot_letterhead_display(doc.letterhead_snapshot) if doc.letterhead_enabled else None
    personal_snapshot_display = _snapshot_letterhead_display(doc.personal_letterhead_snapshot) if doc.letterhead_enabled else None
    personal_access = OrganizationMembership.objects.filter(user=request.user, organization=organization, is_active=True, can_use_personal_letterhead=True).exists()
    personal_letters = PersonalLetterhead.objects.filter(organization=organization, user=request.user) if personal_access else PersonalLetterhead.objects.none()
    current_personal_letterhead = personal_letters.filter(pk=doc.personal_letterhead_id).first() if doc.personal_letterhead_id else None
    snapshot_display = personal_snapshot_display if doc.letterhead_source == "personal" else company_snapshot_display
    if snapshot_display:
        letterhead = snapshot_display
        if doc.letterhead_source == "personal":
            letterhead_image_url = reverse("digidoc_personal_letterhead_image", args=[doc.pk])
            letterhead_second_image_url = letterhead_image_url
        else:
            letterhead_image_url = reverse("digidoc_letterhead_image", args=[doc.pk, "1"])
            letterhead_second_image_url = reverse("digidoc_letterhead_image", args=[doc.pk, "2"])
    else:
        letterhead_image_url = reverse("company_letterhead_image")
        letterhead_second_image_url = reverse("company_letterhead_image") + "?slot=2"
    writing_settings = DigiDocWritingSettings.objects.filter(organization=organization).first()
    settings_json = {
        "autocapitalize_enabled": writing_settings.autocapitalize_enabled if writing_settings else True,
        "autocorrect_enabled": writing_settings.autocorrect_enabled if writing_settings else True,
        "spellcheck_enabled": writing_settings.spellcheck_enabled if writing_settings else True,
        "language": writing_settings.language if writing_settings else "en-GB",
        "rules": writing_settings.autocorrect_rules if writing_settings else default_digidoc_autocorrect_rules(),
    }
    can_manage_writing = request.user.organization_memberships.filter(organization=organization, is_active=True, role__in={"owner", "hr_admin"}).exists()
    nonce = secrets.token_urlsafe(18)
    safe_json_script = str(json_script(content, "dd-initial")).replace("<script ", f'<script nonce="{nonce}" ', 1)
    settings_script = str(json_script(settings_json, "dd-writing-settings")).replace("<script ", f'<script nonce="{nonce}" ', 1)
    response = render(request, "attendance/digidoc_editor.html", _doc_context(request, organization, document=doc, initial_json_script=safe_json_script, writing_settings_script=settings_script, writing_settings=settings_json, writing_language_choices=DigiDocWritingSettings.LANGUAGE_CHOICES, can_manage_writing=can_manage_writing, letterhead=letterhead, company_letterhead=company_letterhead, letterhead_image_url=letterhead_image_url, letterhead_second_image_url=letterhead_second_image_url, personal_letters=personal_letters, current_personal_letterhead=current_personal_letterhead, personal_letterhead_image_url=reverse("personal_letterhead_image", args=[current_personal_letterhead.pk]) if current_personal_letterhead else "", company_letterhead_image_url=reverse("company_letterhead_image"), company_letterhead_second_image_url=reverse("company_letterhead_image") + "?slot=2", branding_url=reverse("organization_branding"), csp_nonce=nonce))
    response["Content-Security-Policy"] = f"default-src 'self'; script-src 'self'; style-src 'self' 'nonce-{nonce}'; img-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    response["X-Frame-Options"] = "DENY"
    response["Referrer-Policy"] = "same-origin"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


def _validated_autocorrect_rules(raw):
    if not isinstance(raw, str) or len(raw) > 10000:
        raise ValidationError("The correction list is too long.")
    rules = []
    seen = set()
    for line in raw.splitlines():
        if not line.strip():
            continue
        if "=>" not in line:
            raise ValidationError("Use one rule per line in the form wrong => corrected.")
        source, replacement = (part.strip() for part in line.split("=>", 1))
        if not source or len(source) > 50 or len(replacement) > 100 or source == replacement:
            raise ValidationError("Each correction needs 1–50 source characters and up to 100 replacement characters.")
        for value in (source, replacement):
            if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value) or any(char in "<>" for char in value):
                raise ValidationError("Corrections cannot contain markup, control, or bidirectional characters.")
            if re.search(r"(?:url\s*\(|https?://|javascript:|data:)", value, re.I):
                raise ValidationError("Corrections cannot contain URLs or CSS values.")
        key = source.casefold()
        if key in seen:
            raise ValidationError("Correction source phrases must be unique.")
        seen.add(key)
        rules.append({"from": source, "to": replacement})
        if len(rules) > 100:
            raise ValidationError("A company can define up to 100 correction rules.")
    return rules


@login_required
def digidoc_writing_settings(request):
    organization = _scope(request)
    membership = request.user.organization_memberships.filter(organization=organization, is_active=True).first()
    if not membership or membership.role not in {"owner", "hr_admin"}:
        raise PermissionDenied
    settings_obj = DigiDocWritingSettings.objects.filter(organization=organization).first()
    defaults = {
        "autocapitalize_enabled": True, "autocorrect_enabled": True,
        "spellcheck_enabled": True, "language": "en-GB",
        "autocorrect_rules": default_digidoc_autocorrect_rules(),
    }
    values = {**defaults, **({
        "autocapitalize_enabled": settings_obj.autocapitalize_enabled,
        "autocorrect_enabled": settings_obj.autocorrect_enabled,
        "spellcheck_enabled": settings_obj.spellcheck_enabled,
        "language": settings_obj.language,
        "autocorrect_rules": settings_obj.autocorrect_rules,
    } if settings_obj else {})}
    error = ""
    if request.method == "POST":
        if len(request.body) > 12288:
            raise ValidationError("The writing settings request is too large.")
        allowed = {"csrfmiddlewaretoken", "autocapitalize_enabled", "autocorrect_enabled", "spellcheck_enabled", "language", "rules"}
        if set(request.POST) - allowed:
            raise ValidationError("Unsupported writing setting.")
        language = request.POST.get("language", "")
        if language not in {choice[0] for choice in DigiDocWritingSettings.LANGUAGE_CHOICES}:
            raise ValidationError("Unsupported spell-check language.")
        try:
            rules = _validated_autocorrect_rules(request.POST.get("rules", ""))
        except ValidationError as exc:
            error = exc.messages[0]
        else:
            settings_obj, _created = DigiDocWritingSettings.objects.get_or_create(organization=organization)
            settings_obj.autocapitalize_enabled = request.POST.get("autocapitalize_enabled") == "on"
            settings_obj.autocorrect_enabled = request.POST.get("autocorrect_enabled") == "on"
            settings_obj.spellcheck_enabled = request.POST.get("spellcheck_enabled") == "on"
            settings_obj.language = language
            settings_obj.autocorrect_rules = rules
            settings_obj.updated_by = request.user
            settings_obj.save()
            AuditLog.objects.create(organization=organization, actor=request.user, area="organization", action="digidoc.writing_settings_changed", target_model="DigiDocWritingSettings", target_id=str(organization.pk), summary="Updated company DigiDoc writing preferences.", metadata={"language": language, "rule_count": len(rules)})
            values.update({
                "autocapitalize_enabled": settings_obj.autocapitalize_enabled,
                "autocorrect_enabled": settings_obj.autocorrect_enabled,
                "spellcheck_enabled": settings_obj.spellcheck_enabled,
                "language": language,
                "autocorrect_rules": rules,
            })
    return render(request, "attendance/digidoc_writing_settings.html", {
        "organization": organization, "values": values, "error": error,
        "rules_text": "\n".join(f"{rule['from']} => {rule['to']}" for rule in values["autocorrect_rules"]),
    })


@login_required
@require_POST
def digidoc_save(request, document_id):
    organization = _scope(request)
    doc = _owned_document(request, organization, document_id)
    if doc.created_by_id is None:
        return JsonResponse({"error": "Claim this orphaned document before editing."}, status=403)
    if len(request.body) > MAX_JSON_BYTES + 4096:
        return JsonResponse({"error": "The document exceeds the 2 MB limit."}, status=413)
    rate_key = f"digidoc:save:{organization.pk}:{request.user.pk}"
    cache.add(rate_key, 0, timeout=60)
    try:
        if cache.incr(rate_key) > 120:
            return JsonResponse({"error": "Autosave rate limit reached. Try again shortly."}, status=429)
    except ValueError:
        cache.set(rate_key, 1, timeout=60)
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) - {"title", "content", "letterhead_enabled", "letterhead_page_mode", "letterhead_first_slot", "letterhead_other_slot", "letterhead_source", "personal_letterhead_id", "version"}:
            raise ValidationError("Unsupported save request.")
        content = validate_document_json(payload.get("content"))
        _ensure_company_images(content, organization)
        expected_version = payload.get("version")
        if type(expected_version) is not int:
            raise ValidationError("Document version is invalid.")
        title = _clean_title(payload.get("title"))
        enabled = payload.get("letterhead_enabled", False)
        mode = payload.get("letterhead_page_mode", "every")
        first_slot = payload.get("letterhead_first_slot", "1")
        other_slot = payload.get("letterhead_other_slot", "none" if mode == "first" else "1")
        source = payload.get("letterhead_source", "company")
        if source not in {"company", "personal"}:
            raise ValidationError("Invalid letterhead source.")
        current_letterhead = CompanyLetterhead.objects.filter(organization=organization).first()
        personal_letterhead = None
        if source == "personal" and enabled:
            membership = request.user.organization_memberships.filter(organization=organization, is_active=True, role__in=DIGIDOC_ROLES, can_use_personal_letterhead=True).first()
            if not membership:
                raise ValidationError("Personal letterhead access is not enabled for your account.")
            personal_letterhead = PersonalLetterhead.objects.filter(pk=payload.get("personal_letterhead_id"), organization=organization, user=request.user).first()
            if not personal_letterhead:
                raise ValidationError("Choose one of your own saved personal letterheads.")
        # Keep the editor's default slot values valid when the letterhead is
        # disabled. They have no rendering effect until enabled.
        valid_slots = {"none"} if enabled else {"none", "1", "2"}
        if source == "personal" and (personal_letterhead or doc.personal_letterhead_snapshot):
            valid_slots.add("1")
        elif current_letterhead and current_letterhead.image:
            valid_slots.add("1")
        if source == "company" and ((current_letterhead and current_letterhead.image_second) or "2" in (doc.letterhead_snapshot or {})):
            valid_slots.add("2")
        if source == "company":
            valid_slots.update((doc.letterhead_snapshot or {}).keys())
        if type(enabled) is not bool or mode not in {"every", "first"} or first_slot not in valid_slots or other_slot not in valid_slots:
            raise ValidationError("Invalid letterhead settings.")
        layout_attrs = content.get("attrs", {})
        if enabled and (layout_attrs.get("page_size", "A4") != "A4" or layout_attrs.get("orientation", "portrait") != "portrait"):
            raise ValidationError("Letterheads are available on A4 portrait pages only.")
        if enabled and source == "company" and not ((current_letterhead and current_letterhead.image) or doc.letterhead_snapshot):
            raise ValidationError("This company has no saved letterhead.")
        if enabled and source == "personal" and not personal_letterhead:
            raise ValidationError("Choose one of your own saved personal letterheads.")
        with transaction.atomic():
            doc = get_object_or_404(DigiDocDocument.objects.select_for_update(), pk=document_id, organization=organization)
            if expected_version != doc.version:
                return JsonResponse({"error": "This document changed in another session. Reload before saving."}, status=409)
            doc.title, doc.content_json = title, content
            doc.letterhead_enabled, doc.letterhead_page_mode = enabled, mode
            doc.letterhead_first_slot, doc.letterhead_other_slot = first_slot, other_slot
            doc.letterhead_source = source
            if source == "company" and enabled and current_letterhead:
                doc.letterhead_snapshot = _letterhead_snapshot(current_letterhead)
            elif source == "company" and not enabled:
                doc.letterhead_snapshot = {}
            if source == "personal" and enabled and personal_letterhead:
                doc.personal_letterhead_id = personal_letterhead.pk
                doc.personal_letterhead_snapshot = _personal_letterhead_snapshot(personal_letterhead)
            elif source == "personal" and not enabled:
                doc.personal_letterhead_id = None
                doc.personal_letterhead_snapshot = {}
            doc.version += 1
            doc.save(update_fields=["title", "content_json", "letterhead_enabled", "letterhead_page_mode", "letterhead_first_slot", "letterhead_other_slot", "letterhead_source", "personal_letterhead_id", "personal_letterhead_snapshot", "letterhead_snapshot", "version", "updated_at"])
        return JsonResponse({"ok": True, "version": doc.version, "updated_at": timezone.localtime(doc.updated_at).strftime("%I:%M %p").lstrip("0")})
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else "Invalid save request."
        return JsonResponse({"error": message}, status=400)


@login_required
@require_POST
def digidoc_duplicate(request, document_id):
    organization = _scope(request)
    original = _owned_document(request, organization, document_id)
    if original.created_by_id is None:
        raise PermissionDenied
    doc = DigiDocDocument.objects.create(organization=organization, created_by=request.user, title=_clean_title("Copy of " + original.title), content_json=original.content_json, letterhead_enabled=original.letterhead_enabled, letterhead_page_mode=original.letterhead_page_mode, letterhead_first_slot=original.letterhead_first_slot, letterhead_other_slot=original.letterhead_other_slot, letterhead_source=original.letterhead_source, letterhead_snapshot=original.letterhead_snapshot, personal_letterhead_snapshot=original.personal_letterhead_snapshot, personal_letterhead_id=original.personal_letterhead_id)
    return redirect("digidoc_editor", document_id=doc.pk)


@login_required
@require_POST
def digidoc_delete(request, document_id):
    organization = _scope(request)
    doc = _owned_document(request, organization, document_id)
    if doc.created_by_id is None:
        raise PermissionDenied
    doc.delete()
    return redirect("digidoc_list")


@login_required
@require_POST
def digidoc_image_upload(request):
    organization = _scope(request)
    upload = request.FILES.get("image")
    if not upload or upload.size <= 0 or upload.size > 8 * 1024 * 1024:
        return JsonResponse({"error": "Choose a PNG or JPEG image no larger than 8 MB."}, status=400)
    recent_uploads = AuditLog.objects.filter(actor=request.user, action="digidoc.image_uploaded", created_at__gte=timezone.now()-timedelta(hours=1)).count()
    if recent_uploads >= 10:
        return JsonResponse({"error": "Upload limit reached for this hour."}, status=429)
    usage = 0
    for asset in DigiDocImageAsset.objects.filter(organization=organization).only("image"):
        try: usage += asset.image.size
        except OSError: pass
    if usage + upload.size > 100 * 1024 * 1024:
        return JsonResponse({"error": "The company DigiDoc image storage limit has been reached."}, status=413)
    from .letterhead import sanitize_letterhead
    try:
        data, image_format, _extension, width, height = sanitize_letterhead(upload)
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)
    asset = DigiDocImageAsset(organization=organization, uploaded_by=request.user, image_format=image_format, image_width=width, image_height=height)
    asset.image.save("asset.png" if image_format == "png" else "asset.jpg", ContentFile(data), save=True)
    AuditLog.objects.create(organization=organization, actor=request.user, area="organization", action="digidoc.image_uploaded", target_model="DigiDocImageAsset", target_id=str(asset.pk), summary="Uploaded a DigiDoc image asset.", metadata={"format": image_format, "size": len(data)})
    return JsonResponse({"id": str(asset.pk), "url": reverse("digidoc_image", args=[asset.pk]), "alt": ""})


@login_required
def digidoc_image(request, asset_id):
    organization = _scope(request)
    asset = get_object_or_404(DigiDocImageAsset, pk=asset_id, organization=organization)
    try:
        with asset.image.open("rb") as image_file:
            data = image_file.read(8 * 1024 * 1024 + 1)
    except OSError:
        return HttpResponse(status=404)
    if len(data) > 8 * 1024 * 1024:
        return HttpResponse(status=404)
    response = HttpResponse(data, content_type="image/png" if asset.image_format == "png" else "image/jpeg")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


def _paragraph_html(node):
    if node["type"] == "text":
        value = html.escape(node.get("text", "")).replace("\n", "<br/>")
        for mark in node.get("marks", []):
            kind = mark["type"]
            if kind == "bold": value = f"<b>{value}</b>"
            elif kind == "italic": value = f"<i>{value}</i>"
            elif kind == "underline": value = f"<u>{value}</u>"
            elif kind == "strike": value = f"<strike>{value}</strike>"
            elif kind == "superscript": value = f"<super>{value}</super>"
            elif kind == "subscript": value = f"<sub>{value}</sub>"
            elif kind == "link": value = f'<link href="{html.escape(mark["attrs"]["href"], quote=True)}" color="#2457b2">{value}</link>'
            elif kind == "fontFamily": value = f'<font name="{mark["attrs"]["value"]}">{value}</font>'
            elif kind == "fontSize": value = f'<font size="{mark["attrs"]["value"]}">{value}</font>'
            elif kind == "textColor": value = f'<font color="{mark["attrs"]["color"]}">{value}</font>'
            elif kind == "highlight": value = f'<font backColor="{mark["attrs"]["color"]}">{value}</font>'
        return value
    return "".join(_paragraph_html(child) for child in node.get("content", []))


def _build_pdf(doc, organization=None, *, pdf_assets=None, letterhead_bytes=None, letterhead_meta=None):
    font_dir = os.path.join(os.path.dirname(__file__), "static", "attendance", "fonts")
    font_slugs = (("Roboto", "roboto"), ("Open Sans", "open-sans"), ("Lato", "lato"), ("Montserrat", "montserrat"), ("Merriweather", "merriweather"), ("Nunito", "nunito"), ("Oswald", "oswald"), ("Source Sans 3", "source-sans-3"), ("Poppins", "poppins"), ("Playfair Display", "playfair-display"), ("Roboto Mono", "roboto-mono"), ("Inter", "inter"), ("Arimo", "arimo"), ("Tinos", "tinos"), ("Cousine", "cousine"), ("Carlito", "carlito"), ("Caladea", "caladea"), ("Noto Sans", "notosans"), ("Noto Serif", "notoserif"), ("Lora", "lora"), ("Raleway", "raleway"), ("EB Garamond", "ebgaramond"), ("Libre Baskerville", "librebaskerville"), ("PT Serif", "pt-serif"), ("Crimson Text", "crimsontext"))
    for family, slug in font_slugs:
        regular = os.path.join(font_dir, f"{slug}-400.ttf")
        bold = os.path.join(font_dir, f"{slug}-700.ttf")
        italic = os.path.join(font_dir, f"{slug}-400-italic.ttf")
        bold_italic = os.path.join(font_dir, f"{slug}-700-italic.ttf")
        if os.path.isfile(regular):
            bold = bold if os.path.isfile(bold) else regular
            italic = italic if os.path.isfile(italic) else regular
            bold_italic = bold_italic if os.path.isfile(bold_italic) else bold
            pdfmetrics.registerFont(TTFont(family, regular))
            pdfmetrics.registerFont(TTFont(f"{family}-Bold", bold))
            pdfmetrics.registerFont(TTFont(f"{family}-Italic", italic))
            pdfmetrics.registerFont(TTFont(f"{family}-BoldItalic", bold_italic))
            pdfmetrics.registerFontFamily(family, normal=family, bold=f"{family}-Bold", italic=f"{family}-Italic", boldItalic=f"{family}-BoldItalic")
    content = validate_document_json(doc.content_json)
    if letterhead_meta is not None:
        if doc.letterhead_enabled and isinstance(letterhead_meta, dict) and "scale_mode" in letterhead_meta:
            letterhead_assets = {"1": SimpleNamespace(**letterhead_meta)}
        elif doc.letterhead_enabled and isinstance(letterhead_meta, dict):
            letterhead_assets = {slot: SimpleNamespace(**meta) for slot, meta in letterhead_meta.items()}
        else:
            letterhead_assets = {}
        letterhead_data = letterhead_bytes if isinstance(letterhead_bytes, dict) else ({"1": letterhead_bytes} if letterhead_bytes else {})
    else:
        asset = CompanyLetterhead.objects.filter(organization=organization).first() if doc.letterhead_enabled else None
        letterhead_assets, letterhead_data = {}, {}
        if asset:
            for slot, field_name in (("1", "image"), ("2", "image_second")):
                image = getattr(asset, field_name)
                if image:
                    letterhead_assets[slot] = asset
                    with image.open("rb") as source:
                        letterhead_data[slot] = source.read(8 * 1024 * 1024 + 1)
    first_slot = getattr(doc, "letterhead_first_slot", "1")
    other_slot = getattr(doc, "letterhead_other_slot", "none" if getattr(doc, "letterhead_page_mode", "every") == "first" else "1")
    if doc.letterhead_enabled and not letterhead_assets:
        raise ValidationError("The saved letterhead is unavailable.")
    if doc.letterhead_enabled and any(slot not in {"1", "2", "none"} for slot in (first_slot, other_slot)):
        raise ValidationError("The selected letterhead is unavailable.")
    if doc.letterhead_enabled and any(slot != "none" and (slot not in letterhead_assets or slot not in letterhead_data) for slot in (first_slot, other_slot)):
        raise ValidationError("The selected letterhead is unavailable.")
    document_attrs = content.get("attrs", {})
    page_size_name = document_attrs.get("page_size", "A4")
    orientation = document_attrs.get("orientation", "portrait")
    page_size = PAGE_SIZE_POINTS[page_size_name]
    if orientation == "landscape":
        page_size = page_landscape(page_size)
    margins_cm = document_attrs.get("margins", {"top_cm": 2.5, "right_cm": 2.5, "bottom_cm": 2.5, "left_cm": 2.5})
    margins = tuple(margins_cm[field] * 10 for field in ("top_cm", "right_cm", "bottom_cm", "left_cm"))
    letterhead = letterhead_assets.get("1") or next(iter(letterhead_assets.values()), None)
    if letterhead:
        if page_size_name != "A4" or orientation != "portrait":
            raise ValidationError("Letterheads are available on A4 portrait pages only.")
        margins = tuple(max(value, required) for value, required in zip(
            margins, (letterhead.margin_top_mm + 4, letterhead.margin_right_mm, letterhead.margin_bottom_mm + 4, letterhead.margin_left_mm)))
    buffer = BytesIO()
    top, right, bottom, left = margins
    pdf = SimpleDocTemplate(buffer, pagesize=page_size, leftMargin=left*mm, rightMargin=right*mm, topMargin=top*mm, bottomMargin=bottom*mm, title=_clean_title(doc.title), pageCompression=1)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DigiDocH1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=20, leading=25, spaceBefore=8, spaceAfter=8))
    styles.add(ParagraphStyle(name="DigiDocH2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=16, leading=20, spaceBefore=7, spaceAfter=6))
    styles.add(ParagraphStyle(name="DigiDocH3", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=13, leading=17, spaceBefore=6, spaceAfter=5))
    styles.add(ParagraphStyle(name="DigiDocTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=24, leading=30, spaceBefore=10, spaceAfter=10))
    styles.add(ParagraphStyle(name="DigiDocSubtitle", parent=styles["BodyText"], fontName="Helvetica-Oblique", fontSize=12, leading=15, textColor="#5b6572", spaceAfter=8))
    alignments = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT, "justify": TA_JUSTIFY}
    flow = []

    def image_flow(node):
        attrs = node.get("attrs", {})
        asset_id = attrs.get("asset_id", "")
        image_data = pdf_assets.get(asset_id, b"") if pdf_assets is not None else b""
        if pdf_assets is None:
            try:
                asset = DigiDocImageAsset.objects.get(pk=asset_id, organization=organization)
                with asset.image.open("rb") as image_file:
                    image_data = image_file.read(8 * 1024 * 1024 + 1)
            except (DigiDocImageAsset.DoesNotExist, OSError, ValueError):
                image_data = b""
        result = []
        if attrs.get("space_before_pt", 0):
            result.append(Spacer(1, attrs["space_before_pt"]))
        if not image_data or len(image_data) > 8 * 1024 * 1024:
            alt = html.escape(attrs.get("alt") or "Image unavailable")
            result.append(Paragraph(f"[Image unavailable: {alt}]", styles["BodyText"]))
        else:
            crop_ratio = {"square": 1, "landscape": 16 / 9, "portrait": 3 / 4}.get(attrs.get("crop", "none"))
            if crop_ratio:
                from PIL import Image, ImageOps
                with Image.open(BytesIO(image_data)) as source_image:
                    cropped = ImageOps.fit(source_image.convert("RGB"), (1200, max(1, round(1200 / crop_ratio))), centering=(0.5, 0.5))
                    image_buffer = BytesIO()
                    cropped.save(image_buffer, format="JPEG", quality=90, optimize=True)
                    image_data = image_buffer.getvalue()
            image = PdfImage(BytesIO(image_data))
            max_width, max_height = A4[0] - (left + right) * mm, A4[1] - (top + bottom) * mm
            max_width *= attrs.get("width_percent", 100) / 100
            scale = min(max_width / image.imageWidth, max_height / image.imageHeight, 1)
            image.drawWidth = image.imageWidth * scale
            image.drawHeight = image.imageHeight * scale
            image.hAlign = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}.get(attrs.get("align", "center"), "CENTER")
            result.append(image)
        if attrs.get("space_after_pt", 0):
            result.append(Spacer(1, attrs["space_after_pt"]))
        return result

    def paragraph_flows(node, style):
        children = node.get("content", [])
        if not any(child.get("type") == "image" for child in children):
            return [Paragraph(_paragraph_html(node) or "&#160;", style)]
        result, segment = [], []
        for child in children:
            if child.get("type") == "image":
                if segment:
                    result.append(Paragraph(_paragraph_html({"type": "paragraph", "content": segment}) or "&#160;", style))
                    segment = []
                result.extend(image_flow(child))
            else:
                segment.append(child)
        if segment:
            result.append(Paragraph(_paragraph_html({"type": "paragraph", "content": segment}) or "&#160;", style))
        return result

    def build_list_flow(node, level=0):
        kind = node["type"]
        checklist = kind == "bulletList" and node.get("attrs", {}).get("list_style") == "checklist"
        items = []
        for item in node.get("content", []):
            item_flows = []
            for child in item.get("content", []):
                if child["type"] in {"paragraph", "heading"}:
                    item_flows.extend(paragraph_flows(child, styles["BodyText"]))
                elif child["type"] in {"bulletList", "orderedList"}:
                    item_flows.append(build_list_flow(child, level + 1))
            if checklist:
                item_flows.insert(0, Paragraph("[ ]", styles["BodyText"]))
            items.append(ListItem(item_flows or [Paragraph("&#160;", styles["BodyText"])]))
        list_style = node.get("attrs", {}).get("list_style", "decimal" if kind == "orderedList" else "disc")
        bullet_type = ({"decimal":"1", "lower-alpha":"a", "upper-alpha":"A", "lower-roman":"i", "upper-roman":"I"}.get(list_style, "bullet")) if kind == "orderedList" else "bullet"
        start = node.get("attrs", {}).get("start", 1) if kind == "orderedList" else "bulletchar"
        glyph = {"disc":"•", "circle":"◦", "square":"▪", "checklist":"☐"}.get(list_style, "•")
        return ListFlowable(items, bulletType=bullet_type, bulletChar=glyph, start=start, leftIndent=18 * (level + 1),
                            bulletFormat="%s." if kind == "orderedList" else None,
                            bulletFontName="Helvetica", bulletFontSize=9, bulletDedent=10)

    def blocks(nodes):
        for node in nodes:
            kind = node["type"]
            if kind == "image":
                flow.extend(image_flow(node))
                continue
            if kind in {"paragraph", "heading", "tableCell"}:
                text = _paragraph_html(node)
                attrs = node.get("attrs", {})
                if kind == "heading":
                    base_style = styles["DigiDocTitle"] if attrs.get("style") == "title" else styles[f"DigiDocH{node['level']}"]
                    base_size = base_style.fontSize
                    leading_ratio = base_style.leading / base_size
                else:
                    base_style = styles["DigiDocSubtitle"] if attrs.get("style") == "subtitle" else styles["BodyText"]
                    base_size = base_style.fontSize if attrs.get("style") == "subtitle" else 10
                    leading_ratio = base_style.leading / base_size if attrs.get("style") == "subtitle" else 1.2
                leading_ratio = {"single": 1.2, "1.15": 1.38, "1.5": 1.8, "double": 2.4}.get(attrs.get("line_spacing", "single"), leading_ratio)
                style = ParagraphStyle(
                    "DigiDocBlock", parent=base_style, fontName=base_style.fontName,
                    fontSize=base_size, leading=round(base_size * leading_ratio, 1),
                    alignment=alignments.get(attrs.get("align"), TA_LEFT),
                    leftIndent=attrs.get("left_indent_cm", attrs.get("indent", 0) * 1.27) * 28.3465,
                    rightIndent=attrs.get("right_indent_cm", 0) * 28.3465,
                    firstLineIndent=attrs.get("first_line_indent_cm", 0) * 28.3465,
                    spaceBefore=attrs.get("space_before_pt", 0),
                    spaceAfter=attrs.get("space_after_pt", 7),
                )
                flow.extend(paragraph_flows(node, style))
            elif kind == "hardBreak": flow.append(PageBreak())
            elif kind == "horizontalRule":
                from reportlab.platypus import HRFlowable
                flow.extend([HRFlowable(width="100%", thickness=0.8, color="#9aa2ad", spaceBefore=6, spaceAfter=10), Spacer(1, 2)])
            elif kind in {"bulletList", "orderedList"}:
                flow.append(build_list_flow(node))
            elif kind == "table":
                rows = []
                for row in node.get("content", []):
                    rows.append([Paragraph(_paragraph_html(cell) or "&#160;", styles["BodyText"]) for cell in row.get("content", [])])
                if rows:
                    width = A4[0] - (left + right)*mm
                    column_count = max(len(row) for row in rows)
                    table = Table(rows, colWidths=[width/max(column_count, 1)] * column_count, repeatRows=1, hAlign="LEFT")
                    table.setStyle(TableStyle([("GRID", (0,0), (-1,-1), .5, (0.65,0.68,0.72)), ("BACKGROUND", (0,0), (-1,0), (0.92,0.94,0.97)), ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 7), ("RIGHTPADDING", (0,0), (-1,-1), 7), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
                    flow.extend([table, Spacer(1, 8)])
            elif kind in {"doc", "listItem"}:
                blocks(node.get("content", []))
    blocks(content.get("content", []))

    image_handles, readers = {}, {}
    if doc.letterhead_enabled:
        for slot, raw in letterhead_data.items():
            if not raw or len(raw) > 8 * 1024 * 1024:
                raise ValidationError("The saved letterhead is unavailable.")
            image_handles[slot] = BytesIO(raw)
            readers[slot] = ImageReader(image_handles[slot])
        def draw_page(canvas, _document):
            page_number = canvas.getPageNumber()
            if page_number > MAX_PAGES:
                raise ValidationError("The document exceeds the 50 page limit.")
            slot = first_slot if page_number == 1 else other_slot
            if slot != "none":
                reader = readers[slot]
                iw, ih = reader.getSize()
                selected_letterhead = letterhead_assets[slot]
                scale = max(A4[0]/iw, A4[1]/ih) if selected_letterhead.scale_mode == "fill" else min(A4[0]/iw, A4[1]/ih)
                w, h = iw*scale, ih*scale
                canvas.saveState(); path=canvas.beginPath(); path.rect(0,0,A4[0],A4[1]); canvas.clipPath(path, stroke=0, fill=0)
                canvas.drawImage(reader,(A4[0]-w)/2,(A4[1]-h)/2,width=w,height=h,mask="auto"); canvas.restoreState()
    else:
        def draw_page(canvas, _document):
            if canvas.getPageNumber() > MAX_PAGES:
                raise ValidationError("The document exceeds the 50 page limit.")

    def make_canvas(*args, **kwargs):
        kwargs.update(pagesize=A4, pageCompression=1, invariant=1)
        output = pdf_canvas.Canvas(*args, **kwargs)
        output.setTitle(_clean_title(doc.title))
        output.setAuthor("")
        output.setSubject("")
        output.setCreator("")
        output._doc.info.producer = ""
        return output

    try:
        pdf.build(flow or [Paragraph("&#160;", styles["BodyText"])], onFirstPage=draw_page, onLaterPages=draw_page, canvasmaker=make_canvas)
    except Exception:
        for image_handle in image_handles.values(): image_handle.close()
        raise
    for image_handle in image_handles.values(): image_handle.close()
    data = buffer.getvalue()
    if len(data) > 25 * 1024 * 1024:
        raise ValidationError("The generated PDF is too large.")
    return data


def _render_pdf_isolated(document):
    """Run PDF generation in a short-lived worker with a process memory cap."""
    content = validate_document_json(document.content_json)
    image_ids = set()
    def collect(node):
        if node["type"] == "image": image_ids.add(node["attrs"]["asset_id"])
        for child in node.get("content", []): collect(child)
    collect(content)
    image_payload = {}
    total_asset_bytes = 0
    for asset in DigiDocImageAsset.objects.filter(organization=document.organization, pk__in=image_ids):
        try:
            with asset.image.open("rb") as source:
                data = source.read(8 * 1024 * 1024 + 1)
        except (OSError, ValueError):
            continue
        if not data or len(data) > 8 * 1024 * 1024:
            continue
        total_asset_bytes += len(data)
        if total_asset_bytes > 20 * 1024 * 1024:
            raise ValidationError("The combined document images exceed the PDF input limit.")
        image_payload[str(asset.pk)] = base64.b64encode(data).decode("ascii")
    letterhead_bytes = None
    letterhead_meta = None
    active_snapshot = document.personal_letterhead_snapshot if document.letterhead_source == "personal" else document.letterhead_snapshot
    if document.letterhead_enabled and active_snapshot:
        letterhead_bytes, letterhead_meta = {}, {}
        for slot, item in active_snapshot.items():
            letterhead_bytes[slot] = base64.b64decode(item["data"], validate=True)
            letterhead_meta[slot] = item["meta"]
    elif document.letterhead_enabled:
        if document.letterhead_source == "personal":
            raise ValidationError("The saved personal letterhead snapshot is unavailable.")
        letterhead = CompanyLetterhead.objects.filter(organization=document.organization).first()
        if not letterhead:
            raise ValidationError("The saved letterhead is unavailable.")
        letterhead_bytes, letterhead_meta = {}, {}
        for slot, field_name in (("1", "image"), ("2", "image_second")):
            image = getattr(letterhead, field_name)
            if image:
                with image.open("rb") as source:
                    letterhead_bytes[slot] = source.read(8 * 1024 * 1024 + 1)
                letterhead_meta[slot] = {"scale_mode": letterhead.scale_mode, "margin_top_mm": letterhead.margin_top_mm, "margin_bottom_mm": letterhead.margin_bottom_mm, "margin_left_mm": letterhead.margin_left_mm, "margin_right_mm": letterhead.margin_right_mm}
    worker_request = {
        "title": _clean_title(document.title), "content": content,
        "letterhead_enabled": document.letterhead_enabled,
        "letterhead_page_mode": document.letterhead_page_mode,
        "letterhead_first_slot": document.letterhead_first_slot,
        "letterhead_other_slot": document.letterhead_other_slot,
        "letterhead_meta": letterhead_meta,
        "letterhead_bytes": {slot: base64.b64encode(data).decode("ascii") for slot, data in letterhead_bytes.items()} if letterhead_bytes else None,
        "assets": image_payload,
    }
    payload = json.dumps(worker_request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > 48 * 1024 * 1024:
        raise ValidationError("The document exceeds the PDF input limit.")
    worker_env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if name in os.environ}
    worker_env.update({"PYTHONIOENCODING": "utf-8", "DJANGO_SETTINGS_MODULE": "core.settings"})
    kwargs = {}
    if os.name != "nt":
        import resource
        def set_limits():
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        kwargs["preexec_fn"] = set_limits
    process = subprocess.Popen([sys.executable, "-m", "attendance.digidoc_worker"], cwd=str(settings.BASE_DIR), env=worker_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    job_handle = None
    try:
        if os.name == "nt":
            from .letterhead import _assign_windows_job_limit
            job_handle = _assign_windows_job_limit(process, cpu_limit_seconds=20)
        output, _error = process.communicate(payload, timeout=60)
    except subprocess.TimeoutExpired as exc:
        process.kill(); process.communicate()
        raise ValidationError("The document export timed out.") from exc
    except Exception:
        if process.poll() is None: process.kill()
        process.communicate()
        raise
    finally:
        if job_handle:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job_handle)
    if process.returncode != 0 or not output or len(output) > 25 * 1024 * 1024:
        raise ValidationError("The document could not be exported.")
    return output


def _render_preview_images_isolated(pdf_data, *, first_page_only=False):
    """Rasterize a generated PDF in a bounded worker and validate its PNG bundle."""
    if not pdf_data.startswith(b"%PDF-") or len(pdf_data) > 25 * 1024 * 1024:
        raise ValidationError("The preview could not be generated.")
    worker_env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if name in os.environ}
    kwargs = {}
    if os.name != "nt":
        import resource
        def set_limits():
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        kwargs["preexec_fn"] = set_limits
    process = subprocess.Popen(
        [sys.executable, "-m", "attendance.digidoc_preview_worker", *( ["--first-page"] if first_page_only else [] )],
        cwd=str(settings.BASE_DIR), env=worker_env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs,
    )
    job_handle = None
    try:
        if os.name == "nt":
            from .letterhead import _assign_windows_job_limit
            job_handle = _assign_windows_job_limit(process, cpu_limit_seconds=20)
        output, _error = process.communicate(pdf_data, timeout=60)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise ValidationError("The preview could not be generated.") from exc
    except Exception:
        if process.poll() is None:
            process.kill()
        process.communicate()
        raise
    finally:
        if job_handle:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job_handle)
    if process.returncode != 0 or not output or len(output) > 31 * 1024 * 1024:
        raise ValidationError("The preview could not be generated.")
    try:
        pages = []
        total = 0
        with zipfile.ZipFile(BytesIO(output), "r") as archive:
            names = archive.namelist()
            if not 1 <= len(names) <= 100 or names != [f"page-{i}.png" for i in range(1, len(names) + 1)]:
                raise ValueError("Invalid preview archive")
            for index, name in enumerate(names, start=1):
                info = archive.getinfo(name)
                if info.file_size > 10 * 1024 * 1024:
                    raise ValueError("Preview image too large")
                raw = archive.read(name)
                total += len(raw)
                if len(raw) != info.file_size or total > 30 * 1024 * 1024 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("Invalid preview image")
                pages.append({"number": index, "data": base64.b64encode(raw).decode("ascii")})
        return pages
    except Exception as exc:
        raise ValidationError("The preview could not be generated.") from exc


@login_required
def digidoc_pdf(request, document_id):
    organization = _scope(request)
    doc = _owned_document(request, organization, document_id)
    cutoff = timezone.now() - timedelta(minutes=1)
    recent = AuditLog.objects.filter(actor=request.user, action="digidoc.download", created_at__gte=cutoff).count()
    if recent >= 10:
        return HttpResponse("Download limit reached. Try again shortly.", status=429)
    slot = None
    token = secrets.token_urlsafe(18)
    for slot_number in (0, 1):
        candidate = f"digidoc:pdf:slot:{slot_number}"
        if cache.add(candidate, token, timeout=30):
            slot = candidate
            break
    if slot is None:
        return HttpResponse("PDF generation is busy. Try again shortly.", status=429)
    try:
        data = _render_pdf_isolated(doc)
    except ValidationError as exc:
        if cache.get(slot) == token: cache.delete(slot)
        return HttpResponse(exc.messages[0], status=400)
    except Exception:
        if cache.get(slot) == token: cache.delete(slot)
        return HttpResponse("The document could not be exported.", status=400)
    if cache.get(slot) == token: cache.delete(slot)
    clean_name = _clean_title(doc.title).replace('\\', '_').replace('/', '_').replace('"', '').replace("'", '')
    clean_name = re.sub(r"[. ]+$", "", re.sub(r"[^\w .-]+", "_", clean_name, flags=re.UNICODE))[:80].strip(" .") or "document"
    if clean_name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        clean_name = "document"
    filename = re.sub(r"[^A-Za-z0-9_-]+", "_", unicodedata.normalize("NFKD", clean_name).encode("ascii", "ignore").decode())[:80].strip("_") or "document"
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"; filename*=UTF-8\'\'{quote(clean_name)}.pdf'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    AuditLog.objects.create(organization=organization, actor=request.user, area="organization", action="digidoc.download", target_model="DigiDocDocument", target_id=str(doc.pk), summary="Downloaded a DigiDoc PDF.", metadata={"format": "pdf"})
    return response


@login_required
def digidoc_export(request, document_id, file_format):
    organization = _scope(request)
    doc = _owned_document(request, organization, document_id)
    exporters = {
        "docx": (export_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "odt": (export_odt, "application/vnd.oasis.opendocument.text"),
        "rtf": (export_rtf, "application/rtf"),
        "txt": (export_text, "text/plain; charset=utf-8"),
    }
    if file_format not in exporters:
        return HttpResponse("Unsupported document format.", status=404)
    cutoff = timezone.now() - timedelta(minutes=1)
    recent = AuditLog.objects.filter(actor=request.user, action="digidoc.download", created_at__gte=cutoff).count()
    if recent >= 10:
        return HttpResponse("Download limit reached. Try again shortly.", status=429)
    try:
        content = validate_document_json(doc.content_json)
        exporter, content_type = exporters[file_format]
        image_ids = set()
        def collect(node):
            if node["type"] == "image":
                image_ids.add(node["attrs"]["asset_id"])
            for child in node.get("content", []):
                collect(child)
        collect(content)
        export_assets = {}
        for asset in DigiDocImageAsset.objects.filter(organization=organization, pk__in=image_ids):
            try:
                with asset.image.open("rb") as source:
                    image_data = source.read(8 * 1024 * 1024 + 1)
            except (OSError, ValueError):
                continue
            if not image_data or len(image_data) > 8 * 1024 * 1024:
                continue
            export_assets[str(asset.pk)] = {"data": image_data, "format": asset.image_format, "width": asset.image_width, "height": asset.image_height}
        data = exporter(content, export_assets)
    except ValidationError as exc:
        return HttpResponse(exc.messages[0], status=400)
    except Exception:
        logger.exception("DigiDoc %s export failed for document %s", file_format, document_id)
        return HttpResponse("The document could not be exported.", status=400)
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not data or len(data) > 25 * 1024 * 1024:
        return HttpResponse("The generated document is too large to download.", status=400)
    clean_name = _clean_title(doc.title).replace("\\", "_").replace("/", "_").replace('"', "").replace("'", "")
    clean_name = re.sub(r"[. ]+$", "", re.sub(r"[^\w .-]+", "_", clean_name, flags=re.UNICODE))[:80].strip(" .") or "document"
    if clean_name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        clean_name = "document"
    filename = re.sub(r"[^A-Za-z0-9_-]+", "_", unicodedata.normalize("NFKD", clean_name).encode("ascii", "ignore").decode())[:80].strip("_") or "document"
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}.{file_format}"; filename*=UTF-8\'\'{quote(clean_name)}.{file_format}'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    AuditLog.objects.create(organization=organization, actor=request.user, area="organization", action="digidoc.download", target_model="DigiDocDocument", target_id=str(doc.pk), summary=f"Downloaded a DigiDoc {file_format.upper()}.", metadata={"format": file_format})
    return response


@login_required
def digidoc_preview(request, document_id):
    organization = _scope(request)
    doc = _owned_document(request, organization, document_id)
    try:
        pdf_data = _render_pdf_isolated(doc)
        pages = _render_preview_images_isolated(pdf_data)
    except Exception:
        return HttpResponse("The document preview could not be generated.", status=400)
    active_snapshot = doc.personal_letterhead_snapshot if doc.letterhead_source == "personal" else doc.letterhead_snapshot
    if doc.letterhead_enabled and doc.letterhead_source == "personal" and not active_snapshot:
        return HttpResponse("The saved personal letterhead snapshot is unavailable.", status=400)
    letterhead = _snapshot_letterhead_display(active_snapshot) if doc.letterhead_enabled else None
    if doc.letterhead_enabled and not letterhead:
        letterhead = CompanyLetterhead.objects.filter(organization=organization).first()
    for page in pages:
        slot = doc.letterhead_first_slot if page["number"] == 1 else doc.letterhead_other_slot
        page["show_letterhead_guides"] = bool(letterhead and slot != "none" and (slot == "1" and letterhead.image or slot == "2" and letterhead.image_second))
        page["guide_top_pct"] = round((letterhead.margin_top_mm / 297) * 100, 4) if letterhead else 0
        page["guide_bottom_pct"] = round((letterhead.margin_bottom_mm / 297) * 100, 4) if letterhead else 0
        page["guide_left_pct"] = round((letterhead.margin_left_mm / 210) * 100, 4) if letterhead else 0
        page["guide_right_pct"] = round((letterhead.margin_right_mm / 210) * 100, 4) if letterhead else 0
    nonce = secrets.token_urlsafe(18)
    response = render(request, "attendance/digidoc_preview.html", {
        "document": doc, "pages": pages,
        "csp_nonce": nonce,
        "letterhead_margins": {
            "top": letterhead.margin_top_mm if letterhead else 0,
            "bottom": letterhead.margin_bottom_mm if letterhead else 0,
            "left": letterhead.margin_left_mm if letterhead else 0,
            "right": letterhead.margin_right_mm if letterhead else 0,
        },
        "has_letterhead_guides": any(page["show_letterhead_guides"] for page in pages),
    })
    response["Content-Security-Policy"] = f"default-src 'self'; img-src data:; style-src 'self' 'nonce-{nonce}'; script-src 'self'; object-src 'none'; frame-ancestors 'none'"
    response["X-Frame-Options"] = "DENY"
    response["Referrer-Policy"] = "same-origin"
    response["Cache-Control"] = "private, no-store"
    return response
