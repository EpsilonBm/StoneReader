"""Metadata extraction helpers for imported books."""

from __future__ import annotations

import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def _ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}")[0] + "}"
    return ""


def extract_epub_metadata(file_path: str) -> dict:
    meta: dict = {}
    try:
        with zipfile.ZipFile(file_path, "r") as archive:
            container_data = archive.read("META-INF/container.xml")
            root = ET.fromstring(container_data)
            ns = _ns(root.tag)
            rootfile = root.find(f".//{ns}rootfile")
            if rootfile is None:
                return meta

            opf_path = rootfile.attrib.get("full-path", "")
            if not opf_path:
                return meta
            opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
            opf_data = archive.read(opf_path)
            opf = ET.fromstring(opf_data)
            opf_ns = _ns(opf.tag)

            metadata = opf.find(f".//{opf_ns}metadata")
            if metadata is not None:
                for node in metadata:
                    local = node.tag.split("}")[-1].lower()
                    text = (node.text or "").strip()
                    if local == "title" and text and "title" not in meta:
                        meta["title"] = text
                    if local == "creator" and text and "author" not in meta:
                        meta["author"] = text

            manifest = {}
            manifest_node = opf.find(f".//{opf_ns}manifest")
            if manifest_node is not None:
                for item in manifest_node.findall(f"{opf_ns}item"):
                    iid = item.attrib.get("id")
                    href = item.attrib.get("href")
                    if iid and href:
                        manifest[iid] = urllib.parse.unquote(href)

            cover_id = None
            if metadata is not None:
                for node in metadata:
                    local = node.tag.split("}")[-1].lower()
                    if local == "meta" and node.attrib.get("name", "").lower() == "cover":
                        cover_id = node.attrib.get("content")
                        break

            if cover_id and cover_id in manifest:
                cover_rel = manifest[cover_id]
                cover_bytes = archive.read(opf_dir + cover_rel)
                ext = Path(cover_rel).suffix.lower() or ".jpg"
                meta["cover_bytes"] = cover_bytes
                meta["cover_ext"] = ext
    except Exception:
        return meta

    return meta


def extract_mobi_metadata(file_path: str) -> dict:
    meta: dict = {}
    try:
        import mobi  # type: ignore

        unpack_root, _ = mobi.extract(file_path)
        root = Path(unpack_root)
        opf_files = sorted(root.rglob("*.opf"))
        if not opf_files:
            return meta
        opf_path = opf_files[0]
        opf_data = opf_path.read_bytes()
        opf = ET.fromstring(opf_data)
        opf_ns = _ns(opf.tag)

        metadata = opf.find(f".//{opf_ns}metadata")
        if metadata is not None:
            for node in metadata:
                local = node.tag.split("}")[-1].lower()
                text = (node.text or "").strip()
                if local == "title" and text and "title" not in meta:
                    meta["title"] = text
                if local == "creator" and text and "author" not in meta:
                    meta["author"] = text

        manifest_node = opf.find(f".//{opf_ns}manifest")
        manifest = {}
        if manifest_node is not None:
            for item in manifest_node.findall(f"{opf_ns}item"):
                iid = item.attrib.get("id")
                href = item.attrib.get("href")
                if iid and href:
                    manifest[iid] = urllib.parse.unquote(href)

        cover_id = None
        if metadata is not None:
            for node in metadata:
                local = node.tag.split("}")[-1].lower()
                if local == "meta" and node.attrib.get("name", "").lower() == "cover":
                    cover_id = node.attrib.get("content")
                    break

        if cover_id and cover_id in manifest:
            rel = Path(manifest[cover_id])
            cpath = (opf_path.parent / rel).resolve()
            if cpath.exists():
                meta["cover_bytes"] = cpath.read_bytes()
                meta["cover_ext"] = cpath.suffix.lower() or ".jpg"
    except Exception:
        return meta

    return meta


def save_cover_bytes(storage_root: Path, file_path: str, cover_bytes: bytes, cover_ext: str) -> str | None:
    try:
        covers = storage_root / "covers"
        covers.mkdir(parents=True, exist_ok=True)
        stem = Path(file_path).stem
        safe = "".join(c for c in stem if c.isalnum() or c in {"_", "-"}).strip() or "cover"
        target = covers / f"{safe}{cover_ext}"
        target.write_bytes(cover_bytes)
        return str(target)
    except Exception:
        return None
