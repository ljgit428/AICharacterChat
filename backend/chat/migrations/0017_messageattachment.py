from django.db import migrations, models
import django.db.models.deletion


def backfill_message_attachments(apps, schema_editor):
    Message = apps.get_model('chat', 'Message')
    MessageAttachment = apps.get_model('chat', 'MessageAttachment')

    attachments_to_create = []
    for message in Message.objects.exclude(attachment='').exclude(attachment__isnull=True).iterator():
        attachments_to_create.append(
            MessageAttachment(
                message_id=message.id,
                file=message.attachment.name,
                attachment_name=message.attachment_name,
                attachment_mime_type=message.attachment_mime_type,
                attachment_kind=message.attachment_kind,
                attachment_text_content=message.attachment_text_content,
                sort_order=0,
            )
        )

    if attachments_to_create:
        MessageAttachment.objects.bulk_create(attachments_to_create)


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0016_characterknowledgeasset'),
    ]

    operations = [
        migrations.CreateModel(
            name='MessageAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='chat_attachments/')),
                ('attachment_name', models.CharField(blank=True, default='', max_length=255)),
                ('attachment_mime_type', models.CharField(blank=True, default='', max_length=100)),
                ('attachment_kind', models.CharField(blank=True, choices=[('text', 'Text'), ('image', 'Image'), ('video', 'Video')], default='', max_length=16)),
                ('attachment_text_content', models.TextField(blank=True, default='')),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='chat.message')),
            ],
            options={
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.RunPython(backfill_message_attachments, migrations.RunPython.noop),
    ]
