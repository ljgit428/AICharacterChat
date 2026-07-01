from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0008_character_knowledge_base_chatsession_memory_summary_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="character_growth_summary",
            field=models.TextField(blank=True, default="", help_text="How the character relationship or personality has evolved in this session"),
        ),
        migrations.AddField(
            model_name="chatsession",
            name="knowledge_updates_summary",
            field=models.TextField(blank=True, default="", help_text="Session-scoped knowledge updates gathered from conversation and web research"),
        ),
        migrations.AddField(
            model_name="chatsession",
            name="user_preferences_summary",
            field=models.TextField(blank=True, default="", help_text="Observed user preferences inferred during this session"),
        ),
        migrations.AddField(
            model_name="message",
            name="research_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
