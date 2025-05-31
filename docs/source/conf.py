# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
sys.path.insert(0, os.path.abspath('../../src/aioslsk'))
sys.path.insert(0, os.path.abspath('../../src/'))
sys.path.insert(0, os.path.abspath('_exts/'))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'aioslsk'
copyright = '2023, Jurgen'
author = 'Jurgen'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx_rtd_theme',
    'sphinx.ext.autodoc',
    'sphinxcontrib.autodoc_pydantic',
    'sphinx.ext.intersphinx',
    'message_generator'
]

templates_path = ['_templates']
exclude_patterns = ['deprecated/**']

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_css_files = [
    'css/custom.css'
]

# Autodoc settings
# autodoc_class_signature = 'seperated'
autodoc_member_order = 'bysource'
autodoc_typehints = 'description'
autodoc_default_options = {
    'undoc-members': True
}
autodoc_mock_imports = [
    'aiofiles',
    'async_upnp_client',
    'async_timeout',
    'mutagen'
]

autodoc_pydantic_model_show_json = False
autodoc_pydantic_settings_show_json = False

# Intersphinx mapping
intersphinx_mapping = {'python': ('https://docs.python.org/3.12', None)}
