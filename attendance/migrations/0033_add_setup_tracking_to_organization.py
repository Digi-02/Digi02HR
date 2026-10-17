from django.db import migrations, models


def mark_existing_organizations_setup_completed(apps, schema_editor):
    """Mark all existing organizations as setup_completed so they are not
    forced into the new setup wizard."""
    Organization = apps.get_model('attendance', 'Organization')
    Organization.objects.all().update(setup_completed=True)


class Migration(migrations.Migration):

    dependencies = [
        ('attendance', '0032_organization_logo_is_light'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='setup_completed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='organization',
            name='setup_completed_steps',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='organization',
            name='setup_current_step',
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.RunPython(mark_existing_organizations_setup_completed),
    ]
