import io
import struct
import sys
from typing import Any

import cloudpickle
import trio


def get_subprocess_command(child_r, child_w, parent_pid):
    from . import _child
    return (
        sys.executable,
        '-m', _child.__name__,
        '--parent-pid', str(parent_pid),
        '--fd-read', str(child_r),
        '--fd-write', str(child_w),
    )


def pickle_value(value: Any) -> bytes:
    serialized_value = cloudpickle.dumps(value)
    return struct.pack('>I', len(serialized_value)) + serialized_value


async def coro_read_exactly(stream: trio.abc.ReceiveStream, num_bytes: int) -> bytes:
    buffer = io.BytesIO()
    bytes_remaining = num_bytes
    while bytes_remaining > 0:
        data = await stream.receive_some(bytes_remaining)
        if data == b'':
            raise trio.ClosedResourceError("Encuntered end of stream")
        buffer.write(data)
        bytes_remaining -= len(data)

    return buffer.getvalue()


async def coro_receive_pickled_value(stream: trio.abc.ReceiveStream) -> Any:
    len_bytes = await coro_read_exactly(stream, 4)
    serialized_len = int.from_bytes(len_bytes, 'big')
    serialized_result = await coro_read_exactly(stream, serialized_len)
    return cloudpickle.loads(serialized_result)


def sync_read_exactly(stream: io.BytesIO, num_bytes: int) -> bytes:
    buffer = io.BytesIO()
    bytes_remaining = num_bytes
    while bytes_remaining > 0:
        data = stream.read(bytes_remaining)
        if data == b'':
            raise ConnectionError("Got end of stream")
        buffer.write(data)
        bytes_remaining -= len(data)

    return buffer.getvalue()


def sync_receive_pickled_value(stream: io.BytesIO) -> Any:
    len_bytes = sync_read_exactly(stream, 4)
    serialized_len = int.from_bytes(len_bytes, 'big')
    serialized_result = sync_read_exactly(stream, serialized_len)
    return cloudpickle.loads(serialized_result)
