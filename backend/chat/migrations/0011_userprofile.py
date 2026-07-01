from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0010_souldocument_soulpatch'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('avatar_url', models.URLField(blank=True, default='', max_length=500)),
                ('preferred_name', models.CharField(blank=True, default='', max_length=100)),
                ('pronouns', models.CharField(blank=True, default='', max_length=50)),
                ('bio', models.TextField(blank=True, default='')),
                ('timezone', models.CharField(blank=True, default='UTC', max_length=64)),
                ('interface_language', models.CharField(blank=True, default='English', max_length=50)),
                ('share_local_time', models.BooleanField(default=True)),
                ('share_location', models.BooleanField(default=False)),
                ('location_precision', models.CharField(choices=[('region', 'Region'), ('city', 'City'), ('exact', 'Exact')], default='city', max_length=16)),
                ('location_label', models.CharField(blank=True, default='', max_length=255)),
                ('share_weather', models.BooleanField(default=False)),
                ('preferred_relationship_style', models.CharField(blank=True, default='', max_length=64)),
                ('preferred_reply_length', models.CharField(choices=[('short', 'Short'), ('medium', 'Medium'), ('long', 'Long')], default='medium', max_length=16)),
                ('preferred_proactivity', models.CharField(choices=[('low', 'Low'), ('normal', 'Normal'), ('high', 'High')], default='normal', max_length=16)),
                ('preferred_emotional_intensity', models.CharField(choices=[('low', 'Low'), ('normal', 'Normal'), ('high', 'High')], default='normal', max_length=16)),
                ('allow_long_term_memory', models.BooleanField(default=True)),
                ('allow_preference_inference', models.BooleanField(default=True)),
                ('allow_research_profile_updates', models.BooleanField(default=False)),
                ('blocked_topics', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['user_id'],
            },
        ),
    ]
