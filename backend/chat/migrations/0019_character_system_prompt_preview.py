from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0018_remove_character_first_message_and_knowledge_base'),
    ]

    operations = [
        migrations.AddField(
            model_name='character',
            name='system_prompt_preview',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Editable character setup block injected into the system prompt.',
            ),
        ),
    ]
