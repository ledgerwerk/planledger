import os
import sys
from importlib import metadata

from docutils.parsers.rst.directives import html as docutils_html_directives
from docutils.parsers.rst.directives import misc as docutils_misc_directives

sys.path.insert(0, os.path.abspath(".."))
if (
    not hasattr(docutils_misc_directives, "Meta")
    and hasattr(docutils_html_directives, "Meta")
):
    docutils_misc_directives.Meta = docutils_html_directives.Meta

project = "planledger"
copyright = "2026, Planledger Contributors"
author = "Planledger Contributors"

try:
    release = metadata.version("planledger")
except metadata.PackageNotFoundError:
    try:
        from planledger._version import __version__ as release
    except ImportError:
        release = "0.1.0"

version = ".".join(release.split(".")[:2])

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx.ext.coverage",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
}

todo_include_todos = True
