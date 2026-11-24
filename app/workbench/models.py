"""Bounded woodworking design contract. Coordinates and sizes are in millimetres."""
from __future__ import annotations
from typing import Literal
from uuid import uuid4
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import math
from urllib.parse import urlsplit

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Reference(Record):
    id: str
    name: str
    kind: Literal["image", "link", "note", "document"] = "image"
    url: str = Field(default="", max_length=4000)
    text: str = Field(default="", max_length=8000)

    @model_validator(mode="after")
    def valid_content(self):
        if self.kind == "link":
            self.url = self.url.strip()
            try:
                link = urlsplit(self.url)
                valid = (link.scheme.lower() in {"http", "https"} and bool(link.hostname)
                         and link.username is None and link.password is None
                         and not any(c.isspace() or ord(c) < 32 for c in self.url))
                link.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("请填写不含登录凭据的 HTTP 或 HTTPS 链接")
        elif self.kind == "note":
            self.text = self.text.strip()
            if not self.text:
                raise ValueError("请填写参考说明")
            self.url = ""
        elif not self.url:
            raise ValueError("参考文件地址不能为空")
        return self

class ReferenceInput(Record):
    expected_revision: int = Field(ge=1)
    kind: Literal["link", "note"]
    name: str = Field(default="", max_length=160)
    url: str = Field(default="", max_length=4000)
    text: str = Field(default="", max_length=8000)

class Evidence(Record):
    statement: str
    source_ids: list[str] = Field(default_factory=list)
    status: Literal["observed", "inferred", "unknown", "adopted"] = "unknown"

class Scale(Record):
    kind: Literal["target", "reference"]
    confirmed: bool = False
    note: str = ""
    length_mm: float | None = Field(default=None, gt=0, le=10000)

class Requirements(Record):
    body_height_mm: float | None = Field(default=None, gt=0, le=2500)
    load_kg: float | None = Field(default=None, gt=0, le=500)
    environment: str = ""
    tools: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=4000)

class Costing(Record):
    currency: str = Field(default="CNY", min_length=3, max_length=8)
    cutting_per_sheet: float | None = Field(default=None, ge=0, le=1_000_000)
    finish_per_sheet: float | None = Field(default=None, ge=0, le=1_000_000)
    assembly_hours: float | None = Field(default=None, ge=0, le=1_000)
    labor_per_hour: float | None = Field(default=None, ge=0, le=1_000_000)
    hardware_prices: dict[str, float] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2000)
    source: str = Field(default="", max_length=400)
    quoted_at: str = Field(default="", max_length=40)

    @field_validator("hardware_prices")
    @classmethod
    def valid_hardware_prices(cls, value):
        if len(value) > 200:
            raise ValueError("五金价格条目过多")
        for key, price in value.items():
            if not key or len(key) > 300:
                raise ValueError("五金价格键必须为 1 到 300 个字符")
            if not math.isfinite(price) or price < 0 or price > 1_000_000:
                raise ValueError("五金单价必须为非负数")
        return value

class ModuleConstraint(Record):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    operator: Literal["gte", "lte", "eq", "range"] = "range"
    value_mm: float | None = None
    min_mm: float | None = None
    max_mm: float | None = None
    priority: Literal["required", "recommended"] = "required"
    label: str = Field(default="", max_length=160)

    @model_validator(mode="after")
    def valid_bounds(self):
        values = (self.value_mm, self.min_mm, self.max_mm)
        if any(value is not None and (not math.isfinite(value) or value <= 0) for value in values):
            raise ValueError("模块约束数值必须为正的有限数值")
        if self.operator in {"gte", "lte", "eq"} and self.value_mm is None:
            raise ValueError("模块约束需要 value_mm")
        if self.operator == "range":
            if self.min_mm is None or self.max_mm is None or self.min_mm > self.max_mm:
                raise ValueError("范围约束需要有效的 min_mm 和 max_mm")
        return self

