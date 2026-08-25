"""把角色级 tts_config 迁移到音色库（TtsVoiceModel）。

旧模型里每个角色直填 onnx_model_dir/ref_audio_path；迁移后角色只存
voice_model_id 引用设置页登记的音色。相同 (user, engine, 模型目录,
参考音频) 的配置去重共用一条音色记录；model_version 顺带把旧写法
v2pr 归一化为 v2pro。原字段保留在 tts_config 里不删，作为回滚兜底。
"""

from django.db import migrations


def migrate_character_tts_to_voice_library(apps, schema_editor):
    TtsVoiceModel = apps.get_model('chat', 'TtsVoiceModel')
    Character = apps.get_model('chat', 'Character')

    aliases = {'v2pr': 'v2pro'}

    def voice_fields(cfg):
        onnx_dir = (cfg.get('onnx_model_dir') or '').strip()
        ref_audio = (cfg.get('ref_audio_path') or '').strip()
        return onnx_dir, ref_audio

    for character in Character.objects.exclude(tts_config={}).iterator():
        cfg = character.tts_config or {}
        onnx_dir, ref_audio = voice_fields(cfg)
        if not onnx_dir and not ref_audio:
            continue

        engine = (cfg.get('provider') or 'genie').strip().lower() or 'genie'
        if engine == 'none':
            continue

        existing = TtsVoiceModel.objects.filter(
            user_id=character.created_by_id,
            engine=engine,
            onnx_model_dir__iexact=onnx_dir,
            source_ckpt_path='',
        ).first() if onnx_dir else TtsVoiceModel.objects.filter(
            user_id=character.created_by_id,
            engine=engine,
            onnx_model_dir='',
            ref_audio_path__iexact=ref_audio,
        ).first()

        if existing:
            voice = existing
        else:
            model_version = (cfg.get('model_version') or '').strip().lower()
            model_version = aliases.get(model_version, model_version)
            fallback_name = (
                onnx_dir.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]
                or ref_audio.replace('\\', '/').rsplit('/', 1)[-1]
                or f'{character.name} Voice'
            )
            try:
                voice = TtsVoiceModel.objects.create(
                    user_id=character.created_by_id,
                    name=fallback_name[:100],
                    engine=engine,
                    model_version=model_version,
                    language=(cfg.get('language') or '').strip(),
                    voice_name=(cfg.get('voice_name') or '').strip(),
                    onnx_model_dir=onnx_dir,
                    ref_audio_path=ref_audio,
                    ref_audio_text=(cfg.get('ref_audio_text') or '').strip(),
                    ref_audio_language=(cfg.get('ref_audio_language') or '').strip(),
                )
            except Exception:
                # 同名冲突等极端情况：加后缀重试一次，保证迁移不中断。
                suffix = sum(1 for _ in TtsVoiceModel.objects.filter(user_id=character.created_by_id)) + 1
                voice = TtsVoiceModel.objects.create(
                    user_id=character.created_by_id,
                    name=f'{fallback_name[:90]} {suffix}',
                    engine=engine,
                    model_version=model_version,
                    language=(cfg.get('language') or '').strip(),
                    voice_name=(cfg.get('voice_name') or '').strip(),
                    onnx_model_dir=onnx_dir,
                    ref_audio_path=ref_audio,
                    ref_audio_text=(cfg.get('ref_audio_text') or '').strip(),
                    ref_audio_language=(cfg.get('ref_audio_language') or '').strip(),
                )

        cfg['model_version'] = aliases.get((cfg.get('model_version') or '').strip().lower(), (cfg.get('model_version') or '').strip().lower())
        cfg['voice_model_id'] = voice.pk
        character.tts_config = cfg
        character.save(update_fields=['tts_config'])


def restore_character_tts_config(apps, schema_editor):
    """反向迁移：移除 voice_model_id 引用（直填字段从未删除，配置即恢复）。"""
    Character = apps.get_model('chat', 'Character')
    for character in Character.objects.iterator():
        cfg = character.tts_config or {}
        if 'voice_model_id' in cfg:
            cfg.pop('voice_model_id', None)
            character.tts_config = cfg
            character.save(update_fields=['tts_config'])


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0036_ttsservicesettings_ttsvoicemodel'),
    ]

    operations = [
        migrations.RunPython(migrate_character_tts_to_voice_library, restore_character_tts_config),
    ]
