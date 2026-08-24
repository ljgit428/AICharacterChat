from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0033_character_enable_web_search'),
    ]

    operations = [
        migrations.AddField(
            model_name='character',
            name='tts_config',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='角色级语音模型配置（引擎/模型版本/音色名/ONNX 目录/参考音频）。空 dict = 跟随全局默认音色。',
            ),
        ),
    ]
