import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from unoserver.api import ConversionConfig, _configuration_dir, load_conversion_config


@pytest.fixture(autouse=True)
def cleanup_cached_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("UNOSERVER_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("UNOSERVER_CONFIG_DIR", raising=False)
    yield


def test_load_default_configuration():
    config = load_conversion_config(None)
    assert isinstance(config, ConversionConfig)
    assert config.convert_to == "pdf"
    assert config.filter_options == []


def test_load_configuration_from_default_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("UNOSERVER_CONFIG_DIR", "configs")
        workspace = Path(tmp)
        monkeypatch.setenv("UNOSERVER_WORKSPACE", tmp)

        configs_dir = _configuration_dir()
        assert configs_dir == workspace / "configs"

        config_file = configs_dir / "custom.xml"
        config_file.write_text(
            """
            <configuration>
                <convertTo>pdf</convertTo>
                <exportFilter>writer_pdf_Export</exportFilter>
                <updateIndex>false</updateIndex>
                <option name="Quality" value="92" />
                <option name="ReduceImages" value="true" />
            </configuration>
            """,
            encoding="utf-8",
        )

        config = load_conversion_config("custom")
        assert config.convert_to == "pdf"
        assert config.filter_name == "writer_pdf_Export"
        assert config.update_index is False
        assert "Quality=92" in config.filter_options
        assert "ReduceImages=true" in config.filter_options


def test_load_configuration_not_found(tmp_path):
    with pytest.raises(HTTPException) as exc:
        load_conversion_config("missing-config")
    assert exc.value.status_code == 404
    assert "Configuração não encontrada" in exc.value.detail