class FitSuggestion(Record):
    key: Literal["seat_height_mm", "seat_width_mm", "seat_depth_mm", "back_angle_deg", "seat_tilt_deg", "seat_back_angle_deg"]
    value: float = Field(ge=-180, le=2000)
    reason: str = Field(min_length=1, max_length=1000)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    anthropometry: dict[str, float | str | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def dimension_range(self):
        if self.key.endswith('_mm') and self.value <= 0:
            raise ValueError('长度建议必须大于零')
        if self.key == 'seat_back_angle_deg' and not 0 < self.value < 180:
            raise ValueError('座背夹角必须在 0 到 180 度之间')
        if self.key == 'back_angle_deg' and not 0 <= self.value <= 90:
            raise ValueError('旧版靠背后倾角必须在 0 到 90 度之间')
        if self.key == 'seat_tilt_deg' and not -90 < self.value < 90:
            raise ValueError('座面倾角必须在 -90 到 90 度之间')
        return self

class Module(Record):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal["support", "reach", "clearance", "storage", "surface", "base"]
    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(default="", max_length=1000)
    occupant: str = Field(default="", max_length=160)
    posture: str = Field(default="", max_length=160)
    anthropometry: dict[str, float | str | None] = Field(default_factory=dict)
    target: dict[str, float | str | None] = Field(default_factory=dict)
    confirmations: dict[str, bool] = Field(default_factory=dict)
    decisions: dict[str, Literal["keep", "adopt", "custom"]] = Field(default_factory=dict)
    suggestions: list[FitSuggestion] = Field(default_factory=list, max_length=5)
    constraints: list[ModuleConstraint] = Field(default_factory=list, max_length=50)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    status: Literal["inferred", "target", "confirmed", "conflict", "needs_review"] = "inferred"
    affected_part_ids: list[str] = Field(default_factory=list, max_length=100)
    notes: str = Field(default="", max_length=4000)

class Material(Record):
    name: str
    kind: Literal["solid_wood", "panel"]
    grain_axis: Literal["x", "z", "unknown"] = "unknown"
    properties: dict[str, float | str | None] = Field(default_factory=dict)
    stock_dimensions_mm: tuple[float, float, float] | None = None
    price_per_stock: float | None = Field(default=None, ge=0, le=10_000_000)
    currency: str = Field(default="CNY", min_length=3, max_length=8)
    price_note: str = Field(default="", max_length=200)

    @field_validator("stock_dimensions_mm")
    @classmethod
    def valid_stock(cls, value):
        if value is None:
            return value
        if any(not math.isfinite(v) or v <= 0 or v > 20000 for v in value):
            raise ValueError("板材规格必须为正数且在 20000 mm 以内")
        return value

class Feature(Record):
    id: str
    role: Literal["connection", "hardware_access"] = "connection"
    kind: Literal["hole", "slot"]
    face: Literal["top", "bottom", "left", "right", "front", "back"]
    u_mm: float
    v_mm: float
    diameter_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    depth_mm: float
    entry_mm: tuple[float, float, float] | None = None
    direction_local: tuple[float, float, float] | None = None

    @model_validator(mode="after")
    def explicit_axis(self):
        if (self.entry_mm is None) != (self.direction_local is None):
            raise ValueError("斜孔入口和局部轴向必须同时指定")
        if self.direction_local is not None:
            if self.kind != "hole" or abs(sum(x*x for x in self.direction_local)-1) > 1e-6:
                raise ValueError("显式孔轴须为孔及单位向量")
        return self

class PlaneCut(Record):
    normal_local: tuple[float, float, float]
    offset_mm: float

    @model_validator(mode="after")
    def unit_normal(self):
        if abs(sum(x*x for x in self.normal_local)-1) > 1e-6:
            raise ValueError("斜切平面法向须为单位向量")
        return self

class Part(Record):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str
    kind: str = "board"
    material_id: str
    size_mm: tuple[float, float, float]
    position_mm: tuple[float, float, float] = (0, 0, 0)
    rotation_deg: tuple[float, float, float] = (0, 0, 0)
    outline_mm: list[tuple[float, float]] | None = Field(default=None, max_length=100)
    plane_cuts: list[PlaneCut] = Field(default_factory=list, max_length=8)
    features: list[Feature] = Field(default_factory=list, max_length=200)

    @field_validator("position_mm", "rotation_deg")
    @classmethod
    def bounded_transform(cls, value):
        if any(not math.isfinite(v) or abs(v) > 100000 for v in value):
            raise ValueError("变换数值超出木作项目范围")
        return value

    @field_validator("size_mm")
    @classmethod
    def positive_size(cls, value):
        if any(not math.isfinite(v) or v <= 0 or v > 10000 for v in value):
            raise ValueError("零件尺寸必须在 0 到 10000 mm 之间")
        return value

class HardwareGeometry(Record):
    kind: Literal["bolt", "washer", "barrel_nut", "hex_nut"]
    diameter_mm: float = Field(gt=0, le=1000)
    length_mm: float = Field(gt=0, le=1000)
    bore_diameter_mm: float | None = Field(default=None, gt=0, le=1000)
    head_diameter_mm: float | None = Field(default=None, gt=0, le=1000)
    head_height_mm: float | None = Field(default=None, gt=0, le=1000)
    across_flats_mm: float | None = Field(default=None, gt=0, le=1000)

    @model_validator(mode="after")
    def meaningful_shape(self):
        if self.kind == "bolt":
            if self.head_diameter_mm is None or self.head_height_mm is None:
                raise ValueError("螺栓几何需要头径和头高")
            if self.head_diameter_mm < self.diameter_mm:
                raise ValueError("螺栓头径不能小于杆径")
        else:
            if self.bore_diameter_mm is None or self.bore_diameter_mm >= self.diameter_mm:
                raise ValueError("垫圈或螺母需要小于外径的内孔")
        if self.kind == "hex_nut":
            if self.across_flats_mm is None or not self.bore_diameter_mm < self.across_flats_mm <= self.diameter_mm:
                raise ValueError("六角螺母对边尺寸应在内孔与外径之间")
        return self

class HardwareInstance(Record):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    part_id: str
    feature_id: str
    offset_mm: float = Field(default=0, ge=-1000, le=10000)
    bore_part_id: str | None = None
    bore_feature_id: str | None = None

class Hardware(Record):
    name: str
    spec: str
    quantity: int = Field(ge=1, le=1000)
    geometry: HardwareGeometry | None = None
    instances: list[HardwareInstance] = Field(default_factory=list, max_length=1000)

class Joint(Record):
    name: str = ""
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal["screw", "half_lap", "dowel", "mortise_tenon", "cam_lock"]
    part_ids: list[str] = Field(min_length=2, max_length=10)
    feature_ids: list[str] = Field(default_factory=list)
    hardware: list[Hardware] = Field(default_factory=list)
    assembly_note: str = ""
    confirmed: bool = False

class Preservation(Record):
    """Design-specific constraints; inferred limits are never verified by an AI import."""
    status: Literal["unknown", "inferred", "verified"] = "unknown"
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    features: list[str] = Field(default_factory=list, max_length=20)
    adjustable_keys: list[str] = Field(default_factory=list, max_length=20)
    limits: list[ModuleConstraint] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=2000)

