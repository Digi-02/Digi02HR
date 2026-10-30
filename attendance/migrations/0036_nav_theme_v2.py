from django.core.validators import RegexValidator
from django.db import migrations, models


HEX_VALIDATOR = RegexValidator(
    regex="^#[0-9A-Fa-f]{6}$", message="Enter a valid hex color like #3B5BFF."
)

OLD_DEFAULTS = {
    ("black", "#0A0A0A", "pill", "auto", "#0A0A0A"),
    ("clean", "#0A0A0A", "pill", "auto", "#0A0A0A"),
}

APPEARANCE_MAP = {
    "black": "dark",
    "white": "clean",
    "light_grey": "light",
    "clean": "clean",
    "brand": "brand",
    "custom": "custom",
    "dark": "dark",
    "light": "light",
}

ACTIVE_MAP = {
    "pill": "rounded_pill",
    "left_bar": "minimal",
    "soft_tint": "soft_pill",
    "outline": "outline",
    "rounded_pill": "rounded_pill",
    "soft_pill": "soft_pill",
    "minimal": "minimal",
    "custom": "custom",
}


def migrate_navigation(apps, schema_editor):
    Organization = apps.get_model("attendance", "Organization")
    AuditLog = apps.get_model("attendance", "AuditLog")

    for organization in Organization.objects.iterator():
        values = (
            organization.nav_style,
            organization.nav_bg_color,
            organization.nav_highlight_style,
            organization.nav_highlight_source,
            organization.nav_highlight_color,
        )
        has_custom_values = values not in OLD_DEFAULTS
        has_marker = (
            3 in (organization.setup_completed_steps or [])
            or AuditLog.objects.filter(
                organization_id=organization.pk, action="branding.update"
            ).exists()
        )
        explicit = has_custom_values or has_marker

        appearance = APPEARANCE_MAP.get(organization.nav_style, "clean")
        if organization.nav_style == "black" and not explicit:
            appearance = "clean"

        old_active = organization.nav_highlight_style
        active = ACTIVE_MAP.get(old_active, "rounded_pill")
        # An explicitly saved old Clean sidebar used the quiet soft-grey pill.
        # Preserve that intentional choice; untouched default rows get the new
        # black rounded pill above.
        if (
            explicit
            and organization.nav_style == "clean"
            and old_active == "pill"
            and organization.nav_highlight_source == "auto"
        ):
            active = "soft_pill"

        update_fields = {
            "nav_style": appearance,
            "nav_highlight_style": active,
            "nav_customized": explicit,
        }
        # The new default highlight is the Jobgio black. Old rows that used the
        # old default black keep the same value; custom colours are untouched.
        if organization.nav_highlight_color == "#0A0A0A" and not has_custom_values:
            update_fields["nav_highlight_color"] = "#111111"
        for field, value in update_fields.items():
            setattr(organization, field, value)
        organization.save(update_fields=list(update_fields))


def reverse_navigation(apps, schema_editor):
    Organization = apps.get_model("attendance", "Organization")
    reverse_appearance = {"clean": "white", "light": "light_grey", "dark": "black"}
    reverse_active = {
        "rounded_pill": "pill",
        "soft_pill": "soft_tint",
        "minimal": "left_bar",
        "outline": "outline",
        "custom": "pill",
    }
    for organization in Organization.objects.iterator():
        organization.nav_style = reverse_appearance.get(organization.nav_style, organization.nav_style)
        organization.nav_highlight_style = reverse_active.get(
            organization.nav_highlight_style, organization.nav_highlight_style
        )
        organization.save(update_fields=["nav_style", "nav_highlight_style"])


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0035_alter_organization_nav_style_favoritepage"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organization",
            name="nav_style",
            field=models.CharField(
                choices=[
                    ("clean", "Clean"),
                    ("light", "Light"),
                    ("dark", "Dark"),
                    ("brand", "Company Brand"),
                    ("custom", "Custom"),
                ],
                default="clean",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="organization",
            name="nav_highlight_style",
            field=models.CharField(
                choices=[
                    ("rounded_pill", "Rounded Pill"),
                    ("soft_pill", "Soft Pill"),
                    ("minimal", "Minimal Indicator"),
                    ("outline", "Outline"),
                    ("custom", "Custom Highlight"),
                ],
                default="rounded_pill",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="organization",
            name="nav_highlight_source",
            field=models.CharField(
                choices=[
                    ("auto", "Default Black"),
                    ("accent", "Company Brand Colour"),
                    ("custom", "Custom Colour"),
                ],
                default="auto",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="organization",
            name="nav_highlight_color",
            field=models.CharField(
                default="#111111",
                max_length=7,
                validators=[HEX_VALIDATOR],
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="nav_text_color",
            field=models.CharField(blank=True, default="", max_length=7, validators=[HEX_VALIDATOR]),
        ),
        migrations.AddField(
            model_name="organization",
            name="nav_muted_color",
            field=models.CharField(blank=True, default="", max_length=7, validators=[HEX_VALIDATOR]),
        ),
        migrations.AddField(
            model_name="organization",
            name="nav_hover_bg",
            field=models.CharField(blank=True, default="", max_length=7, validators=[HEX_VALIDATOR]),
        ),
        migrations.AddField(
            model_name="organization",
            name="nav_hover_fg",
            field=models.CharField(blank=True, default="", max_length=7, validators=[HEX_VALIDATOR]),
        ),
        migrations.AddField(
            model_name="organization",
            name="nav_active_icon_bg",
            field=models.CharField(blank=True, default="", max_length=7, validators=[HEX_VALIDATOR]),
        ),
        migrations.AddField(
            model_name="organization",
            name="nav_active_icon_fg",
            field=models.CharField(blank=True, default="", max_length=7, validators=[HEX_VALIDATOR]),
        ),
        migrations.AddField(
            model_name="organization",
            name="nav_customized",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(migrate_navigation, reverse_navigation),
    ]
