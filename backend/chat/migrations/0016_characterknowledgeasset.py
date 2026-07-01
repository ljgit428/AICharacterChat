from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0015_character_user_address'),
    ]

    operations = [
        migrations.CreateModel(
            name='CharacterKnowledgeAsset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='character_knowledge_assets/')),
                ('attachment_name', models.CharField(blank=True, default='', max_length=255)),
                ('attachment_mime_type', models.CharField(blank=True, default='', max_length=100)),
                ('attachment_kind', models.CharField(blank=True, choices=[('text', 'Text'), ('image', 'Image'), ('video', 'Video')], default='', max_length=16)),
                ('attachment_text_content', models.TextField(blank=True, default='')),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('character', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='knowledge_assets', to='chat.character')),
            ],
            options={
                'ordering': ['sort_order', 'id'],
            },
        ),
    ]
