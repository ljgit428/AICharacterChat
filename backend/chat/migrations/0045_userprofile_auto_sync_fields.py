from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0044_merge_tts_and_draft_jobs"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="auto_sync_timezone",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="auto_sync_location",
            field=models.BooleanField(default=False),
        ),
    ]
