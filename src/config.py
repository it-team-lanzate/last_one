"""Load YAML config with optional 'extends' merge. Credentials from .env."""
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Config YAML inválido en {path}: {e}") from e
    if "extends" in data:
        extends_path = path.parent / data.pop("extends")
        base = load_config(extends_path)
        data = _deep_merge(base, data)
    return data
