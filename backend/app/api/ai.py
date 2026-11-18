"""Hybrid AI provider management and local model manager."""
from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..jobs import manager
from ..models import AIProvider
from ..schemas import JobRef, ModelDownload, ProviderIn, ProviderOut, ProviderUpdate
from ..security import set_secret
from ..services import llm, transcription, vision
from ..services.system_info import hardware_summary
from .common import get_or_404

router = APIRouter(tags=["ai"])

PRIVACY_SUMMARY = {
    "sent": [
        "Transcript text of the candidate clips being reviewed (plus up to 3 neighbouring sentences for boundary context)",
        "Sentence timestamps and anonymous speaker labels (S1, S2...)",
        "Top keywords of the video",
        "Selected still frames (JPEG, 512px) ONLY if 'Send video frames' is enabled for the provider",
    ],
    "never_sent": [
        "Original video or audio files",
        "Full-resolution media, file paths, project names or system information",
        "Your API keys to anyone other than the provider you configured",
    ],
    "notes": [
        "Cloud analysis is disabled by default and only runs for providers you enable and acknowledge.",
        "Offline mode blocks every external request; local Ollama keeps working.",
        "API keys are encrypted with Windows DPAPI (bound to your Windows user) and never sent to the browser.",
    ],
}


def _out(p: AIProvider) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "kind": p.kind, "base_url": p.base_url, "model": p.model, "enabled": p.enabled, "is_local": p.is_local,
            "has_key": p.has_key, "send_frames": p.send_frames, "privacy_acknowledged": p.privacy_acknowledged, "usage": p.usage or {},
            "last_test": p.last_test or {}}


def _cfg(p: AIProvider) -> llm.ProviderConfig:
    return llm.ProviderConfig(p.id, p.name, p.kind, p.base_url or "", p.model, p.enabled, p.is_local, p.send_frames, p.privacy_acknowledged)


@router.get("/api/ai/provider-kinds")
def provider_kinds():
    return llm.PROVIDER_KINDS


@router.get("/api/ai/privacy-summary")
def privacy_summary():
    return PRIVACY_SUMMARY


@router.get("/api/ai/providers", response_model=list[ProviderOut])
def list_providers(db: Session = Depends(get_db)):
    return [_out(p) for p in db.query(AIProvider).order_by(AIProvider.created_at).all()]


@router.post("/api/ai/providers", response_model=ProviderOut)
def create_provider(body: ProviderIn, db: Session = Depends(get_db)):
    spec = llm.PROVIDER_KINDS[body.kind]
    url = body.base_url or spec["default_url"]
    local = body.kind == "ollama" or llm.is_local_url(url)
    p = AIProvider(name=body.name, kind=body.kind, base_url=url, model=body.model or spec["default_model"], enabled=False,
                   is_local=local, send_frames=body.send_frames, privacy_acknowledged=local)
    db.add(p)
    db.flush()
    if body.api_key:
        set_secret(f"provider:{p.id}", body.api_key.strip())
        p.has_key = True
    if body.enabled:
        _enable(p)
    return _out(p)


def _enable(p: AIProvider) -> None:
    if not p.is_local and not p.privacy_acknowledged:
        raise HTTPException(400, "Review and acknowledge the privacy summary before enabling a cloud provider")
    if not p.is_local and config.get_settings().get("offline_mode"):
        raise HTTPException(400, "Offline mode is on - disable it in Settings to enable cloud providers")
    p.enabled = True


@router.put("/api/ai/providers/{pid}", response_model=ProviderOut)
def update_provider(pid: str, body: ProviderUpdate, db: Session = Depends(get_db)):
    p = get_or_404(db, AIProvider, pid, "Provider")
    if body.name is not None:
        p.name = body.name
    if body.base_url is not None:
        if body.base_url and not body.base_url.startswith(("http://", "https://")):
            raise HTTPException(400, "Invalid URL")
        p.base_url = body.base_url
        was_local = p.is_local
        p.is_local = p.kind == "ollama" or llm.is_local_url(body.base_url)
        if was_local and not p.is_local:
            p.privacy_acknowledged = False
            p.enabled = False
    if body.model is not None:
        p.model = body.model
    if body.send_frames is not None:
        if body.send_frames and not p.send_frames and not p.is_local:
            p.privacy_acknowledged = False  # scope of shared data changed - re-acknowledge
            p.enabled = False
        p.send_frames = body.send_frames
    if body.clear_key:
        set_secret(f"provider:{p.id}", None)
        p.has_key = False
    if body.api_key:
        set_secret(f"provider:{p.id}", body.api_key.strip())
        p.has_key = True
    if body.enabled is not None:
        if body.enabled:
            _enable(p)
        else:
            p.enabled = False
    return _out(p)


@router.post("/api/ai/providers/{pid}/acknowledge", response_model=ProviderOut)
def acknowledge(pid: str, db: Session = Depends(get_db)):
    p = get_or_404(db, AIProvider, pid, "Provider")
    p.privacy_acknowledged = True
    return _out(p)


@router.delete("/api/ai/providers/{pid}")
def delete_provider(pid: str, db: Session = Depends(get_db)):
    p = get_or_404(db, AIProvider, pid, "Provider")
    set_secret(f"provider:{p.id}", None)
    db.delete(p)
    return {"deleted": True}


