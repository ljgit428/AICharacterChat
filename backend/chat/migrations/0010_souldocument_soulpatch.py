from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0009_chatsession_character_growth_summary_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SoulDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("path", models.CharField(max_length=255)),
                ("kind", models.CharField(choices=[("markdown", "Markdown"), ("json", "JSON"), ("text", "Text")], default="markdown", max_length=16)),
                ("title", models.CharField(max_length=120)),
                ("content", models.TextField(blank=True, default="")),
                ("is_locked", models.BooleanField(default=False)),
                ("can_user_edit", models.BooleanField(default=True)),
                ("can_auto_update", models.BooleanField(default=False)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("character", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="soul_documents", to="chat.character")),
            ],
            options={
                "ordering": ["path"],
            },
        ),
        migrations.CreateModel(
            name="SoulPatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_path", models.CharField(max_length=255)),
                ("operation", models.CharField(default="replace", max_length=32)),
                ("summary", models.CharField(max_length=255)),
                ("reason", models.TextField(blank=True, default="")),
                ("confidence", models.FloatField(default=0.0)),
                ("proposed_content", models.TextField(blank=True, default="")),
                ("source_refs", models.JSONField(blank=True, default=list)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("proposed", "Proposed"), ("applied", "Applied"), ("rejected", "Rejected")], default="proposed", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("applied_at", models.DateTimeField(blank=True, null=True)),
                ("character", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="soul_patches", to="chat.character")),
                ("chat_session", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="soul_patches", to="chat.chatsession")),
                ("document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="patches", to="chat.souldocument")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="souldocument",
            constraint=models.UniqueConstraint(fields=("character", "path"), name="unique_soul_document_path_per_character"),
        ),
    ]
