from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def skip_pydantic_members(
    app: Any,
    what: str,
    name: str,
    obj: Any,
    skip: bool,
    options: Any,
) -> bool:
    hidden_members = {
        "__init__",
        "bind",
        "construct",
        "copy",
        "dict",
        "from_orm",
        "json",
        "parse_file",
        "parse_obj",
        "parse_raw",
        "schema",
        "schema_json",
        "update_forward_refs",
        "validate",
        "model_construct",
        "model_copy",
        "model_dump",
        "model_dump_json",
        "model_json_schema",
        "model_parametrized_name",
        "model_post_init",
        "model_rebuild",
        "model_validate",
        "model_validate_json",
        "model_validate_strings",
    }

    hidden_prefixes = (
        "model_",
        "__pydantic_",
        "_",
    )

    if name in hidden_members:
        return True

    if name.startswith(hidden_prefixes):
        return True

    return skip


# -- Path setup ---------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

sys.path.insert(0, str(SRC))

from pymax import __version__  # noqa: E402

# -- Project information -----------------------------------------------------

project = "PyMax"
author = "ink-developer"
copyright = "2026, ink-developer"

release = __version__


# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
]

templates_path = ["_templates"]

autosummary_generate = True

exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
]

language = "ru"

# -- Autodoc -----------------------------------------------------------------

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "private-members": False,
    "special-members": False,
    "member-order": "bysource",
    "exclude-members": (
        "dict,json,parse_obj,parse_raw,schema,schema_json,"
        "copy,construct,from_orm,update_forward_refs,validate,"
        "model_dump,model_dump_json,model_validate,model_validate_json,"
        "model_validate_strings,model_json_schema,model_construct,"
        "model_copy,model_rebuild,model_post_init,model_parametrized_name"
    ),
}


autodoc_typehints_format = "short"
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_class_signature = "separated"
# -- Napoleon ----------------------------------------------------------------

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = False
napoleon_use_param = True
napoleon_use_rtype = True

# -- Intersphinx -------------------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- HTML --------------------------------------------------------------------

# html_theme = "shibuya"
html_theme = "furo"

html_title = "PyMax"
html_static_path = ["_static"]

pygments_style = "friendly"
pygments_dark_style = "monokai"

html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
}


def setup(app: Any) -> None:
    app.connect("autodoc-skip-member", skip_pydantic_members)
