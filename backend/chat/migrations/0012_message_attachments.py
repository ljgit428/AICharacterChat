from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0011_userprofile'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='attachment',
            field=models.FileField(blank=True, null=True, upload_to='chat_attachments/'),
        ),
        migrations.AddField(
            model_name='message',
            name='attachment_kind',
            field=models.CharField(
                blank=True,
                choices=[('text', 'Text'), ('image', 'Image'), ('video', 'Video')],
                default='',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='message',
            name='attachment_mime_type',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='message',
            name='attachment_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='message',
            name='attachment_text_content',
            field=models.TextField(blank=True, default=''),
        ),
    ]
