"""Tests de TTS (ElevenLabs) y del pegado de voz al video (sin red real)."""
from pathlib import Path

import pytest

from app.config import get_settings
from app.pipeline import tts, voiceover


# --- catálogo y resolución de voz ---
def test_listar_voces_no_vacio():
    voces = tts.listar_voces()
    assert "Sarah" in voces and len(voces) >= 3


def test_resolver_voice_id_por_nombre_id_y_default():
    assert tts.resolver_voice_id("Sarah") == tts.VOCES["Sarah"]
    raw = "21m00Tcm4TlvDq8ikWAM"
    assert tts.resolver_voice_id(raw) == raw            # ya es un id
    # vacío -> voz por defecto del catálogo
    assert tts.resolver_voice_id("") in tts.VOCES.values()


# --- voice_settings: velocidad recortada a [0.7, 1.2] ---
@pytest.mark.parametrize("vel,esperado", [(2.0, 1.2), (0.1, 0.7), (1.1, 1.1)])
def test_voice_settings_clampa_velocidad(vel, esperado):
    vs = tts.construir_voice_settings(vel, None, None)
    assert vs["speed"] == esperado
    assert 0.0 <= vs["stability"] <= 1.0 and 0.0 <= vs["similarity_boost"] <= 1.0


# --- generar_voz: payload correcto, sin llamar a la red real ---
def test_generar_voz_payload_y_archivo(tmp_path, monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        content = b"ID3-audio-falso"
        text = ""

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResp()

    monkeypatch.setattr("httpx.Client", FakeClient)
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "clave-test")

    out = tts.generar_voz("Hola mundo", voz="Sarah", velocidad=1.1, out_dir=tmp_path)

    assert out.exists() and out.suffix == ".mp3" and out.read_bytes()
    assert tts.VOCES["Sarah"] in captured["url"]
    assert captured["json"]["model_id"] == "eleven_multilingual_v2"
    assert captured["json"]["voice_settings"]["speed"] == 1.1
    assert captured["json"]["text"] == "Hola mundo"
    assert captured["headers"]["xi-api-key"] == "clave-test"     # va por header, no en el front


def test_generar_voz_sin_clave_falla(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "")
    with pytest.raises(RuntimeError):
        tts.generar_voz("hola", out_dir=tmp_path)


def test_generar_voz_texto_vacio_falla(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "x")
    with pytest.raises(RuntimeError):
        tts.generar_voz("   ", out_dir=tmp_path)


# --- comandos FFmpeg de pegado/mezcla ---
def test_cmd_reemplazo_mapea_voz():
    cmd = " ".join(voiceover.build_pegar_voz_cmd(
        Path("v.mp4"), Path("a.mp3"), Path("o.mp4")))
    assert "-map 0:v:0" in cmd and "-map 1:a:0" in cmd
    assert "-c:v copy" in cmd and "-shortest" in cmd


def test_cmd_mezcla_usa_amix():
    cmd = " ".join(voiceover.build_mezclar_voz_cmd(
        Path("v.mp4"), Path("a.mp3"), Path("o.mp4")))
    assert "amix=inputs=2" in cmd and "volume=" in cmd
    assert "-map 0:v:0" in cmd and "-shortest" in cmd
