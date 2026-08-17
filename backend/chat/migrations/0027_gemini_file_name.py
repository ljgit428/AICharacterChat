from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0026_modelroleassignment_alter_modelconfiguration_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='characterknowledgeasset',
            name='gemini_file_name',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='messageattachment',
            name='gemini_file_name',
            field=models.TextField(blank=True, default=''),
        ),
    ]
