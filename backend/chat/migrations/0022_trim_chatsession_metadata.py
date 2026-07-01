from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0021_userprofile_default_enable_web_search"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="chatsession",
            name="additional_context",
        ),
        migrations.RemoveField(
            model_name="chatsession",
            name="character_growth_summary",
        ),
        migrations.RemoveField(
            model_name="chatsession",
            name="enable_web_search",
        ),
        migrations.RemoveField(
            model_name="chatsession",
            name="knowledge_updates_summary",
        ),
        migrations.RemoveField(
            model_name="chatsession",
            name="memory_summary",
        ),
        migrations.RemoveField(
            model_name="chatsession",
            name="model_config",
        ),
        migrations.RemoveField(
            model_name="chatsession",
            name="output_language",
        ),
        migrations.RemoveField(
            model_name="chatsession",
            name="pinned_memory",
        ),
        migrations.RemoveField(
            model_name="chatsession",
            name="user_persona",
        ),
        migrations.RemoveField(
            model_name="chatsession",
            name="user_preferences_summary",
        ),
        migrations.RemoveField(
            model_name="chatsession",
            name="world_time",
        ),
    ]
