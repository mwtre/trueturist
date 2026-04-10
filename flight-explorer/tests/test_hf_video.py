import sys
import types


def test_text_to_video_calls_inference_client(monkeypatch):
    calls = {}

    class FakeInferenceClient:
        def __init__(self, *, provider, api_key):
            calls["provider"] = provider
            calls["api_key"] = api_key

        def text_to_video(self, prompt, *, model):
            calls["prompt"] = prompt
            calls["model"] = model
            return {"ok": True, "url": "https://example.invalid/video.mp4"}

    fake_hub = types.SimpleNamespace(InferenceClient=FakeInferenceClient)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    from app.hf_video import text_to_video

    out = text_to_video(
        prompt="A young man walking on the street",
        model="tencent/HunyuanVideo",
        provider="fal-ai",
        hf_token="hf_test_token",
    )

    assert out["ok"] is True
    assert calls == {
        "provider": "fal-ai",
        "api_key": "hf_test_token",
        "prompt": "A young man walking on the street",
        "model": "tencent/HunyuanVideo",
    }

