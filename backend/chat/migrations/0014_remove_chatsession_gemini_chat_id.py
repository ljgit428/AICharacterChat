from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0013_default_language_to_simplified_chinese"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="chatsession",
            name="gemini_chat_id",
        ),
    ]
