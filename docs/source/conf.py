# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
sys.path.insert(0, os.path.abspath('../../src/aioslsk'))
sys.path.insert(0, os.path.abspath('../../src/'))

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
    'sphinxcontrib.autodoc_pydantic'
]

templates_path = ['_templates']
exclude_patterns = []

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

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
