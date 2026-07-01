from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0007_modelconfiguration_chatsession_model_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="character",
            name="knowledge_base",
            field=models.TextField(blank=True, default="", help_text="Persistent knowledge and lore for this character."),
        ),
        migrations.AddField(
            model_name="chatsession",
            name="last_response_latency_ms",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="chatsession",
            name="memory_summary",
            field=models.TextField(blank=True, default="", help_text="Rolling summary of the conversation state"),
        ),
        migrations.AddField(
            model_name="chatsession",
            name="pinned_memory",
            field=models.TextField(blank=True, default="", help_text="Important facts the assistant should always remember in this session"),
        ),
    ]
