from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0014_remove_chatsession_gemini_chat_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="character",
            name="user_address",
            field=models.CharField(
                blank=True,
                default="",
                help_text="How this character prefers to address the user.",
                max_length=100,
            ),
        ),
    ]
