from __future__ import annotations

import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, Optional

from pydantic import BaseModel, Field


def escape_xml(value: Optional[str]) -> str:
    if value is None:
        return ""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def normalize_template_markers(xml: str) -> str:
    normalized = xml.replace("&lt;!--", "<!--").replace("--&gt;", "-->")
    normalized = normalized.replace("HABILIDADES_ENDT", "HABILIDADES_END")
    normalized = normalized.replace(" _START", "_START")
    normalized = normalized.replace(" _END", "_END")
    return normalized


@dataclass
class BlockDefinition:
    start_marker: str
    end_marker: str
    placeholders: List[str]


class ResumeExperience(BaseModel):
    titulo: str = ""
    cargo: str = ""
    periodo: str = ""
    descricao: str = ""


class ResumeItem(BaseModel):
    titulo: str = ""
    descricao: str = ""


class ResumeProject(BaseModel):
    titulo: str = ""
    nome_link: Optional[str] = None
    descricao: str = ""
    stack: Optional[str] = None


class ResumeData(BaseModel):
    nome: str = ""
    email: str = ""
    cidade: str = ""
    estado: str = ""
    celular: str = ""
    subtitulo: str = ""
    perfil: str = ""
    experiencias: List[ResumeExperience] = Field(default_factory=list)
    habilidades: List[ResumeItem] = Field(default_factory=list)
    formacoes: List[ResumeItem] = Field(default_factory=list)
    diferenciais: List[ResumeItem] = Field(default_factory=list)
    projetos: List[ResumeProject] = Field(default_factory=list)


def _extract_block(xml: str, start: str, end: str) -> Optional[tuple[str, str, str]]:
    try:
        start_idx = xml.index(start)
        end_idx = xml.index(end, start_idx + len(start))
    except ValueError:
        return None

    before = xml[: start_idx + len(start)]
    block = xml[start_idx + len(start) : end_idx]
    after = xml[end_idx:]
    return before, block, after


def _replace_placeholders(
    text: str, replacements: Mapping[str, Optional[str]]
) -> str:
    result = text
    for key, value in replacements.items():
        result = result.replace(f"[{key}]", escape_xml(value))
    return result


def _render_block(
    xml: str,
    start_marker: str,
    end_marker: str,
    items: Iterable[dict[str, Optional[str]]],
) -> str:
    block = _extract_block(xml, start_marker, end_marker)
    if block is None:
        return xml

    before, template_block, after = block
    rendered_items: List[str] = []
    for entry in items:
        rendered_items.append(_replace_placeholders(template_block, entry))

    return before + "".join(rendered_items) + after


def apply_resume_to_xml(xml: str, resume: ResumeData) -> str:
    normalized = normalize_template_markers(xml)

    normalized = _render_block(
        normalized,
        "<!-- EXPERIENCIAS_START -->",
        "<!-- EXPERIENCIAS_END -->",
        (
            {
                "titulo": item.titulo,
                "cargo": item.cargo,
                "periodo": item.periodo,
                "descricao": item.descricao,
            }
            for item in resume.experiencias
        ),
    )

    normalized = _render_block(
        normalized,
        "<!-- HABILIDADES_START -->",
        "<!-- HABILIDADES_END -->",
        (
            {
                "titulo": item.titulo,
                "descricao": item.descricao,
            }
            for item in resume.habilidades
        ),
    )

    normalized = _render_block(
        normalized,
        "<!-- FORMACOES_START -->",
        "<!-- FORMACOES_END -->",
        (
            {
                "titulo": item.titulo,
                "descricao": item.descricao,
            }
            for item in resume.formacoes
        ),
    )

    normalized = _render_block(
        normalized,
        "<!-- DIFERENCIAIS_START -->",
        "<!-- DIFERENCIAIS_END -->",
        (
            {
                "titulo": item.titulo,
                "descricao": item.descricao,
            }
            for item in resume.diferenciais
        ),
    )

    replacements = {
        "nome": resume.nome,
        "email": resume.email,
        "cidade": resume.cidade,
        "estado": resume.estado,
        "celular": resume.celular,
        "subtitulo": resume.subtitulo,
        "perfil": resume.perfil,
    }

    normalized = _replace_placeholders(normalized, replacements)
    return normalized


def fill_resume_template(
    template_path: Path,
    resume: ResumeData,
    workspace: Path,
) -> Path:
    if not template_path.exists():
        raise FileNotFoundError(f"Template não encontrado: {template_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        with zipfile.ZipFile(template_path) as zip_reader:
            zip_reader.extractall(tmpdir_path)

        content_path = tmpdir_path / "content.xml"
        if not content_path.exists():
            raise FileNotFoundError("Template ODT sem content.xml")

        content = content_path.read_text(encoding="utf-8")
        updated = apply_resume_to_xml(content, resume)
        content_path.write_text(updated, encoding="utf-8")

        with tempfile.NamedTemporaryFile(
            suffix=".odt", dir=workspace, delete=False
        ) as output_file:
            with zipfile.ZipFile(output_file.name, "w") as zip_writer:
                mimetype_path = tmpdir_path / "mimetype"
                if mimetype_path.exists():
                    # ODT exige que mimetype seja o primeiro arquivo, sem compressão
                    zip_writer.write(
                        mimetype_path,
                        "mimetype",
                        compress_type=zipfile.ZIP_STORED,
                    )

                for file_path in tmpdir_path.rglob("*"):
                    if not file_path.is_file():
                        continue
                    if file_path.name == "mimetype":
                        continue

                    arcname = file_path.relative_to(tmpdir_path)
                    zip_writer.write(
                        file_path,
                        arcname,
                        compress_type=zipfile.ZIP_DEFLATED,
                    )

        return Path(output_file.name)


def load_resume_from_file(path: Path) -> ResumeData:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    return ResumeData.model_validate(data)
