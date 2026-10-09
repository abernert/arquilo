# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Per-launch process ownership using POSIX groups or Windows Job Objects.

No process is started here. The transport owns Popen and passes the returned
process to bind(). Windows launches stay suspended until job assignment; a
failed assignment must never fall back to running an unowned process.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any


JOB_EXIT_CODE = 0xD0A00001
REAP_TIMEOUT = 3.0


class ProcessTreeError(OSError):
    """Ownership or cleanup could not be established."""


@dataclass
class Cleanup:
    strategy: str
    reason: str
    parent_exit_before: int | None
    parent_exit_after: int | None = None
    actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    forced_parent_exit: bool = False
    job_empty: bool | None = None
    interrupted: bool = False

    def metadata(self) -> dict[str, Any]:
        return asdict(self)


def finish_cleanup(operation, result: Cleanup):
    """Repeated Ctrl+C records cancellation but cannot abandon owned children."""
    while True:
        try:
            return operation()
        except KeyboardInterrupt:
            result.interrupted = True


class ProcessTree:
    """One process group/job, with idempotent, serialized cleanup."""

    def __init__(self) -> None:
        self.proc = None
        self.job = _WindowsJob() if os.name == "nt" else None
        if os.name not in {"posix", "nt"}:
            raise ProcessTreeError(f"Unsupported process-tree platform: {os.name}")
        self.strategy = "windows-job" if self.job is not None else "posix-process-group"
        self._lock = threading.RLock()
        self.cleanup: Cleanup | None = None
        self.closed = False

    @property
    def popen_options(self) -> dict[str, Any]:
        # CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP. Ctrl+C is handled by
        # the controller, so child console delivery cannot race its cleanup.
        return {"creationflags": 0x4 | 0x200} if self.job is not None else {"start_new_session": True}

    def bind(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        if self.job is not None:
            self.job.assign_and_resume(proc.pid)

    def terminate(self, *, reason: str, grace_seconds: float) -> Cleanup:
        with self._lock:
            if self.cleanup is not None:
                return self.cleanup
            if self.closed or self.proc is None:
                raise ProcessTreeError("Cannot terminate an unbound/closed process tree")
            proc = self.proc
            result = Cleanup(self.strategy, reason, proc.poll())
            def stop_tree():
                if self.job is not None:
                    if self.job.active_processes():
                        self.job.terminate()
                        result.actions.append("TerminateJobObject")
                    deadline = time.monotonic() + REAP_TIMEOUT
                    while self.job.active_processes() and time.monotonic() < deadline:
                        time.sleep(.02)
                    result.job_empty = self.job.active_processes() == 0
                    if not result.job_empty:
                        raise ProcessTreeError("Windows job still has active processes after termination")
                else:
                    # The group outlives its leader. Never gate killpg on poll().
                    def send(sig: int) -> bool:
                        try:
                            os.killpg(proc.pid, sig)
                        except ProcessLookupError:
                            return False
                        except PermissionError:
                            # Darwin can reject killpg for a group containing
                            # only the just-killed, not-yet-reaped leader. Do
                            # not equate EPERM with success: first reap that
                            # leader, then require the *whole group* to be gone.
                            # Live/inaccessible descendants and permission
                            # failures before any successful signal still fail.
                            if sys.platform == "darwin" and result.actions:
                                rc = proc.poll()
                                killed_by_us = rc in [
                                    -int(signal.Signals[action]) for action in result.actions
                                    if action in {"SIGTERM", "SIGKILL"}]
                                if killed_by_us:
                                    try:
                                        os.killpg(proc.pid, 0)
                                    except ProcessLookupError:
                                        result.actions.append("group_absent_after_reap")
                                        return False
                                    except PermissionError:
                                        pass
                            raise
                        result.actions.append(signal.Signals(sig).name)
                        return True

                    if result.interrupted:
                        send(signal.SIGKILL)
                    elif send(signal.SIGTERM):
                        deadline = time.monotonic() + grace_seconds
                        while time.monotonic() < deadline:
                            proc.poll()  # reap the leader without ignoring remaining children
                            try:
                                os.killpg(proc.pid, 0)
                            except ProcessLookupError:
                                return  # No remaining group; do not send a redundant KILL.
                            except PermissionError:
                                # kill(0) is only an existence probe. macOS
                                # can return EPERM while a killed member exits.
                                # Actual TERM/KILL permission errors still fail.
                                pass
                            time.sleep(min(.02, max(0, deadline - time.monotonic())))
                        # A child may ignore TERM even when its parent has exited.
                        send(signal.SIGKILL)
            try:
                finish_cleanup(stop_tree, result)
            except OSError as exc:
                result.errors.append(f"{type(exc).__name__}: {exc}")
                # An owned Windows job also kills on close. A cleanup failure
                # remains a failure even if this last resort succeeds.
                if self.job is not None:
                    try:
                        finish_cleanup(self.job.close, result)
                        result.actions.append("CloseHandle(kill-on-close)")
                    except OSError as close_exc:
                        result.errors.append(str(close_exc))
                else:
                    try:
                        finish_cleanup(lambda: os.killpg(proc.pid, signal.SIGKILL), result)
                        result.actions.append("SIGKILL")
                    except ProcessLookupError:
                        pass
                    except OSError as kill_exc:
                        result.errors.append(f"SIGKILL failed: {kill_exc}")
            try:
                result.parent_exit_after = finish_cleanup(lambda: proc.wait(timeout=REAP_TIMEOUT), result)
            except subprocess.TimeoutExpired:
                result.errors.append("Parent process did not exit within the cleanup deadline")
            result.forced_parent_exit = result.parent_exit_before is None and (
                (self.job is not None and "TerminateJobObject" in result.actions
                 and result.parent_exit_after == JOB_EXIT_CODE)
                or (self.job is None and result.parent_exit_after in [
                    -int(signal.Signals[action]) for action in result.actions if action in {"SIGTERM", "SIGKILL"}])
            )
            self.cleanup = result
            return result

    def prepare_pipes(self) -> None:
        if self.job is None:
            for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                os.set_blocking(pipe.fileno(), False)

    def cancel_io(self, thread: threading.Thread) -> None:
        if self.job is not None and thread.is_alive() and thread.native_id is not None:
            self.job.cancel_io(thread.native_id)

    def close(self) -> None:
        with self._lock:
            if not self.closed:
                if self.job is not None:
                    self.job.close()
                self.closed = True

    def abort_start(self, proc: subprocess.Popen | None) -> None:
        """Fail closed if bind/resume (or Popen itself) raises, including Ctrl+C."""
        result = Cleanup(self.strategy, "launch_aborted", None)
        try:
            if proc is not None:
                # If assignment failed the process is still suspended and has
                # no children; if resume already ran, closing the job owns them.
                if self.job is None:
                    self.proc = proc
                    result = self.terminate(reason="launch_aborted", grace_seconds=.1)
                else:
                    finish_cleanup(self.close, result)
                    if proc.poll() is None:
                        finish_cleanup(proc.kill, result)
                    finish_cleanup(lambda: proc.wait(timeout=REAP_TIMEOUT), result)
        finally:
            finish_cleanup(self.close, result)
            if proc is not None:
                for pipe in (proc.stdin, proc.stdout, proc.stderr):
                    if pipe is not None:
                        finish_cleanup(pipe.close, result)


class _WindowsJob:
    """Lazy Win32 ctypes binding; importing the module has no OS side effects."""

    def __init__(self) -> None:
        import ctypes as c
        from ctypes import wintypes as w

        self.c = c
        self.api = c.WinDLL("kernel32", use_last_error=True)
        size_t = c.c_size_t

        class BasicLimit(c.Structure):
            _fields_ = [("PerProcessUserTimeLimit", c.c_int64), ("PerJobUserTimeLimit", c.c_int64),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", size_t),
                        ("MaximumWorkingSetSize", size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

        class IoCounters(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimit(c.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", size_t), ("JobMemoryLimit", size_t),
                        ("PeakProcessMemoryUsed", size_t), ("PeakJobMemoryUsed", size_t)]

        class Accounting(c.Structure):
            _fields_ = [(name, c.c_int64) for name in (
                "TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")]
            _fields_ += [(name, w.DWORD) for name in (
                "TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")]

        class ThreadEntry(c.Structure):
            _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ThreadID", w.DWORD),
                        ("th32OwnerProcessID", w.DWORD), ("tpBasePri", w.LONG),
                        ("tpDeltaPri", w.LONG), ("dwFlags", w.DWORD)]

        self.Accounting, self.ThreadEntry = Accounting, ThreadEntry
        signatures = {
            "CreateJobObjectW": ([c.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "ResumeThread": ([w.HANDLE], w.DWORD),
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Thread32First": ([w.HANDLE, c.POINTER(ThreadEntry)], w.BOOL),
            "Thread32Next": ([w.HANDLE, c.POINTER(ThreadEntry)], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "CancelSynchronousIo": ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        self.handle = self.api.CreateJobObjectW(None, None)
        self.check(self.handle, "CreateJobObjectW")
        try:
            limits = ExtendedLimit()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway
            self.check(self.api.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)),
                       "SetInformationJobObject")
        except BaseException:
            self.close()
            raise

    def check(self, value: Any, operation: str) -> None:
        if not value:
            error = self.c.get_last_error()
            raise ProcessTreeError(f"{operation} failed (WinError {error}): {self.c.FormatError(error).strip()}")

    def assign_and_resume(self, pid: int) -> None:
        process = self.api.OpenProcess(0x100 | 0x1, False, pid)  # SET_QUOTA | TERMINATE
        self.check(process, "OpenProcess")
        try:
            self.check(self.api.AssignProcessToJobObject(self.handle, process), "AssignProcessToJobObject")
        finally:
            self.check(self.api.CloseHandle(process), "CloseHandle(process)")
        self.resume(pid)

    def resume(self, pid: int) -> None:
        # Popen closes the primary thread handle. Recover the sole thread of
        # the still-suspended process through the documented Tool Help API.
        snapshot = self.api.CreateToolhelp32Snapshot(0x4, 0)  # SNAPTHREAD
        if snapshot == self.c.c_void_p(-1).value:
            self.check(False, "CreateToolhelp32Snapshot")
        try:
            entry = self.ThreadEntry()
            entry.dwSize = self.c.sizeof(entry)
            found = []
            more = self.api.Thread32First(snapshot, self.c.byref(entry))
            while more:
                if entry.th32OwnerProcessID == pid:
                    found.append(entry.th32ThreadID)
                entry.dwSize = self.c.sizeof(entry)
                more = self.api.Thread32Next(snapshot, self.c.byref(entry))
            if self.c.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                self.check(False, "Thread32First/Next")
            if len(found) != 1:
                raise ProcessTreeError(f"Expected one suspended primary thread for {pid}, found {len(found)}")
            thread = self.api.OpenThread(0x2, False, found[0])  # SUSPEND_RESUME
            self.check(thread, "OpenThread")
            try:
                count = self.api.ResumeThread(thread)
                if count == 0xFFFFFFFF:
                    self.check(False, "ResumeThread")
                if count != 1:
                    raise ProcessTreeError(f"Unexpected primary thread suspend count: {count}")
            finally:
                self.check(self.api.CloseHandle(thread), "CloseHandle(thread)")
        finally:
            self.check(self.api.CloseHandle(snapshot), "CloseHandle(snapshot)")

    def active_processes(self) -> int:
        info = self.Accounting()
        self.check(self.api.QueryInformationJobObject(self.handle, 1, self.c.byref(info), self.c.sizeof(info), None),
                   "QueryInformationJobObject")
        return info.ActiveProcesses

    def terminate(self) -> None:
        self.check(self.api.TerminateJobObject(self.handle, JOB_EXIT_CODE), "TerminateJobObject")

    def cancel_io(self, thread_id: int) -> None:
        thread = self.api.OpenThread(0x1, False, thread_id)  # THREAD_TERMINATE
        if not thread and self.c.get_last_error() == 87:  # thread already exited
            return
        self.check(thread, "OpenThread(cancel_io)")
        try:
            if not self.api.CancelSynchronousIo(thread) and self.c.get_last_error() != 1168:
                self.check(False, "CancelSynchronousIo")
        finally:
            self.check(self.api.CloseHandle(thread), "CloseHandle(io_thread)")

    def close(self) -> None:
        if self.handle:
            self.check(self.api.CloseHandle(self.handle), "CloseHandle(job)")
            self.handle = None


class InterruptiblePipe:
    """Raw POSIX pipes poll without blocking; Windows I/O is cancelled by TID."""

    def __init__(self, stream: Any, stop: threading.Event) -> None:
        self.stream, self.stop = stream, stop

    def _operate(self, method: str, value: Any) -> Any:
        while not self.stop.is_set():
            try:
                result = getattr(self.stream, method)(value)
            except BlockingIOError:
                result = None
            if result is not None:
                return result
            self.stop.wait(.005)
        raise OSError("Pipe capture cancelled before EOF; see cleanup diagnostics")

    def read(self, size: int) -> bytes:
        return self._operate("read", size)

    def write(self, data: bytes) -> int:
        return self._operate("write", data)
