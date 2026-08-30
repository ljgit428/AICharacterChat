from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0046_share_defaults_true"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="location_latitude",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="location_longitude",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
