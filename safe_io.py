# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Controller I/O: no link traversal; anchored POSIX operations/Windows parent leases.

Explicit workspace roots are canonicalized by their caller once. Paths below
those roots must not contain symbolic links, reparse points or hardlinked files.
This protects controller writes, not arbitrary code running with the user's UID.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path, PureWindowsPath
import stat
import sys
import uuid


class UnsafePathError(ValueError):
    pass


def lexical_path(path: Path) -> Path:
    raw = os.fspath(path)
    if not raw or '\0' in raw:
        raise UnsafePathError('Empty path or NUL in controller path')
    if os.name == 'nt':
        win = PureWindowsPath(raw)
        if win.drive and (not win.root or len(win.drive) != 2 or win.drive[1] != ':'):
            raise UnsafePathError('Controller paths require a local absolute drive, not UNC/device/drive-relative paths')
        reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{p}{n}' for p in ('COM', 'LPT') for n in range(1, 10)}
        for part in win.parts[1:] if win.anchor else win.parts:
            if part in ('.', '..'):
                continue
            if (part.endswith((' ', '.')) or part.split('.')[0].upper() in reserved
                    or any(ord(c) < 32 or c in '<>:"|?*' for c in part)):
                raise UnsafePathError(f'Unsafe Windows controller path component: {part!r}')
    result = Path(os.path.abspath(os.path.expanduser(raw)))
    # macOS exposes these OS-owned aliases; do not resolve arbitrary user paths.
    if sys.platform == 'darwin':
        for alias in ('/var', '/tmp', '/etc'):
            prefix = Path(alias)
            if result.is_relative_to(prefix):
                result = Path('/private') / result.relative_to('/')
                break
    return result


def _regular(info, path):
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, 'st_file_attributes', 0) & 0x400):
        raise UnsafePathError(f'Controller file must be a single-link regular file: {path}')


