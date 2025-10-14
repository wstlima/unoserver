from unoserver.template_filler import (  # type: ignore
    ResumeData,
    ResumeExperience,
    ResumeItem,
    apply_resume_to_xml,
    normalize_template_markers,
)


def test_normalize_template_markers_handles_common_issues():
    raw = "&lt;!-- DIFERENCIAIS _START --&gt; HABILIDADES_ENDT"
    normalized = normalize_template_markers(raw)
    assert "<!-- DIFERENCIAIS_START -->" in normalized
    assert "HABILIDADES_END" in normalized


def test_apply_resume_to_xml_renders_sections_and_escapes():
    xml = (
        "<root>"
        "&lt;!-- EXPERIENCIAS_START --&gt;"
        "<p>[titulo] - [cargo] - [periodo] - [descricao]</p>"
        "&lt;!-- EXPERIENCIAS_END --&gt;"
        "&lt;!-- HABILIDADES_START --&gt;"
        "<p>[titulo]: [descricao]</p>"
        "&lt;!-- HABILIDADES_END --&gt;"
        "<p>[nome] | [email] | [perfil]</p>"
        "</root>"
    )

    resume = ResumeData(
        nome="Fulano",
        email="fulano@example.com",
        perfil="Dev & Liderança",
        experiencias=[
            ResumeExperience(
                titulo="Empresa X",
                cargo="Dev",
                periodo="2023",
                descricao="Criou & testou",
            )
        ],
        habilidades=[ResumeItem(titulo="Python", descricao="Automação <IA>")],
    )

    rendered = apply_resume_to_xml(xml, resume)

    assert "Empresa X" in rendered
    assert "Dev" in rendered
    assert "Fulano" in rendered
    assert "fulano@example.com" in rendered
    assert "Dev &amp; Liderança" in rendered
    assert "Automação &lt;IA&gt;" in rendered
    assert "<!-- EXPERIENCIAS_START -->" in rendered