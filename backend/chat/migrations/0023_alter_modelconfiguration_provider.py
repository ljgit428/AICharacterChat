from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0022_trim_chatsession_metadata"),
    ]

    operations = [
        migrations.AlterField(
            model_name="modelconfiguration",
            name="provider",
            field=models.CharField(
                choices=[("gemini", "Gemini"), ("openai_compatible", "OpenAI Compatible")],
                default="openai_compatible",
                max_length=32,
            ),
        ),
    ]
