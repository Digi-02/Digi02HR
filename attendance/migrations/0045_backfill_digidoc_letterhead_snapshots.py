from django.core.files.base import ContentFile
from django.db import migrations


SAFE_IMAGE_BYTES = 8 * 1024 * 1024


def _image_bytes(field_file):
    if not field_file:
        return None
    try:
        with field_file.open("rb") as source:
            data = source.read(SAFE_IMAGE_BYTES + 1)
    except (OSError, ValueError):
        return None
    if not data or len(data) > SAFE_IMAGE_BYTES:
        return None
    return data


def backfill_letterhead_snapshots(apps, schema_editor):
    """Freeze the artwork each existing document currently prints with.

    A snapshot is a private copy, so replacing or deleting the company
    letterhead afterwards cannot change an already-saved document.
    """
    CompanyLetterhead = apps.get_model("attendance", "CompanyLetterhead")
    DigiDocDocument = apps.get_model("attendance", "DigiDocDocument")
    DigiDocLetterheadSnapshot = apps.get_model("attendance", "DigiDocLetterheadSnapshot")

    documents = DigiDocDocument.objects.filter(letterhead_enabled=True).iterator()
    for document in documents:
        if DigiDocLetterheadSnapshot.objects.filter(document_id=document.pk).exists():
            continue
        letterhead = CompanyLetterhead.objects.filter(
            organization_id=document.organization_id
        ).first()
        if not letterhead:
            continue
        for page_role, selected in (
            ("first", document.letterhead_first_slot or "1"),
            ("other", document.letterhead_other_slot or "none"),
        ):
            if selected not in {"1", "2"}:
                continue
            if selected == "2":
                image = letterhead.image_second
                image_format = letterhead.image_second_format
                image_width = letterhead.image_second_width
                image_height = letterhead.image_second_height
            else:
                image = letterhead.image
                image_format = letterhead.image_format
                image_width = letterhead.image_width
                image_height = letterhead.image_height
            data = _image_bytes(image)
            if not data or not image_format or not image_width or not image_height:
                continue
            snapshot = DigiDocLetterheadSnapshot(
                document_id=document.pk,
                organization_id=document.organization_id,
                page_role=page_role,
                source_kind="company",
                source_id=str(letterhead.pk),
                source_slot=selected,
                image_format=image_format,
                image_width=image_width,
                image_height=image_height,
                scale_mode=letterhead.scale_mode,
                margin_top_mm=letterhead.margin_top_mm,
                margin_bottom_mm=letterhead.margin_bottom_mm,
                margin_left_mm=letterhead.margin_left_mm,
                margin_right_mm=letterhead.margin_right_mm,
            )
            extension = "png" if image_format == "png" else "jpg"
            snapshot.image.save(
                f"backfill-{page_role}-{document.pk}.{extension}",
                ContentFile(data),
                save=True,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0044_digidoc_privacy_snapshots"),
    ]

    operations = [
        migrations.RunPython(
            backfill_letterhead_snapshots,
            migrations.RunPython.noop,
        ),
    ]