@contextmanager
def _windows_directory(path: Path):
    """Lease one directory without sharing rename/delete rights; reject reparse points."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    class AttributeTag(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('tag', wintypes.DWORD)]
    query = kernel.GetFileInformationByHandleEx
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    query.restype = wintypes.BOOL
    # Query-only handles do not hold delete sharing; request FILE_LIST_DIRECTORY.
    handle = create(str(path), 0x0001, 1 | 2, None, 3, 0x02000000 | 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = AttributeTag()
        if not query(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not info.attributes & 0x10 or info.attributes & 0x400:
            raise UnsafePathError(f'Controller parent is a reparse point or not a directory: {path}')
        yield handle
    finally:
        close(handle)


@contextmanager
def directory(path: Path, *, create: bool = False):
    """Hold the entire directory chain while an operation is in progress."""
    from contextlib import ExitStack
    path = lexical_path(path)
    with ExitStack() as stack:
        current = Path(path.anchor)
        if os.name == 'nt':
            stack.enter_context(_windows_directory(current))
            for part in path.parts[1:]:
                current = current / part
                if create:
                    try:
                        os.mkdir(current, 0o700)
                    except FileExistsError:
                        pass
                stack.enter_context(_windows_directory(current))
            yield path, None
        else:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            fd = os.open(current, flags)
            stack.callback(os.close, fd)
            for part in path.parts[1:]:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                try:
                    fd = os.open(part, flags, dir_fd=fd)
                except OSError as exc:
                    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                        raise UnsafePathError(f'Linked/non-directory controller parent: {current / part}') from exc
                    raise
                stack.callback(os.close, fd)
                current = current / part
            yield path, fd


def mkdir(path: Path) -> None:
    with directory(path, create=True):
        pass


def check_path(path: Path, *, missing_ok: bool = True) -> Path:
    path = lexical_path(path)
    try:
        with directory(path.parent) as (_, fd):
            try:
                info = os.stat(path if fd is None else path.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                if missing_ok:
                    return path
                raise
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise UnsafePathError(f'Linked controller path: {path}')
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise UnsafePathError(f'Hardlinked controller file: {path}')
    except FileNotFoundError:
        if not missing_ok:
            raise
    return path


def _open_leaf(path: Path, fd, mode: str, *, shared: bool = False) -> int:
    writing = any(char in mode for char in 'wax+')
    if os.name == 'nt':
        import ctypes
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        access = (0x80000000 if 'r' in mode or '+' in mode else 0) | (0x40000000 if writing else 0)
        disposition = 1 if 'x' in mode else (4 if any(c in mode for c in 'wa') else 3)
        handle = create(str(path), access, 3 if shared else 1, None, disposition, 0x00200000, None)
        if handle == wintypes.HANDLE(-1).value:
            error = ctypes.get_last_error()
            if error in (80, 183):
                raise FileExistsError(errno.EEXIST, 'File already exists', str(path))
            raise ctypes.WinError(error)
        try:
            opened = msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_RDWR if '+' in mode else (os.O_WRONLY if writing else os.O_RDONLY)))
        except BaseException:
            close = kernel.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close(handle)
            raise
    else:
        flags = os.O_NOFOLLOW | os.O_NONBLOCK
        flags |= os.O_RDWR if '+' in mode else (os.O_WRONLY if writing else os.O_RDONLY)
        if 'x' in mode:
            flags |= os.O_CREAT | os.O_EXCL
        elif any(c in mode for c in 'wa'):
            flags |= os.O_CREAT
        if 'a' in mode:
            flags |= os.O_APPEND
        try:
            opened = os.open(path.name, flags, 0o600, dir_fd=fd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise UnsafePathError(f'Linked controller file: {path}') from exc
            raise
    try:
        _regular(os.fstat(opened), path)
        # Do not truncate until after checking the opened handle (not the pathname).
        if 'w' in mode:
            os.ftruncate(opened, 0)
        if 'a' in mode:
            os.lseek(opened, 0, os.SEEK_END)
        return opened
    except BaseException:
        os.close(opened)
        raise


@contextmanager
def open_file(path: Path, mode: str = 'r', *, encoding='utf-8', newline=None, buffering=-1, shared=False):
    path = lexical_path(path)
    with directory(path.parent, create=any(c in mode for c in 'wax')) as (_, fd):
        opened = _open_leaf(path, fd, mode, shared=shared)
        with os.fdopen(opened, mode, encoding=None if 'b' in mode else encoding,
                       newline=None if 'b' in mode else newline, buffering=buffering) as stream:
            yield stream


def read_bytes(path: Path) -> bytes:
    with open_file(path, 'rb') as stream:
        return stream.read()


def read_text(path: Path) -> str:
    with open_file(path, newline="") as stream:
        return stream.read()


def write_bytes(path: Path, data: bytes, *, exclusive: bool = False) -> None:
    with open_file(path, 'xb' if exclusive else 'wb') as stream:
        if stream.write(data) != len(data):
            raise OSError('Incomplete controller write')
        stream.flush()
        os.fsync(stream.fileno())


def write_text(path: Path, text: str, *, exclusive: bool = False) -> None:
    write_bytes(path, text.encode('utf-8'), exclusive=exclusive)


def atomic_write(path: Path, data: bytes) -> None:
    """Replace through a held parent, never following the destination file.

    Staging names are random exclusive creations. Failed replacements retain
    the complete pending snapshot; no unsafe truncate/copy fallback.
    """
    path = lexical_path(path)
    with directory(path.parent, create=True) as (parent, fd):
        destination = path if fd is None else path.name
        try:
            info = os.stat(destination, dir_fd=fd, follow_symlinks=False)
            _regular(info, path)
            permissions = stat.S_IMODE(info.st_mode)
        except FileNotFoundError:
            permissions = 0o600
        pending = parent / ('.arquilo-write-' + uuid.uuid4().hex + '.pending')
        opened = _open_leaf(pending, fd, 'xb')
        try:
            with os.fdopen(opened, 'wb') as stream:
                if stream.write(data) != len(data):
                    raise OSError('Incomplete staging write')
                stream.flush()
                os.fsync(stream.fileno())
                if os.name != 'nt':
                    os.fchmod(stream.fileno(), permissions)
        except BaseException:
            os.unlink(pending if fd is None else pending.name, dir_fd=fd)
            raise
        try:
            # Check again for diagnostics. Even a later leaf substitution is
            # replaced rather than followed; the leased/anchored parent cannot redirect.
            try:
                _regular(os.stat(destination, dir_fd=fd, follow_symlinks=False), path)
            except FileNotFoundError:
                pass
            if fd is None:
                os.replace(pending, path)
            else:
                os.replace(pending.name, path.name, src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException as exc:
            if isinstance(exc, OSError):
                exc.recovery_path = pending
                exc.add_note(f'Complete recovery file: {pending}')
            raise


def unique_directory(parent: Path, prefix: str) -> Path:
    with directory(parent, create=True) as (base, fd):
        for _ in range(10):
            name = prefix + '-' + uuid.uuid4().hex
            try:
                os.mkdir(base / name if fd is None else name, 0o700, dir_fd=fd)
                return base / name
            except FileExistsError:
                continue
        raise FileExistsError('Cannot allocate a unique controller directory')
