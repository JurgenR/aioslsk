from __future__ import annotations
from dataclasses import fields
from docutils import nodes
from docutils.statemachine import StringList
from sphinx.util.docutils import switch_source_input
from sphinx.application import Sphinx
from sphinx.util.docutils import SphinxDirective
from sphinx.util.typing import ExtensionMetadata
from aioslsk.protocol.messages import ServerMessage

import inspect
from typing import Union


class ServerMessagesDirective(SphinxDirective):

    def run(self) -> list[nodes.Node]:
        sections = []

        for message_type in ServerMessage.__subclasses__():
            message_code = _find_message_code(message_type)

            section = nodes.section()
            section['ids'].append(nodes.make_id(message_type.__name__))
            section_title = nodes.title(text=message_type.__name__)

            section.append(section_title)

            # Description
            description = message_type.__doc__
            if description:
                docstring_lines = StringList(
                    inspect.cleandoc(description).splitlines()
                )
                with switch_source_input(self.state, docstring_lines):
                    message_description = nodes.paragraph()
                    self.state.nested_parse(docstring_lines, 0, message_description)

                section.append(message_description)

            details = nodes.field_list()
            details.append(_create_definition_item("Code:", f"{message_code} (0x{message_code:X})"))
            details.append(_create_definition_item("Status:", "ACTIVE"))

            # Parameters
            ## Request
            if hasattr(message_type, 'Request'):
                request_cls = getattr(message_type, 'Request')

                param_list = _build_parameter_list(request_cls)

                details.append(_create_definition_item("Send:", param_list))

            ## Response
            if hasattr(message_type, 'Response'):
                response_cls = getattr(message_type, 'Response')

                param_list = _build_parameter_list(response_cls)

                details.append(_create_definition_item("Receive:", param_list))

            section.append(details)

            sections.append(section)

        return sections


def _build_parameter_list(message_cls):
    param_list = nodes.enumerated_list()
    for field in fields(message_cls):
        field_text = nodes.paragraph()
        field_text.extend(
            [
                nodes.strong(text=field.metadata['type'].__name__),
                nodes.Text(f": {field.name}")
            ]
        )
        param_item = nodes.list_item()
        param_item.append(field_text)
        param_list.append(param_item)

    return param_list


def _create_definition_item(term: str, definition: Union[nodes.Node, str]) -> nodes.Node:
    item = nodes.definition_list_item()

    if isinstance(definition, str):
        definition = nodes.paragraph(text=definition)

    item.append(nodes.term(text=term))
    definition_node = nodes.definition()
    definition_node.append(definition)
    item.append(definition_node)

    return item


def _find_message_code(message_type) -> int:
    """Finds the message code in either the request or the response"""
    # Both have the MESSAGE_ID but either may not exist
    if hasattr(message_type, 'Request'):
        return getattr(message_type, 'Request').MESSAGE_ID

    if hasattr(message_type, 'Response'):
        return getattr(message_type, 'Response').MESSAGE_ID

    raise Exception(f"message class without message ID? {message_type}")


def setup(app: Sphinx) -> ExtensionMetadata:
    app.add_directive('server-messages', ServerMessagesDirective)

    return {
        'version': '0.1',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
