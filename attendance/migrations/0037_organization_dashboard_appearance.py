from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('attendance', '0036_nav_theme_v2'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='dashboard_appearance',
            field=models.CharField(
                choices=[('brand', 'DIGI HR brand'), ('white', 'White and neutral')],
                default='brand',
                max_length=12,
            ),
        ),
    ]
