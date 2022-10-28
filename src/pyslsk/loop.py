from abc import ABC, abstractmethod
import logging
from threading import Thread, Event
from typing import List


logger = logging.getLogger(__name__)


class Loopable(ABC):

    @abstractmethod
    def loop(self):
        pass

    @abstractmethod
    def stop(self):
        pass


class Loop(Thread):

    def __init__(self):
        super().__init__()
        self._stop_event = Event()
        self._loops: List[Loopable] = []

    def register_loop(self, loop: Loopable):
        self._loops.append(loop)

    def run(self):
        super().run()
        while not self._stop_event.is_set():
            for loop in self._loops:
                try:
                    loop.loop()
                except Exception:
                    logger.exception(f"exception running loop {loop!r}")

    def stop(self):
        logging.info("signaling loop to exit")
        self._stop_event.set()
        if self.is_alive():
            logger.debug(f"wait for thread {self!r} to finish")
            self.join(timeout=30)
            if self.is_alive():
                logger.warning(f"thread is still alive after 30s : {self!r}")
