from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET

SVG_NS = "http://www.w3.org/2000/svg"
ALLOWED_TAGS = {"svg", "g", "path", "circle", "ellipse", "rect", "polygon", "polyline", "desc"}
DRAWABLE_TAGS = {"path", "circle", "ellipse", "rect", "polygon", "polyline"}
TONES = ("deep-shadow", "shadow", "base", "light", "highlight", "accent")
KINDS = {"tree", "bush", "grass"}
ALLOWED_ROLES = {
    "tree": {"root", "trunk", "branch", "foliage", "leaf", "detail"},
    "bush": {"branch", "foliage", "leaf", "detail"},
    "grass": {"grass", "leaf", "flower", "detail"},
}
FORBIDDEN_ATTRIBUTES = {"href", "style", "filter", "mask", "clip-path", "onload", "onclick"}


class SemanticSvgError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse(path: Path) -> ET.Element:
    try:
        return SafeET.fromstring(path.read_bytes())
    except Exception as exc:
        raise SemanticSvgError(f"Invalid or unsafe XML: {exc}") from exc


def _validate_tree(root: ET.Element) -> dict:
    if _local(root.tag) != "svg":
        raise SemanticSvgError("Root element must be <svg>")
    kind = root.get("data-asset-kind", "")
    asset_id = root.get("data-asset-id", "")
    if root.get("data-schema-version") != "1":
        raise SemanticSvgError("data-schema-version must be 1")
    if kind not in KINDS:
        raise SemanticSvgError(f"Unsupported data-asset-kind: {kind!r}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", asset_id):
        raise SemanticSvgError("data-asset-id must be a non-empty slug")
    view_box = root.get("viewBox", "").split()
    if len(view_box) != 4:
        raise SemanticSvgError("A four-number viewBox is required")
    try:
        numbers = [float(value) for value in view_box]
    except ValueError as exc:
        raise SemanticSvgError("viewBox must contain numbers") from exc
    if numbers[2] <= 0 or numbers[3] <= 0:
        raise SemanticSvgError("viewBox width and height must be positive")

    ids: set[str] = set()
    roles: Counter[str] = Counter()
    drawables = 0

    def visit(element: ET.Element, inherited_role: str | None, inherited_tone: str | None) -> None:
        nonlocal drawables
        tag = _local(element.tag)
        if tag not in ALLOWED_TAGS:
            raise SemanticSvgError(f"Forbidden SVG element: <{tag}>")
        for raw_name, value in element.attrib.items():
            name = _local(raw_name).lower()
            if name in FORBIDDEN_ATTRIBUTES or name.startswith("on"):
                raise SemanticSvgError(f"Forbidden attribute on <{tag}>: {name}")
            if "url(" in value.lower() or value.lower().startswith(("http:", "https:", "file:", "data:")):
                raise SemanticSvgError(f"External/resource reference is forbidden: {name}")
        element_id = element.get("id")
        if element_id:
            if element_id in ids:
                raise SemanticSvgError(f"Duplicate id: {element_id}")
            ids.add(element_id)
        role = element.get("data-role", inherited_role)
        tone = element.get("data-tone", inherited_tone)
        ignored = element.get("data-ignore") == "true"
        if tag in DRAWABLE_TAGS and not ignored:
            drawables += 1
            if role not in ALLOWED_ROLES[kind]:
                raise SemanticSvgError(f"Invalid or missing role {role!r} for {kind}")
            if tone not in TONES:
                raise SemanticSvgError(f"Invalid or missing tone {tone!r}")
            roles[role] += 1
        for child in element:
            visit(child, role, tone)

    visit(root, None, None)
    if not drawables:
        raise SemanticSvgError("SVG contains no renderable semantic geometry")
    if drawables > 2000:
        raise SemanticSvgError("SVG exceeds the 2000-element complexity limit")
    return {"asset_id": asset_id, "kind": kind, "view_box": numbers, "drawables": drawables, "roles": dict(roles)}


def validate_svg(path: Path) -> tuple[ET.Element, dict]:
    root = _parse(path)
    return root, _validate_tree(root)


def load_palette(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not data.get("biome"):
        raise SemanticSvgError("Palette schema_version=1 and biome are required")
    return data


def pigment(root: ET.Element, palette: dict, kind: str) -> tuple[ET.Element, dict]:
    output = copy.deepcopy(root)
    category = palette.get("categories", {}).get(kind)
    if not category:
        raise SemanticSvgError(f"Palette has no category {kind!r}")
    assignments: Counter[tuple[str, str, str]] = Counter()

    def visit(element: ET.Element, inherited_role: str | None, inherited_tone: str | None) -> None:
        role = element.get("data-role", inherited_role)
        tone = element.get("data-tone", inherited_tone)
        if _local(element.tag) in DRAWABLE_TAGS and element.get("data-ignore") != "true":
            try:
                color = category[role][TONES.index(tone)]
            except (KeyError, IndexError, ValueError) as exc:
                raise SemanticSvgError(f"No palette mapping for {kind}/{role}/{tone}") from exc
            if element.get("fill") != "none":
                element.set("fill", color)
            if element.get("stroke") not in (None, "none"):
                element.set("stroke", color)
            assignments[(role, tone, color)] += 1
        for child in element:
            visit(child, role, tone)

    visit(output, None, None)
    output.set("data-pigmented-biome", palette["biome"])
    mapping = [
        {"role": role, "tone": tone, "color": color, "elements": count}
        for (role, tone, color), count in sorted(assignments.items())
    ]
    return output, {"biome": palette["biome"], "mapping": mapping}


def serialize_svg(root: ET.Element) -> bytes:
    ET.register_namespace("", SVG_NS)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
