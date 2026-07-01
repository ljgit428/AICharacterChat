from django.db import migrations, models


def normalize_interface_locale(apps, schema_editor):
    UserProfile = apps.get_model("chat", "UserProfile")

    locale_map = {
        "Simplified Chinese": "zh-CN",
        "English": "en-US",
        "zh-CN": "zh-CN",
        "en-US": "en-US",
    }

    for source, target in locale_map.items():
        UserProfile.objects.filter(interface_language=source).update(interface_language=target)


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0012_message_attachments"),
    ]

    operations = [
        migrations.AlterField(
            model_name="chatsession",
            name="output_language",
            field=models.CharField(blank=True, default="Simplified Chinese", max_length=50),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="interface_language",
            field=models.CharField(blank=True, default="zh-CN", max_length=50),
        ),
        migrations.RunPython(normalize_interface_locale, migrations.RunPython.noop),
    ]