@router.post("/api/ai/providers/{pid}/test")
def test_provider(pid: str, db: Session = Depends(get_db)):
    p = get_or_404(db, AIProvider, pid, "Provider")
    from datetime import datetime, timezone

    try:
        res = llm.test_connection(_cfg(p))
        res["at"] = datetime.now(timezone.utc).isoformat()
        u = dict(p.usage or {})
        u["input_tokens"] = u.get("input_tokens", 0) + res["usage"].get("input_tokens", 0)
        u["output_tokens"] = u.get("output_tokens", 0) + res["usage"].get("output_tokens", 0)
        u["requests"] = u.get("requests", 0) + 1
        p.usage = u
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "error": str(exc), "at": datetime.now(timezone.utc).isoformat()}
    p.last_test = {k: v for k, v in res.items() if k != "models"}
    out = _out(p)
    out["models"] = res.get("models", [])
    return out


@router.get("/api/ai/providers/{pid}/models")
def provider_models(pid: str, db: Session = Depends(get_db)):
    p = get_or_404(db, AIProvider, pid, "Provider")
    try:
        return {"models": llm.list_models(_cfg(p))}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Could not list models: {exc}")


# ---------------------------------------------------------------- model manager
@router.get("/api/models")
def models_status(db: Session = Depends(get_db)):
    hw = hardware_summary()
    free = shutil.disk_usage(config.MODELS_DIR).free
    eng = transcription.engine_status()
    cuda_ok, cuda_msg = transcription.cuda_usable() if eng["available"] else (False, "ASR engine unavailable")
    whisper = []
    for name, spec in transcription.WHISPER_MODELS.items():
        fits_ram = hw["ram_gb"] >= spec["ram_gb"] + 2
        fits_vram = hw.get("gpu_vram_gb", 0) >= spec["vram_gb"]
        whisper.append({**spec, "name": name, "installed": transcription.is_installed(name), "fits_ram": fits_ram,
                        "fits_gpu": bool(cuda_ok and fits_vram), "disk_ok": free > spec["size_mb"] * 1e6 * 1.3,
                        "active": config.get_settings()["whisper_model"] == name})
    ollama_models: list[str] = []
    ollama_error = None
    row = db.query(AIProvider).filter(AIProvider.kind == "ollama").first()
    try:
        cfgp = llm.ProviderConfig("probe", "Ollama", "ollama", (row.base_url if row else "") or llm.PROVIDER_KINDS["ollama"]["default_url"],
                                  "", True, True, False, True)
        ollama_models = llm.list_models(cfgp)
    except Exception as exc:  # noqa: BLE001
        ollama_error = f"Ollama not reachable ({type(exc).__name__}). Install from https://ollama.com to use local LLM analysis."
    return {
        "engine": eng, "cuda": {"usable": cuda_ok, "message": cuda_msg}, "hardware": hw, "disk_free_gb": round(free / 1e9, 1),
        "whisper": whisper,
        "vision": [{"name": "yunet", "label": "YuNet face detector (OpenCV Zoo)", "size_mb": round(vision.YUNET_SIZE_KB / 1024, 2),
                    "installed": vision.yunet_installed(), "fallback": "OpenCV Haar cascades (bundled, lower accuracy)"}],
        "ollama": {"models": ollama_models, "error": ollama_error,
                   "suggested": [{"name": "llama3.1:8b", "size_gb": 4.9, "ram_gb": 8}, {"name": "qwen2.5:7b", "size_gb": 4.7, "ram_gb": 8},
                                 {"name": "llama3.2:3b", "size_gb": 2.0, "ram_gb": 4}]},
        "recommended_whisper": _recommend(hw, cuda_ok),
    }


def _recommend(hw: dict, cuda_ok: bool) -> str:
    v = hw.get("gpu_vram_gb", 0)
    if cuda_ok and v >= 6:
        return "large-v3-turbo"
    if cuda_ok and v >= 3.5:
        return "small"
    if hw["ram_gb"] >= 12 and hw["cpu_cores"] >= 8:
        return "small"
    return "base"


@router.post("/api/models/download", response_model=JobRef)
def download_model(body: ModelDownload):
    if config.get_settings().get("offline_mode"):
        raise HTTPException(400, "Offline mode is enabled - disable it to download models")
    if body.kind == "whisper" and body.name not in transcription.WHISPER_MODELS:
        raise HTTPException(400, "Unknown Whisper model")
    if body.kind == "vision" and body.name != "yunet":
        raise HTTPException(400, "Unknown vision model")
    return {"job_id": manager.submit("model_download", None, body.model_dump())}


@router.delete("/api/models/{kind}/{name}")
def delete_model(kind: str, name: str):
    if kind == "whisper" and name in transcription.WHISPER_MODELS:
        transcription.unload_models()
        shutil.rmtree(transcription.model_dir(name), ignore_errors=True)
        return {"deleted": True}
    if kind == "vision" and name == "yunet":
        vision.YUNET_PATH.unlink(missing_ok=True)
        return {"deleted": True}
    raise HTTPException(400, "Unknown model")
