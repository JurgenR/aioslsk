from __future__ import annotations
from dataclasses import fields
import docutils
from docutils import nodes
from docutils.parsers.rst.states import RSTState
from docutils.statemachine import StringList
from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment
from sphinx.util.docutils import switch_source_input
from sphinx.util.docutils import SphinxDirective
from sphinx.util.typing import ExtensionMetadata
from aioslsk.protocol.messages import (
    DistributedMessage,
    PeerInitializationMessage,
    PeerMessage,
    ServerMessage
)
from aioslsk.protocol.primitives import (
    array,
    boolean,
    bytearr,
    int32,
    ipaddr,
    string,
    uint16,
    uint32,
    uint64,
    uint8,
    Attribute,
    SimilarUser,
    Recommendation,
    RoomTicker,
    PotentialParent,
    UserStats,
    FileData,
    DirectoryData,
)
import inspect
from typing import Optional, Union


BASIC_TYPES = [
    boolean,
    bytearr,
    int32,
    ipaddr,
    string,
    uint16,
    uint32,
    uint64,
    uint8,
    string,
]
COMPLEX_TYPES = [
    Attribute,
    SimilarUser,
    Recommendation,
    RoomTicker,
    PotentialParent,
    UserStats,
    FileData,
    DirectoryData,
]


class DataStructuresDirective(SphinxDirective):
    def run(self) -> list[nodes.Node]:
        sections = []

        for struct_type in COMPLEX_TYPES:

            target, section = _create_message_section(
                self.state, self.env, struct_type, struct_type.__name__
            )

            section.extend(_create_description_nodes(self.env, struct_type))

            section.append(_build_parameter_table(struct_type))

            sections.extend([target, section])

        return sections


class ServerMessagesDirective(SphinxDirective):

    def run(self) -> list[nodes.Node]:
        sections = []

        for message_type in ServerMessage.__subclasses__():
            message_code = _find_message_code(message_type)

            target, section = _create_message_section(
                self.state, self.env, message_type,
                f"{message_type.__name__} (Code {message_code})"
            )

            section.extend(_create_description_nodes(self.env, message_type))

            status = _parse_status(self.env, message_type)

            details = nodes.field_list()
            details.append(_create_definition_item("Code:", f"{message_code} (0x{message_code:X})"))
            details.append(_create_definition_item("Status:", status))

            # Parameters
            ## Request
            if hasattr(message_type, 'Request'):
                request_cls = getattr(message_type, 'Request')

                param_list = _build_parameter_table(request_cls)

                details.append(_create_definition_item("Send:", param_list))

            ## Response
            if hasattr(message_type, 'Response'):
                response_cls = getattr(message_type, 'Response')

                param_list = _build_parameter_table(response_cls)

                details.append(_create_definition_item("Receive:", param_list))

            section.append(details)

            sections.extend([target, section])

        return sections


class _PeerMessagesDirectiveBase(SphinxDirective):
    BASE_MESSAGE_CLS = None

    def run(self) -> list[nodes.Node]:
        sections = []

        for message_type in self.BASE_MESSAGE_CLS.__subclasses__():
            message_code = _find_message_code(message_type)

            target, section = _create_message_section(
                self.state, self.env, message_type,
                f"{message_type.__name__} (Code {message_code})"
            )

            section.extend(_create_description_nodes(self.env, message_type))

            status = _parse_status(self.env, message_type)

            details = nodes.field_list()
            details.append(_create_definition_item("Code:", f"{message_code} (0x{message_code:X})"))
            details.append(_create_definition_item("Status:", status))

            request_cls = getattr(message_type, 'Request')
            param_list = _build_parameter_table(request_cls)
            details.append(_create_definition_item("Send:", param_list))

            section.append(details)

            # sections.append(section)
            sections.extend([target, section])

        return sections


class PeerInitMessagesDirective(_PeerMessagesDirectiveBase):
    BASE_MESSAGE_CLS = PeerInitializationMessage


class PeerMessagesDirective(_PeerMessagesDirectiveBase):
    BASE_MESSAGE_CLS = PeerMessage


class DistributedMessagesDirective(_PeerMessagesDirectiveBase):
    BASE_MESSAGE_CLS = DistributedMessage


def _get_optional_text(field) -> str:
    return 'Yes' if field.metadata.get('optional', False) else 'No'


def _get_condition_text(field) -> str:
    if_true = field.metadata.get('if_true', None)
    if_false = field.metadata.get('if_false', None)

    if if_true:
        return f'if {if_true} == true'

    if if_false:
        return f'if {if_false} == false'

    return ''


def _create_message_section(
        state: RSTState, env: BuildEnvironment,
        message_cls: type, title: str) -> tuple[nodes.target, nodes.section]:

    section = nodes.section()
    section_id = nodes.make_id(message_cls.__name__.lower())
    section['ids'].extend([section_id])
    section['names'].extend([nodes.fully_normalize_name(message_cls.__name__)])

    target = nodes.target('', '', ids=[message_cls.__name__.lower()])

    state.document.note_explicit_target(target)

    section_title = nodes.title(text=title)

    section.append(section_title)

    std_domain = env.get_domain('std')
    std_domain.labels[section_id] = (env.docname, section_id, title)
    std_domain.anonlabels[section_id] = (env.docname, section_id)

    return target, section


def _create_type_ref(type_cls: type) -> nodes.Node:
    type_reference = nodes.reference(text=type_cls.__name__)
    type_reference['refid'] = type_cls.__name__.lower()
    type_reference['internal'] = True
    return type_reference


