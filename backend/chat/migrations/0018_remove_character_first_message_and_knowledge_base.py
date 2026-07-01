from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0017_messageattachment'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='character',
            name='first_message',
        ),
        migrations.RemoveField(
            model_name='character',
            name='knowledge_base',
        ),
    ]
