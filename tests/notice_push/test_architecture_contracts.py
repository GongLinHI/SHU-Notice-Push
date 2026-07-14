import ast
from pathlib import Path


def _function_node(path: str, class_name: str, function_name: str):
    module = ast.parse(Path(path).read_text(encoding="utf-8"))
    owner = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )


def test_pipeline_run_contains_no_pagination_or_sql_implementation():
    run = _function_node("notice_push/pipeline.py", "NoticePipeline", "run")
    attributes = {
        node.attr
        for node in ast.walk(run)
        if isinstance(node, ast.Attribute)
    }
    string_literals = {
        node.value.lower()
        for node in ast.walk(run)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert "find_next_page_url" not in attributes
    assert not any("select " in value or "update " in value for value in string_literals)


def test_app_factory_delegates_provider_kind_to_registry():
    source = Path("notice_push/app_factory.py").read_text(encoding="utf-8")

    assert "provider.kind" not in source
    assert "build_summarizer(" in source


def test_removed_html_parser_has_no_compatibility_imports():
    imported_modules = {
        node.module
        for root in (Path("notice_push"), Path("tests"))
        for path in root.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
    }

    assert "notice_push.parsing.html" not in imported_modules
    assert not Path("notice_push/parsing/html.py").exists()


def test_runtime_loader_contains_no_production_urls_or_model_defaults():
    loader = Path("notice_push/settings/loader.py").read_text(encoding="utf-8")

    assert "www.shu.edu.cn" not in loader
    assert "ms.shu.edu.cn" not in loader
    assert "gs.shu.edu.cn" not in loader
    assert "api.deepseek.com" not in loader
    assert "api.moonshot.cn" not in loader
    assert "deepseek-v4-flash" not in loader
    assert "kimi-k2.7-code" not in loader


def test_runtime_yaml_is_only_source_of_production_llm_endpoints():
    python_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("notice_push").rglob("*.py")
    )

    assert "api.deepseek.com" not in python_source
    assert "api.moonshot.cn" not in python_source
    assert "kankanews.com" not in python_source
    assert "deepseek-v4-flash" not in python_source
    assert "kimi-k2.7-code" not in python_source


def test_blocked_publication_fallback_has_only_standard_library_imports():
    path = Path("scripts/workflow/write_blocked_publication_fallback.py")
    module = ast.parse(path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(module)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(module)
        if isinstance(node, ast.ImportFrom) and node.module != "__future__"
    )

    assert imported_roots == {"argparse", "json", "os", "pathlib"}
