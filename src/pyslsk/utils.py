import logging


logger = logging.getLogger()


def try_decoding(value: bytes):
    if isinstance(value, str):
        return value
    try:
        return value.decode('utf-8')
    except UnicodeDecodeError:
        try:
            return value.decode('cp1252')
        except Exception:
            logger.warning(f"failed to decode string {value!r}")
            raise


def get_duration(attributes):
    duration = ''
    for attr, value in attributes:
        if attr == 1:
            minutes, seconds = divmod(value, 60)
            hours, minutes = divmod(minutes, 60)
            duration = f"{hours}h {minutes}m {seconds}s"
            break
    return duration


def get_attribute_string(attributes):
    attr_str = []
    for attr, value in attributes:
        if attr == 0:
            attr_str.append(f"{value}kbps")
        elif attr == 2:
            attr_str.append('CBR' if value == 0 else 'VBR')
        elif attr == 4:
            attr_str.append(f"{(value / 1000):.1f}kHz")
        elif attr == 5:
            attr_str.append(f"{value}ch")

    return ' '.join(attr_str)


def ticket_generator(initial=1234):
    idx = initial
    while True:
        idx += 1
        if idx > 0xFFFFFFFF:
            idx = initial
        yield idx
