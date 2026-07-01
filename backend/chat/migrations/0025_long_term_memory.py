from django.core.validators import MaxLengthValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("chat", "0024_websearchconfiguration"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="is_private_mode",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Per-session override: when true, the long-term memory pipeline "
                    "skips writes for turns in this session."
                ),
            ),
        ),
        migrations.CreateModel(
            name="CharacterMemoryItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "short_id",
                    models.CharField(
                        help_text="4-byte hex id, stable for the lifetime of the entry.",
                        max_length=8,
                    ),
                ),
                (
                    "section",
                    models.CharField(
                        help_text=(
                            "Free-form section name picked and reused by the model."
                        ),
                        max_length=64,
                    ),
                ),
                (
                    "description",
                    models.TextField(
                        help_text=(
                            "Current description. Hard limit 200 visible characters "
                            "(Chinese counts as one)."
                        ),
                        validators=[MaxLengthValidator(200)],
                    ),
                ),
                (
                    "description_history",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text=(
                            "List of {old_desc, new_desc, reason, old_section, "
                            "new_section, old_time, new_time} dicts."
                        ),
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "character",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memory_items",
                        to="chat.character",
                    ),
                ),
            ],
            options={"ordering": ["section", "short_id"]},
        ),
        migrations.AddConstraint(
            model_name="charactermemoryitem",
            constraint=models.UniqueConstraint(
                fields=("character", "short_id"),
                name="unique_memory_short_id_per_character",
            ),
        ),
        migrations.AddIndex(
            model_name="charactermemoryitem",
            index=models.Index(
                fields=["character", "section"],
                name="chat_charactermem_char_section",
            ),
        ),
        migrations.AddIndex(
            model_name="charactermemoryitem",
            index=models.Index(
                fields=["character", "updated_at"],
                name="chat_charactermem_char_updated",
            ),
        ),
        migrations.CreateModel(
            name="MemoryAuditLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("create", "Create"),
                            ("update", "Update"),
                            ("delete", "Delete"),
                            ("merge", "Merge"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "entry_short_id",
                    models.CharField(blank=True, default="", max_length=8),
                ),
                ("before_description", models.TextField(blank=True, default="")),
                ("after_description", models.TextField(blank=True, default="")),
                ("reason", models.TextField(blank=True, default="")),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("celery_worker", "Celery worker"),
                            ("user_edit", "User edit"),
                        ],
                        default="celery_worker",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "character",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memory_audit_log",
                        to="chat.character",
                    ),
                ),
                (
                    "chat_session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="memory_audit_log",
                        to="chat.chatsession",
                    ),
                ),
                (
                    "message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="memory_audit_log",
                        to="chat.message",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="memoryauditlog",
            index=models.Index(
                fields=["character", "-created_at"],
                name="chat_memoryauditl_char_time",
            ),
        ),
    ]
