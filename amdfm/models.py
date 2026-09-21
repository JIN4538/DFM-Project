from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from typing import Any

import numpy as np
import trimesh


def plain(value: Any) -> Any:
    """Strict JSON values. Missing/nonfinite measurements remain null, never zero."""
    if hasattr(value, "__dataclass_fields__"):
        return plain(asdict(value))
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, np.generic):
        return plain(value.item())
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def json_bytes(value: Any) -> bytes:
    return json.dumps(plain(value), ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


@dataclass
class Model:
    mesh: trimesh.Trimesh
    metadata: dict
    cad_features: list[dict] = field(default_factory=list)
    face_ids: np.ndarray | None = None
    body_ids: np.ndarray | None = None

    def select_body(self, body: int | None) -> "Model":
        if body is None:
            return self
        if self.body_ids is None or body not in self.body_ids:
            raise ValueError("선택한 CAD 솔리드를 찾을 수 없습니다.")
        mask = self.body_ids == body
        mesh = self.mesh.copy()
        mesh.update_faces(mask)
        mesh.remove_unreferenced_vertices()
        meta = dict(self.metadata)
        info = next(x for x in meta["bodies"] if x["body_id"] == body)
        meta.update(selected_body=body, solid_count=1, exact_volume_mm3=info["volume_mm3"],
                    exact_area_mm2=info["area_mm2"], cad_valid=info["valid"],
                    cavity_shell_count=info["cavity_shell_count"])
        return Model(mesh, meta, [x for x in self.cad_features if x["body_id"] == body],
                     self.face_ids[mask], self.body_ids[mask])

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        digest.update(json_bytes(self.metadata))
        digest.update(np.asarray(self.mesh.vertices, dtype="<f8").tobytes())
        digest.update(np.asarray(self.mesh.faces, dtype="<i8").tobytes())
        return digest.hexdigest()


@dataclass
class Finding:
    id: str
    title: str
    status: str  # attention, observed, not_detected, unknown, not_applicable
    reason: str
    action: str
    method: str
    evidence: list[str]
    measurements: dict = field(default_factory=dict)
    face_indices: list[int] = field(default_factory=list)
    cad_face_ids: list[int] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    severity: str = "review"

