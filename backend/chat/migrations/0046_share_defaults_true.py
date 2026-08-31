"""时间/位置/天气分享与位置自动检测默认全部打开，并为已有资料行回填。"""

from django.db import migrations, models


def forwards_copy(apps, schema_editor):
    UserProfile = apps.get_model("chat", "UserProfile")
    UserProfile.objects.all().update(
        share_location=True,
        share_weather=True,
        auto_sync_location=True,
    )


def reverse_copy(apps, schema_editor):
    UserProfile = apps.get_model("chat", "UserProfile")
    UserProfile.objects.all().update(
        share_location=False,
        share_weather=False,
        auto_sync_location=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0045_userprofile_auto_sync_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userprofile",
            name="share_location",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="share_weather",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="auto_sync_location",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(forwards_copy, reverse_copy),
    ]
