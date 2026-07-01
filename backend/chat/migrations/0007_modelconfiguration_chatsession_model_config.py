from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0006_remove_character_gemini_file_uri_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ModelConfiguration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('provider', models.CharField(choices=[('gemini', 'Gemini'), ('openai_compatible', 'OpenAI Compatible')], default='gemini', max_length=32)),
                ('model_name', models.CharField(max_length=255)),
                ('api_key', models.CharField(blank=True, max_length=500)),
                ('base_url', models.URLField(blank=True, default='', max_length=500)),
                ('is_default', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='model_configurations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-is_default', 'name', 'id'],
                'constraints': [models.UniqueConstraint(fields=('user', 'name'), name='unique_model_configuration_name_per_user')],
            },
        ),
        migrations.AddField(
            model_name='chatsession',
            name='model_config',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='chat_sessions', to='chat.modelconfiguration'),
        ),
    ]
