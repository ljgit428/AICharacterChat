from django.db import migrations, models

from chat.constants import DEFAULT_CHAT_SESSION_SETTINGS


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0020_remove_soulpatch_document_remove_soulpatch_character_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='default_enable_web_search',
            field=models.BooleanField(default=DEFAULT_CHAT_SESSION_SETTINGS["enable_web_search"]),
        ),
    ]
