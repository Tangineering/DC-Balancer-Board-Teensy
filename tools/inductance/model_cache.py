"""
model_cache.py -- persist the meshed geometry a (config, mesh_pitch) resolves to.

Why: build_model() re-parses + re-rasterises the Gerbers (~10-30 s) every time,
and the sweep workflow needs the SAME geometry at several mesh pitches, consumed
by three different scripts (solver, render_mesh, export_mesh). Caching each
pitch's Model as a compressed .npz makes `regenerate_outputs.py` able to rebuild
every render/STL variant without touching the Gerbers again, and guarantees the
renders show exactly what was solved.

Cache key = <config base>_m<pitch>.npz inside the cache dir (default out/meshes/).
Each file also stores a fingerprint of the mask-affecting config fields; if the
config's geometry inputs changed since the cache was written, the entry is
treated as stale and rebuilt (closure/terminal moves do NOT invalidate -- they
don't alter the copper masks).

Everything written stays under tools/inductance/ (the caller passes a cache dir
inside out/).
"""

from __future__ import annotations

import hashlib
import json
import os

import numpy as np

import fasthenry as fh
from geometry import CopperMask


# Bump when the MESHING ALGORITHM changes (not the config) so existing caches are
# treated as stale and rebuilt. v2: pitch-scaled bridge_gaps (BRIDGE_GAP_MM) so the
# return plane no longer severs at fine pitch. v3: per-conductor policy -- forward
# net uses 'fraction' coverage + light fixed closing (preserves real via-clearance
# notches / current-crowding necks), return keeps 'any' + scaled closing.
MESH_ALGO_VERSION = 3


def _mask_fingerprint(cfg) -> str:
    """Hash of every config field that changes the copper masks / meshing, plus
    the meshing-algorithm version. Closure + terminals are excluded on purpose:
    they only pick nodes."""
    key = {
        "algo": MESH_ALGO_VERSION,
        "gerber_dir": os.path.normpath(str(cfg.get("gerber_dir", ""))).lower(),
        "forward": {"file": cfg["forward"]["file"], "point": list(cfg["forward"]["point"])},
        "return": {"file": cfg["return"]["file"], "point": list(cfg["return"]["point"])},
        "isolation_pitch_mm": float(cfg.get("isolation_pitch_mm", 0.1)),
        "return_margin_mm": float(cfg.get("return_margin_mm", 5.0)),
        "stackup": {k: float(v) for k, v in cfg["stackup"].items()},
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def cache_path(cache_dir: str, base: str, mesh_pitch: float) -> str:
    return os.path.join(cache_dir, f"{base}_m{mesh_pitch:g}.npz")


def _pack_mask(prefix: str, cm: CopperMask, d: dict) -> None:
    d[f"{prefix}_mask"] = cm.mask
    d[f"{prefix}_meta"] = np.array([cm.x0, cm.y0, cm.pitch], dtype=np.float64)


def _unpack_mask(prefix: str, z) -> CopperMask:
    x0, y0, pitch = (float(v) for v in z[f"{prefix}_meta"])
    return CopperMask(mask=z[f"{prefix}_mask"].astype(bool), x0=x0, y0=y0, pitch=pitch)


def save_model(model, path: str, fingerprint: str = "") -> None:
    """Serialize a gerber_inductance.Model to a compressed npz."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    d: dict = {}
    _pack_mask("fwd", model.forward.mask, d)
    _pack_mask("ret", model.ret.mask, d)
    _pack_mask("fwd_fine", model.fwd_fine, d)
    _pack_mask("ret_fine", model.ret_fine, d)
    d["scalars"] = np.array([model.mesh_pitch, model.iso_pitch, model.t_cu, model.h_di],
                            dtype=np.float64)
    d["fingerprint"] = np.array(fingerprint)
    np.savez_compressed(path, **d)


def load_model(path: str):
    """Load a Model saved by save_model. Returns (model, fingerprint)."""
    from gerber_inductance import Model          # local import: avoid cycle at module load
    with np.load(path, allow_pickle=False) as z:
        mesh_pitch, iso_pitch, t_cu, h_di = (float(v) for v in z["scalars"])
        fwd_net = _unpack_mask("fwd", z)
        ret_net = _unpack_mask("ret", z)
        fwd_fine = _unpack_mask("fwd_fine", z)
        ret_fine = _unpack_mask("ret_fine", z)
        fingerprint = str(z["fingerprint"])
    forward = fh.Conductor(mask=fwd_net, z=h_di + t_cu, thickness=t_cu, tag="f")
    ret = fh.Conductor(mask=ret_net, z=0.0, thickness=t_cu, tag="r")
    model = Model(forward, ret, fwd_fine, ret_fine, mesh_pitch, iso_pitch, t_cu, h_di)
    return model, fingerprint


def get_model(cfg, mesh_pitch: float, cache_dir: str, base: str,
              rebuild: bool = False, verbose: bool = True):
    """
    Cached build_model: return the Model for (cfg, mesh_pitch), loading it from
    <cache_dir>/<base>_m<pitch>.npz when present + fingerprint-fresh, else
    building it (build_model) and saving. cfg must have gerber_dir resolved
    (see gerber_inductance.load_config).
    """
    from gerber_inductance import build_model    # local import: avoid cycle at module load
    fp = _mask_fingerprint(cfg)
    path = cache_path(cache_dir, base, mesh_pitch)
    if not rebuild and os.path.isfile(path):
        try:
            model, cached_fp = load_model(path)
        except Exception as e:                   # noqa: BLE001 -- corrupt cache -> rebuild
            if verbose:
                print(f"    mesh cache unreadable ({e}); rebuilding {os.path.basename(path)}")
        else:
            if cached_fp == fp and model.mesh_pitch == float(mesh_pitch):
                if verbose:
                    print(f"    mesh cache hit: {os.path.basename(path)}")
                return model
            if verbose:
                print(f"    mesh cache stale (config geometry changed); rebuilding "
                      f"{os.path.basename(path)}")
    model = build_model(cfg, mesh_pitch=mesh_pitch, verbose=verbose)
    save_model(model, path, fingerprint=fp)
    if verbose:
        print(f"    mesh cached -> {path}")
    return model
