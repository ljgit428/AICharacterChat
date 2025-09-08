# Generated manually for renaming character.image_uri to character.file_uri

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0006_character_response_guidelines'),
    ]

    operations = [
        migrations.RenameField(
            model_name='character',
            old_name='image_uri',
            new_name='file_uri',
        ),
    ]