from __future__ import annotations
from docutils import nodes
from docutils.statemachine import StringList
from sphinx.util.docutils import switch_source_input
from sphinx.application import Sphinx
from sphinx.util.docutils import SphinxDirective
from sphinx.util.typing import ExtensionMetadata
from aioslsk.protocol.messages import ServerMessage

import inspect


class ServerMessagesDirective(SphinxDirective):

    def run(self) -> list[nodes.Node]:
        sections = []

        for message_type in ServerMessage.__subclasses__():
            section = nodes.section()
            section['ids'].append(nodes.make_id(message_type.__name__))
            section_title = nodes.title(text=message_type.__name__)

            section.append(section_title)
            # section.append(nodes.paragraph(text=message_type.__doc__))

            description = message_type.__doc__

            if description:
                docstring_lines = StringList(
                    inspect.cleandoc(description).splitlines()
                )
                with switch_source_input(self.state, docstring_lines):
                    node = nodes.paragraph()
                    self.state.nested_parse(docstring_lines, 0, node)

                section.append(node)

            sections.append(section)

        return sections


def setup(app: Sphinx) -> ExtensionMetadata:
    app.add_directive('server-messages', ServerMessagesDirective)

    return {
        'version': '0.1',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