def _create_type_nodes(type_cls: type, subtype_cls: Optional[type] = None) -> list[nodes.Node]:
    if type_cls == array:
        return [
            nodes.strong(text='array['),
            _create_type_ref(subtype_cls),
            nodes.strong(text=']')
        ]

    else:
        if type_cls in COMPLEX_TYPES:
            return [_create_type_ref(type_cls)]
        else:
            return [nodes.strong(text=type_cls.__name__)]


def _create_description(state: RSTState, type_cls: type) -> Optional[nodes.paragraph]:
    description = type_cls.__doc__
    if not description:
        return None

    docstring_lines = StringList(inspect.cleandoc(description).splitlines())
    with switch_source_input(state, docstring_lines):
        description_node = nodes.paragraph()
        state.nested_parse(docstring_lines, 0, description_node)

    return description_node


def _generate_doctree(env: BuildEnvironment, type_cls: type):
    docstring = type_cls.__doc__
    if not docstring:
        return None

    docstring = inspect.cleandoc(docstring)

    return docutils.core.publish_doctree(
        source=docstring,
        parser_name='rst',
        settings_overrides={
            'output_encoding': 'unicode',
            'env': env
        }
    )


def _create_description_nodes(env: BuildEnvironment, type_cls: type) -> list[nodes.Node]:
    if doctree := _generate_doctree(env, type_cls):
        return [
            component
            for component in doctree
            if not isinstance(component, nodes.field_list)
        ]

    return []


def _parse_status(env: BuildEnvironment, type_cls: type) -> str:
    if doctree := _generate_doctree(env, type_cls):
        for child in doctree.children:

            if not isinstance(child, nodes.field_list):
                continue

            for field in child.children:
                name, value = field.children
                if name.astext() == 'status':
                    return value.astext()

    return 'Unknown'


def _build_parameter_table(message_cls: type) -> nodes.table:
    if not fields(message_cls):
        return nodes.paragraph(text='No parameters')

    table = nodes.table()
    tgroup = nodes.tgroup(cols=5)
    table += tgroup

    for _ in range(5):
        tgroup += nodes.colspec(colwidth=1)

    thead = nodes.thead()
    tgroup += thead
    th_row = nodes.row()
    th_row += nodes.entry('', nodes.paragraph('', nodes.Text('#')))
    th_row += nodes.entry('', nodes.paragraph('', nodes.Text('Type')))
    th_row += nodes.entry('', nodes.paragraph('', nodes.Text('Name')))
    th_row += nodes.entry('', nodes.paragraph('', nodes.Text('Optional')))
    th_row += nodes.entry('', nodes.paragraph('', nodes.Text('Condition')))
    thead += th_row

    tbody = nodes.tbody()
    tgroup += tbody

    for idx, field in enumerate(fields(message_cls), start=1):
        type_cls = field.metadata['type']
        subtype_cls = field.metadata.get('subtype', None)

        id_cell = nodes.entry()
        id_cell += nodes.paragraph(text=str(idx))

        type_cell = nodes.entry()
        type_paragraph = nodes.paragraph()
        type_paragraph += _create_type_nodes(type_cls, subtype_cls)
        type_cell += type_paragraph

        name_cell = nodes.entry()
        name_cell += nodes.paragraph(text=field.name)

        optional_cell = nodes.entry()
        optional_cell += nodes.paragraph(text=_get_optional_text(field))

        condition_cell = nodes.entry()
        condition_cell += nodes.paragraph(text=_get_condition_text(field))

        row = nodes.row()
        row.extend([id_cell, type_cell, name_cell, optional_cell, condition_cell])

        tbody += row

    return table


def _build_parameter_list(message_cls: type) -> nodes.enumerated_list:
    param_list = nodes.enumerated_list()
    for field in fields(message_cls):
        field_text = nodes.paragraph()

        type_cls = field.metadata['type']
        subtype_cls = field.metadata.get('subtype', None)

        field_text.extend(_create_type_nodes(type_cls, subtype_cls))
        field_text.append(nodes.Text(f": {field.name}"))

        param_item = nodes.list_item()
        param_item.append(field_text)
        param_list.append(param_item)

    return param_list


def _create_definition_item(term: str, definition: Union[nodes.Node, str]) -> nodes.definition_list_item:
    item = nodes.definition_list_item()

    if isinstance(definition, str):
        definition = nodes.paragraph(text=definition)

    item.append(nodes.term(text=term))
    definition_node = nodes.definition()
    definition_node.append(definition)
    item.append(definition_node)

    return item


def _find_message_code(message_type: type) -> int:
    """Finds the message code in either the request or the response"""
    # Both have the MESSAGE_ID but either may not exist
    if hasattr(message_type, 'Request'):
        return getattr(message_type, 'Request').MESSAGE_ID

    if hasattr(message_type, 'Response'):
        return getattr(message_type, 'Response').MESSAGE_ID

    raise Exception(f"message class without message ID? {message_type}")


def setup(app: Sphinx) -> ExtensionMetadata:
    app.add_directive('data-structures', DataStructuresDirective)
    app.add_directive('server-messages', ServerMessagesDirective)
    app.add_directive('peer-init-messages', PeerInitMessagesDirective)
    app.add_directive('peer-messages', PeerMessagesDirective)
    app.add_directive('distributed-messages', DistributedMessagesDirective)

    return {
        'version': '0.1',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
