from typing import Protocol


class UploadInfoProvider(Protocol):

    def get_upload_slots(self) -> int:
        ...

    def get_free_upload_slots(self) -> int:
        ...

    def get_queue_size(self) -> int:
        ...

    def has_slots_free(self) -> bool:
        ...

    def get_average_upload_speed(self) -> float:
        ...
