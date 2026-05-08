import atexit

from memory.service import memory_service
from memory.facade import memory_facade

atexit.register(memory_service.close)
