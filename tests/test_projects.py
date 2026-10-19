import pytest

from core import db
from core.projects import (
    Source,
    get_parser,
    get_pipeline,
    list_projects,
    load_all_sources,
    load_sources,
)


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    return tmp_path


def _project(root, name, yaml_text):
    (root / name).mkdir()
    (root / name / "sources.yaml").write_text(yaml_text, encoding="utf-8")


def test_lista_so_pastas_com_sources_yaml(projects_dir):
    _project(projects_dir, "bjj", "[]")
    _project(projects_dir, "sympla", "[]")
    (projects_dir / "sem_config").mkdir()
    (projects_dir / "Invalido").mkdir()
    (projects_dir / "Invalido" / "sources.yaml").write_text("[]")
    assert list_projects() == ["bjj", "sympla"]


def test_sources_ganham_projeto_e_dag_id(projects_dir):
    _project(
        projects_dir,
        "bjj",
        "- name: soucompetidor\n  url: https://exemplo\n  parser: soucompetidor\n",
    )
    _project(projects_dir, "sympla", "- name: eventos\n  url: https://x\n  parser: eventos\n  js: true\n")
    sources = load_all_sources()
    assert [s.dag_id for s in sources] == ["bjj__soucompetidor", "sympla__eventos"]
    assert sources[0] == Source(
        project="bjj", name="soucompetidor", url="https://exemplo", parser="soucompetidor"
    )
    assert sources[1].js is True


def test_nome_invalido_no_yaml(projects_dir):
    _project(projects_dir, "bjj", "- name: Sou Competidor\n  url: x\n  parser: p\n")
    with pytest.raises(ValueError):
        load_sources("bjj")


def test_projeto_real_bjj():
    assert "bjj" in list_projects()
    assert {s.dag_id for s in load_sources("bjj")} == {"bjj__soucompetidor"}
    assert callable(get_parser("bjj", "soucompetidor"))
    pipeline = get_pipeline("bjj")
    assert callable(pipeline.normalize) and callable(pipeline.store)


def test_nao_importa_nomes_estranhos():
    with pytest.raises(ValueError):
        get_parser("bjj", "../os")
    with pytest.raises(ValueError):
        get_pipeline("os.path")


def test_database_url(monkeypatch):
    monkeypatch.setenv("BJJ_DB_PASSWORD", "segredo")
    monkeypatch.delenv("BJJ_DATABASE_URL", raising=False)
    assert db.database_url("bjj") == "postgresql://bjj:segredo@postgres:5432/bjj"
    monkeypatch.setenv("BJJ_DATABASE_URL", "postgresql://outro")
    assert db.database_url("bjj") == "postgresql://outro"
