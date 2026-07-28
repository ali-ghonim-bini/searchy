from __future__ import annotations

import ctypes
import os
from pathlib import Path

AT_FDCWD = -100
AT_SYMLINK_NOFOLLOW = 0x100
STATX_BTIME = 0x0800


class _StatxTimestamp(ctypes.Structure):
    _fields_ = [
        ("tv_sec", ctypes.c_int64),
        ("tv_nsec", ctypes.c_uint32),
        ("reserved", ctypes.c_int32),
    ]


class _Statx(ctypes.Structure):
    _fields_ = [
        ("mask", ctypes.c_uint32),
        ("blksize", ctypes.c_uint32),
        ("attributes", ctypes.c_uint64),
        ("nlink", ctypes.c_uint32),
        ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32),
        ("mode", ctypes.c_uint16),
        ("spare0", ctypes.c_uint16),
        ("ino", ctypes.c_uint64),
        ("size", ctypes.c_uint64),
        ("blocks", ctypes.c_uint64),
        ("attributes_mask", ctypes.c_uint64),
        ("atime", _StatxTimestamp),
        ("btime", _StatxTimestamp),
        ("ctime", _StatxTimestamp),
        ("mtime", _StatxTimestamp),
        ("rdev_major", ctypes.c_uint32),
        ("rdev_minor", ctypes.c_uint32),
        ("dev_major", ctypes.c_uint32),
        ("dev_minor", ctypes.c_uint32),
        ("mnt_id", ctypes.c_uint64),
        ("dio_mem_align", ctypes.c_uint32),
        ("dio_offset_align", ctypes.c_uint32),
        ("spare", ctypes.c_uint64 * 12),
    ]


_libc = ctypes.CDLL(None, use_errno=True)
_statx = getattr(_libc, "statx", None)
if _statx is not None:
    _statx.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(_Statx),
    ]
    _statx.restype = ctypes.c_int


def creation_time(path: Path) -> float | None:
    if _statx is None:
        return None
    result = _Statx()
    encoded = os.fsencode(path)
    if _statx(AT_FDCWD, encoded, AT_SYMLINK_NOFOLLOW, STATX_BTIME, result) != 0:
        return None
    if not result.mask & STATX_BTIME:
        return None
    return result.btime.tv_sec + result.btime.tv_nsec / 1_000_000_000