class BodyProfile(Record):
    height_mm: float = Field(gt=0, le=2500)
    sitting_height_mm: float = Field(gt=0, le=1500)
    hip_width_mm: float = Field(gt=0, le=1000)
    posture: Literal["upright", "reclined", "leaning", "cross_legged"]
    updated_at: str = Field(default_factory=now)

    @model_validator(mode="after")
    def body_measurements(self):
        if self.sitting_height_mm >= self.height_mm:
            raise ValueError("坐高是坐面到头顶的距离，应小于站立身高。")
        return self

class ReviewConfirmation(Record):
    fingerprint: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    decision: Literal['keep', 'adopt', 'custom'] = 'keep'


class ReviewState(Record):
    version: Literal[1] = 1
    confirmations: dict[str, ReviewConfirmation] = Field(default_factory=dict)


class Project(Record):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(default="我的木椅", min_length=1, max_length=120)
    revision: int = Field(default=1, ge=1)
    updated_at: str = Field(default_factory=now)
    scope: Literal["unknown", "supported", "unsupported"] = "unknown"
    scope_reason: str = ""
    references: list[Reference] = Field(default_factory=list, max_length=20)
    evidence: list[Evidence] = Field(default_factory=list, max_length=200)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    fabrication_mode: Literal["self", "kit", "shop"] | None = None
    baseline_revision: int | None = Field(default=None, ge=1)
    preservation: Preservation = Field(default_factory=Preservation)
    design_intent: Literal["restoration", "redesign"] = "restoration"
    reconstruction: bool = False
    profile_snapshot: BodyProfile | None = None
    review_state: ReviewState | None = None
    scale: Scale | None = None
    requirements: Requirements = Field(default_factory=Requirements)
    costing: Costing = Field(default_factory=Costing)
    modules: list[Module] = Field(default_factory=list, max_length=50)
    materials: dict[str, Material] = Field(default_factory=dict)
    parts: list[Part] = Field(default_factory=list, max_length=100)
    joints: list[Joint] = Field(default_factory=list, max_length=200)
    confirmed_revision: int | None = None
    acknowledged_limits: bool = False

    @field_validator("id")
    @classmethod
    def valid_id(cls, value):
        from uuid import UUID
        return str(UUID(value))

class CreateProject(Record):
    name: str = Field(default="我的木椅", min_length=1, max_length=120)

class UpdateProject(Record):
    expected_revision: int
    patch: dict

class ConfirmProject(Record):
    expected_revision: int
    acknowledged_limits: bool = False

class AcceptProposal(Record):
    expected_revision: int
    proposal_id: str
    accept_connections: bool = False

class Command(Record):
    expected_revision: int
    text: str = Field(min_length=1, max_length=4000)

class PreparationRequest(Record):
    expected_revision: int = Field(ge=1)
    text: str = Field(default="", max_length=4000)
    stage: Literal["reference", "fit", "manufacturing"] = "manufacturing"

class Restore(Record):
    expected_revision: int

EDITABLE_FIELDS = {
    "name", "scope", "scope_reason", "evidence", "assumptions",
    "fabrication_mode", "scale", "requirements", "costing", "modules", "materials", "parts", "joints",
    "preservation", "design_intent"
}
