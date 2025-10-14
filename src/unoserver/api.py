import json
import logging
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError

from unoserver import client, server
from unoserver.template_filler import (
    ResumeData,
    fill_resume_template,
    load_resume_from_file,
)

logger = logging.getLogger("unoserver.api")

app = FastAPI(title="Unoserver API", version="1.0.0")

_uno_server: Optional[server.UnoServer] = None
_uno_client: Optional[client.UnoClient] = None


@dataclass
class ConversionConfig:
    convert_to: str = "pdf"
    filter_name: Optional[str] = None
    filter_options: List[str] = field(default_factory=list)
    update_index: bool = True
    input_filter: Optional[str] = None


def _workspace_dir() -> Path:
    base = Path(os.environ.get("UNOSERVER_WORKSPACE", "/workspace"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _configuration_dir() -> Path:
    config_dir = Path(os.environ.get("UNOSERVER_CONFIG_DIR", "configurations"))
    if not config_dir.is_absolute():
        config_dir = _workspace_dir() / config_dir
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def _resolve_config_path(config_name: str) -> Path:
    config_dir = _configuration_dir()
    candidate = Path(config_name)
    if not candidate.suffix:
        candidate = candidate.with_suffix(".xml")
    if not candidate.is_absolute():
        candidate = config_dir / candidate
    return candidate


def _resolve_template_path(template_name: str) -> Path:
    config_dir = _configuration_dir()
    candidate = Path(template_name)
    if not candidate.suffix:
        candidate = candidate.with_suffix(".odt")
    if not candidate.is_absolute():
        candidate = config_dir / candidate
    return candidate


def _resolve_json_path(filename: str) -> Path:
    config_dir = _configuration_dir()
    candidate = Path(filename)
    if not candidate.suffix:
        candidate = candidate.with_suffix(".json")
    if not candidate.is_absolute():
        candidate = config_dir / candidate
    return candidate


async def _store_upload_file(
    upload: UploadFile, workspace: Path, default_suffix: str
) -> Path:
    suffix = Path(upload.filename or "").suffix or default_suffix
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail="Arquivo enviado está vazio")

    with tempfile.NamedTemporaryFile(
        suffix=suffix, dir=workspace, delete=False
    ) as temp_file:
        temp_file.write(data)
        temp_file.flush()
        return Path(temp_file.name)


def _parse_bool(value: Optional[str], default: bool = True) -> bool:
    if value is None:
        return default
    clean = value.strip().lower()
    if clean in {"1", "true", "yes", "on"}:
        return True
    if clean in {"0", "false", "no", "off"}:
        return False
    return default


def load_conversion_config(config_name: Optional[str]) -> ConversionConfig:
    if not config_name:
        return ConversionConfig()

    path = _resolve_config_path(config_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Configuração não encontrada")

    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:  # pragma: no cover - erro tratado em runtime
        raise HTTPException(
            status_code=400,
            detail=f"Configuração XML inválida: {exc}",
        ) from exc

    root = tree.getroot()

    config = ConversionConfig()
    convert_to = root.findtext("convertTo")
    if convert_to:
        config.convert_to = convert_to.strip()

    filter_name = root.findtext("exportFilter") or root.findtext("filterName")
    if filter_name:
        config.filter_name = filter_name.strip()

    input_filter = root.findtext("inputFilter")
    if input_filter:
        config.input_filter = input_filter.strip()

    update_index = root.findtext("updateIndex")
    if update_index is not None:
        config.update_index = _parse_bool(update_index, default=config.update_index)

    for option in root.findall(".//option"):
        name = option.attrib.get("name")
        value = option.attrib.get("value")
        text = (option.text or "").strip()

        if name and value is not None:
            config.filter_options.append(f"{name}={value}")
        elif name and text:
            config.filter_options.append(f"{name}={text}")
        elif value:
            config.filter_options.append(value)
        elif text:
            config.filter_options.append(text)

    logger.info(
        "Aplicando configuração '%s' (convert_to=%s, filter=%s, options=%s)",
        config_name,
        config.convert_to,
        config.filter_name,
        config.filter_options,
    )
    return config


def _build_uno_server() -> server.UnoServer:
    interface = os.environ.get("UNOSERVER_XMLRPC_INTERFACE", "127.0.0.1")
    port = os.environ.get("UNOSERVER_XMLRPC_PORT", "2003")
    uno_interface = os.environ.get("UNOSERVER_UNO_INTERFACE", "127.0.0.1")
    uno_port = os.environ.get("UNOSERVER_UNO_PORT", "2002")
    conversion_timeout = os.environ.get("UNOSERVER_CONVERSION_TIMEOUT")
    stop_after = os.environ.get("UNOSERVER_STOP_AFTER")
    executable = os.environ.get("UNOSERVER_EXECUTABLE", "libreoffice")

    user_installation_path = Path(
        os.environ.get("UNOSERVER_USER_INSTALLATION", "/var/tmp/unoserver")
    )
    user_installation_path.mkdir(parents=True, exist_ok=True)

    uno = server.UnoServer(
        interface=interface,
        port=port,
        uno_interface=uno_interface,
        uno_port=uno_port,
        user_installation=user_installation_path.as_uri(),
        conversion_timeout=int(conversion_timeout)
        if conversion_timeout
        else None,
        stop_after=int(stop_after) if stop_after else None,
    )
    uno.start(executable=executable)
    return uno


def _build_uno_client() -> client.UnoClient:
    server_host = os.environ.get("UNOSERVER_XMLRPC_HOST")
    if not server_host:
        server_host = os.environ.get("UNOSERVER_XMLRPC_INTERFACE", "127.0.0.1")

    port = os.environ.get("UNOSERVER_XMLRPC_PORT", "2003")
    protocol = os.environ.get("UNOSERVER_XMLRPC_PROTOCOL", "http")
    host_location = os.environ.get("UNOSERVER_XMLRPC_HOST_LOCATION", "auto")

    return client.UnoClient(
        server=server_host,
        port=port,
        host_location=host_location,
        protocol=protocol,
    )


@app.on_event("startup")
async def startup_event() -> None:
    global _uno_server, _uno_client
    logger.info("Inicializando servidor UNO")
    _uno_server = _build_uno_server()
    _uno_client = _build_uno_client()
    logger.info("Servidor UNO pronto para uso")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if _uno_server is not None:
        logger.info("Encerrando servidor UNO")
        _uno_server.stop()


@app.post(
    "/convert",
    summary="Converte um documento usando o unoserver",
    response_class=Response,
)
async def convert_document(
    arquivo: UploadFile = File(..., description="Arquivo ODT a ser convertido"),
    configuracao: Optional[str] = Form(
        default=None,
        description="Nome do arquivo XML de configuração a ser aplicado",
    ),
    convert_to: Optional[str] = Form(
        default=None,
        description="Tipo de saída (pdf por padrão)",
    ),
) -> Response:
    if _uno_client is None:
        raise HTTPException(status_code=503, detail="Cliente UNO indisponível")

    config = load_conversion_config(configuracao)
    if convert_to:
        config.convert_to = convert_to

    workspace = _workspace_dir()
    original_suffix = Path(arquivo.filename or "document").suffix or ".odt"

    with tempfile.NamedTemporaryFile(
        suffix=original_suffix,
        dir=workspace,
        delete=False,
    ) as temp_in:
        temp_in.write(await arquivo.read())
        temp_in.flush()
        temp_input_path = Path(temp_in.name)

    try:
        resultado = _uno_client.convert(
            inpath=str(temp_input_path),
            outpath=None,
            convert_to=config.convert_to,
            filtername=config.filter_name,
            filter_options=config.filter_options,
            update_index=config.update_index,
            infiltername=config.input_filter,
        )
    finally:
        try:
            temp_input_path.unlink(missing_ok=True)
        except Exception as exc:  # pragma: no cover
            logger.warning("Não foi possível remover arquivo temporário: %s", exc)

    if resultado is None:
        raise HTTPException(status_code=500, detail="Conversão não retornou dados")

    media_type = "application/pdf"
    if config.convert_to and config.convert_to.lower() != "pdf":
        media_type = "application/octet-stream"

    output_name = (
        Path(arquivo.filename or "documento").with_suffix(f".{config.convert_to}")
    ).name

    headers = {
        "Content-Disposition": f'attachment; filename="{output_name}"',
        "X-Unoserver-Config": configuracao or "",
    }

    return Response(content=resultado, media_type=media_type, headers=headers)


@app.post(
    "/convert/resume",
    summary="Gera PDF a partir de um template ODT preenchido com dados JSON",
    response_class=Response,
)
async def convert_resume(
    template_file: Optional[UploadFile] = File(
        default=None,
        description="Arquivo ODT do template a ser preenchido",
    ),
    dados_json: Optional[UploadFile] = File(
        default=None,
        description="Arquivo JSON contendo os dados do currículo",
    ),
    template_nome: Optional[str] = Form(
        default=None,
        description="Nome do template salvo no workspace (usado quando nenhum arquivo é enviado)",
    ),
    dados_arquivo: Optional[str] = Form(
        default=None,
        description="Nome do arquivo JSON salvo no workspace (fallback caso nenhum arquivo seja enviado)",
    ),
    configuracao: Optional[str] = Form(
        default=None,
        description="Nome da configuração XML a ser aplicada",
    ),
    convert_to: Optional[str] = Form(
        default=None,
        description="Tipo de saída (pdf por padrão)",
    ),
) -> Response:
    if _uno_client is None:
        raise HTTPException(status_code=503, detail="Cliente UNO indisponível")

    workspace = _workspace_dir()
    cleanup: List[Path] = []
    template_label = ""
    resultado: Optional[bytes] = None
    config: ConversionConfig = ConversionConfig()

    try:
        if template_file is not None:
            template_path = await _store_upload_file(template_file, workspace, ".odt")
            cleanup.append(template_path)
            template_label = template_file.filename or template_path.name
        else:
            template_nome = template_nome or "template_well_v4.odt"
            template_path = _resolve_template_path(template_nome)
            if not template_path.exists():
                raise HTTPException(status_code=404, detail="Template não encontrado")
            template_label = template_path.name

        try:
            if dados_json is not None:
                raw_bytes = await dados_json.read()
                if not raw_bytes:
                    raise HTTPException(
                        status_code=400, detail="Arquivo JSON enviado está vazio"
                    )
                try:
                    payload = json.loads(raw_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise HTTPException(status_code=400, detail="JSON inválido") from exc
                resume_data = ResumeData.model_validate(payload)
            else:
                dados_arquivo = dados_arquivo or "dados_cv_completo.json"
                resume_data = load_resume_from_file(
                    _resolve_json_path(dados_arquivo)
                )
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Arquivo JSON não encontrado")
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        config = load_conversion_config(configuracao)
        if convert_to:
            config.convert_to = convert_to

        filled_template = fill_resume_template(template_path, resume_data, workspace)
        cleanup.append(filled_template)

        resultado = _uno_client.convert(
            inpath=str(filled_template),
            outpath=None,
            convert_to=config.convert_to,
            filtername=config.filter_name,
            filter_options=config.filter_options,
            update_index=config.update_index,
            infiltername=config.input_filter,
        )
    finally:
        for path in cleanup:
            path.unlink(missing_ok=True)

    if resultado is None:
        raise HTTPException(status_code=500, detail="Conversão não retornou dados")

    media_type = "application/pdf"
    if config.convert_to and config.convert_to.lower() != "pdf":
        media_type = "application/octet-stream"

    output_name = (
        Path(template_label).stem + f".{config.convert_to}"
        if template_label
        else f"documento.{config.convert_to}"
    )

    headers = {
        "Content-Disposition": f'attachment; filename="{output_name}"',
        "X-Unoserver-Template": template_label,
        "X-Unoserver-Config": configuracao or "",
    }

    return Response(content=resultado, media_type=media_type, headers=headers)
