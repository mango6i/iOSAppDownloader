"""Windows-hosted Apple SAP guest runtime.

This is the independent runtime counterpart to :mod:`native_client.macho`.
It loads the Apple-supplied x86-64 framework images into Unicorn and exposes
only narrowly scoped host shims required by the SAP state machine.  No
external command or browser is started.
"""

import ctypes
import os
import struct
import time
from pathlib import Path

from .errors import NativeClientError
from .macho import MachOImage

try:
    from unicorn import (
        UC_ARCH_X86,
        UC_HOOK_CODE,
        UC_MODE_64,
        Uc,
        x86_const,
    )
except ImportError as exc:  # pragma: no cover - exercised only without native dependency
    raise ImportError("install requirements-native.txt to enable the SAP runtime") from exc


RETURN_ADDRESS = 0x0000000100000000
CORE_FP_BASE = 0x0000100000000000
COMMERCE_CORE_BASE = 0x0000100040000000
COMMERCE_KIT_BASE = 0x0000100080000000
SHIM_BASE = 0x0000200000000000
SHIM_CODE_SIZE = 0x80000
SHIM_SIZE = 0x100000
SCRATCH_BASE = 0x0000300000000000
SCRATCH_SIZE = 32 << 20
HEAP_BASE = 0x0000400000000000
HEAP_SIZE = 64 << 20
STACK_BASE = 0x0000500000000000
STACK_SIZE = 8 << 20
STACK_END = STACK_BASE + STACK_SIZE
PAGE = 0x1000
FAKE_HANDLE = 0xFFFFFFFFFFFFFFFF

CORE_EXPORT_NAMES = (
    "_WIn9UJ86JKdV4dM",
    "_X46O5IeS",
    "_YlCJ3lg",
    "_dku592fbFAj",
    "_fdjkDSAFjklaf2s",
    "_lxpgvVMLd0S7uRl",
)


def _reg(name):
    return getattr(x86_const, "UC_X86_REG_" + name)


class GuestMemory:
    def __init__(self, engine):
        self.engine = engine
        self.cursor = 0
        self.heap_cursor = 0
        self.allocations = {}
        self.free_blocks = []

    def begin(self):
        self.cursor = 0

    def scratch(self, data=b"", size=None):
        payload = bytes(data)
        size = len(payload) if size is None else int(size)
        reserved = _align(max(size, 1), 16)
        if reserved > SCRATCH_SIZE - self.cursor:
            raise NativeClientError("SAP scratch space exhausted")
        address = SCRATCH_BASE + self.cursor
        self.cursor += reserved
        self.engine.mem_write(address, payload + b"\0" * max(0, size - len(payload)))
        return address

    def clear_scratch(self):
        if self.cursor:
            self.engine.mem_write(SCRATCH_BASE, b"\0" * self.cursor)
        self.cursor = 0

    def alloc(self, size):
        size = int(size)
        reserved = _align(max(size, 1), 16)
        for index, (address, available) in enumerate(self.free_blocks):
            if available < reserved:
                continue
            if available == reserved:
                self.free_blocks.pop(index)
            else:
                self.free_blocks[index] = (address + reserved, available - reserved)
            self.allocations[address] = (size, reserved)
            return address
        if reserved > HEAP_SIZE - self.heap_cursor:
            raise NativeClientError("SAP guest heap exhausted")
        address = HEAP_BASE + self.heap_cursor
        self.heap_cursor += reserved
        self.allocations[address] = (size, reserved)
        self.engine.mem_write(address, b"\0" * reserved)
        return address

    def free(self, address):
        if not address:
            return
        record = self.allocations.pop(address, None)
        if record is None:
            raise NativeClientError("guest attempted to free an unknown pointer")
        _size, reserved = record
        self.engine.mem_write(address, b"\0" * reserved)
        self.free_blocks.append((address, reserved))
        self.free_blocks.sort()
        merged = []
        for block in self.free_blocks:
            if merged and merged[-1][0] + merged[-1][1] == block[0]:
                merged[-1] = (merged[-1][0], merged[-1][1] + block[1])
            else:
                merged.append(block)
        self.free_blocks = merged

    def read_u32(self, address):
        return struct.unpack("<I", bytes(self.engine.mem_read(address, 4)))[0]

    def write_u32(self, address, value):
        self.engine.mem_write(address, struct.pack("<I", int(value) & 0xFFFFFFFF))

    def read_u64(self, address):
        return struct.unpack("<Q", bytes(self.engine.mem_read(address, 8)))[0]

    def write_u64(self, address, value):
        self.engine.mem_write(address, struct.pack("<Q", int(value) & 0xFFFFFFFFFFFFFFFF))

    def c_string(self, address, maximum=4096):
        value = bytearray()
        for offset in range(maximum):
            item = bytes(self.engine.mem_read(address + offset, 1))
            if item == b"\0":
                return value.decode("utf-8", "replace")
            value.extend(item)
        raise NativeClientError("guest string exceeds %d bytes" % maximum)


class HostShims:
    def __init__(self, engine, memory, core_exports, icxs):
        self.engine = engine
        self.memory = memory
        # Keep the caller's export table live. CoreFP is loaded first and
        # publishes exports while the guest is being assembled; later dlsym
        # calls must see those newly published addresses.
        self.core_exports = core_exports
        self.icxs = bytes(icxs)
        self.icxs_offset = 0
        self.iterator = 0
        self.errno_address = SHIM_BASE + SHIM_CODE_SIZE
        self.entries = {}
        self.symbols = {}
        self.cursor = SHIM_BASE
        self.data_cursor = SHIM_BASE + SHIM_CODE_SIZE
        self.closed = False
        self.fault = None
        self.engine.mem_map(SHIM_BASE, SHIM_SIZE)
        self.memory.write_u64(self.errno_address, 0)
        self._register()
        self._hook = self.engine.hook_add(
            UC_HOOK_CODE,
            self._dispatch,
            begin=SHIM_BASE,
            end=SHIM_BASE + SHIM_CODE_SIZE - 1,
        )

    def _add(self, name, handler):
        if name in self.symbols:
            return self.symbols[name]
        if self.cursor + 16 > SHIM_BASE + SHIM_CODE_SIZE:
            raise NativeClientError("SAP host shim area is full")
        address = self.cursor
        self.cursor += 16
        self.engine.mem_write(address, b"\xC3")
        self.symbols[name] = address
        self.entries[address] = (name, handler)
        return address

    def _add_data(self, name, value):
        if name in self.symbols:
            return self.symbols[name]
        address = _align(self.data_cursor, 8)
        if address + len(value) > SHIM_BASE + SHIM_SIZE:
            raise NativeClientError("SAP host shim data area is full")
        self.data_cursor = address + max(len(value), 8)
        self.engine.mem_write(address, bytes(value))
        self.symbols[name] = address
        return address

    def resolve(self, name):
        # Unknown platform calls get a safe zero-return stub.  The dispatcher
        # records the symbol so a later implementation can promote it to a
        # typed shim without changing the Mach-O loader.
        return self._add(name, self._return_zero)

    def _register(self):
        zero = (
            "_CFBundleGetMainBundle", "_CFDataGetBytePtr", "_CFDataGetLength",
            "_CFStringGetLength", "_CFStringGetMaximumSizeForEncoding", "_CFUUIDCreateString",
            "_IORegistryEntryFromPath", "_IORegistryEntrySearchCFProperty", "_IOServiceMatching",
            "_getenv", "_pthread_self", "_CFRelease", "_IOObjectRelease", "_close",
            "_close$UNIX2003", "_pthread_mutex_lock", "_pthread_mutex_unlock",
            "_pthread_rwlock_init", "_pthread_rwlock_init$UNIX2003", "_pthread_rwlock_unlock",
            "_pthread_rwlock_unlock$UNIX2003", "_pthread_rwlock_wrlock",
            "_pthread_rwlock_wrlock$UNIX2003", "_CFStringCreateWithCStringNoCopy",
            "_fcntl", "_fcntl$UNIX2003", "_lstat$INODE64", "_statfs", "_statfs$INODE64",
            "_sysctl", "_sysctlbyname",
        )
        for name in zero:
            self._add(name, self._return_zero)
        for name in ("_CFDictionaryGetValue", "_DADiskCopyDescription", "_DADiskCreateFromBSDName", "_DASessionCreate", "_IORegistryEntryCreateCFProperty"):
            self._add(name, self._return_fake)
        for name in ("_abort", "___stack_chk_fail", "dyld_stub_binder"):
            self._add(name, self._abort)
        typed = {
            "_arc4random": self._arc4random,
            "_gettimeofday": self._gettimeofday,
            "_objc_msgSend": self._objc_msg_send,
            "_CFStringCreateWithCString": self._cf_string_create_with_cstring,
            "_CFStringGetCString": self._cf_string_get_cstring,
            "_IOIteratorNext": self._io_iterator_next,
            "_IORegistryEntryGetParentEntry": self._io_registry_entry_get_parent_entry,
            "_IOServiceGetMatchingServices": self._io_service_get_matching_services,
            "_IOServiceGetMatchingService": self._io_service_get_matching_service,
            "_OSAtomicCompareAndSwap32Barrier": self._os_atomic_compare_and_swap32_barrier,
            "___error": self._error,
            "_dlopen": self._dlopen,
            "_dlsym": self._dlsym,
            "_open": self._open,
            "_open$UNIX2003": self._open,
            "_pthread_once": self._pthread_once,
            "_read": self._read,
            "_read$UNIX2003": self._read,
        }
        for name, handler in typed.items():
            self._add(name, handler)
        for name, handler in (
            ("_malloc", self._malloc), ("_malloc_good_size", self._malloc_good_size),
            ("_malloc_size", self._malloc_size), ("_calloc", self._calloc),
            ("_realloc", self._realloc), ("_reallocf", self._realloc), ("_free", self._free),
            ("_memcpy", self._memmove), ("_memmove", self._memmove), ("_memset", self._memset),
            ("___bzero", self._bzero), ("___memcpy_chk", self._checked_memcpy),
            ("___memset_chk", self._checked_memset), ("_memcmp", self._memcmp),
            ("_strcmp", self._strcmp), ("_strncmp", self._strncmp), ("_strlen", self._strlen),
        ):
            self._add(name, handler)
        self._add_data("___stack_chk_guard", b"\xA5\x71\x3C\xD9\x86\x42\xEF\x10")
        self._add_data("_kCFAllocatorDefault", b"\0" * 8)
        self._add_data("_kCFAllocatorNull", b"\0" * 8)
        self._add_data("_kDADiskDescriptionVolumeUUIDKey", b"\0" * 8)
        self._add_data("_kIOMasterPortDefault", b"\0" * 8)

    def _args(self):
        names = ("RDI", "RSI", "RDX", "RCX", "R8", "R9")
        return [self.engine.reg_read(_reg(name)) for name in names]

    def _set_result(self, value):
        self.engine.reg_write(_reg("RAX"), int(value) & 0xFFFFFFFFFFFFFFFF)

    def _dispatch(self, _engine, address, _size, _user_data=None):
        entry = self.entries.get(address)
        if not entry:
            self.fault = NativeClientError("guest entered unknown shim %#x" % address)
            self.engine.emu_stop()
            return
        name, handler = entry
        try:
            handler()
        except Exception as exc:
            self.fault = NativeClientError("%s: %s" % (name, exc))
            self.engine.emu_stop()

    def _return_zero(self):
        self._set_result(0)

    def _return_fake(self):
        self._set_result(FAKE_HANDLE)

    def _return_minus_one(self):
        self._set_result(FAKE_HANDLE)

    def _abort(self):
        raise NativeClientError("guest called abort")

    def _malloc(self):
        self._set_result(self.memory.alloc(self._args()[0]))

    def _malloc_good_size(self):
        self._set_result(_align(max(self._args()[0], 1), 16))

    def _malloc_size(self):
        record = self.memory.allocations.get(self._args()[0])
        self._set_result(record[1] if record else 0)

    def _calloc(self):
        args = self._args()
        total = args[0] * args[1]
        self._set_result(self.memory.alloc(total))

    def _realloc(self):
        old, size = self._args()[:2]
        if not old:
            self._set_result(self.memory.alloc(size))
            return
        old_size, _reserved = self.memory.allocations.get(old, (0, 0))
        address = self.memory.alloc(size)
        self.engine.mem_write(address, self.engine.mem_read(old, min(old_size, size)))
        self.memory.free(old)
        self._set_result(address)

    def _free(self):
        address = self._args()[0]
        if address:
            self.memory.free(address)
        self._set_result(0)

    def _memmove(self):
        dst, src, length = self._args()[:3]
        self.engine.mem_write(dst, bytes(self.engine.mem_read(src, length)))
        self._set_result(dst)

    def _memset(self):
        dst, value, length = self._args()[:3]
        self.engine.mem_write(dst, bytes([value & 0xFF]) * length)
        self._set_result(dst)

    def _bzero(self):
        dst, length = self._args()[:2]
        self.engine.mem_write(dst, b"\0" * length)
        self._set_result(dst)

    def _checked_memcpy(self):
        args = self._args()
        if args[2] > args[3]:
            raise NativeClientError("checked memcpy exceeded destination")
        self._memmove()

    def _checked_memset(self):
        args = self._args()
        if args[2] > args[3]:
            raise NativeClientError("checked memset exceeded destination")
        self._memset()

    def _memcmp(self):
        left, right, length = self._args()[:3]
        a = bytes(self.engine.mem_read(left, length))
        b = bytes(self.engine.mem_read(right, length))
        self._set_result((a > b) - (a < b))

    def _strcmp(self):
        a, b = self._args()[:2]
        left = self.memory.c_string(a).encode()
        right = self.memory.c_string(b).encode()
        self._set_result((left > right) - (left < right))

    def _strncmp(self):
        a, b, length = self._args()[:3]
        left = self.memory.c_string(a).encode()[:length]
        right = self.memory.c_string(b).encode()[:length]
        self._set_result((left > right) - (left < right))

    def _strlen(self):
        self._set_result(len(self.memory.c_string(self._args()[0]).encode()))

    def _arc4random(self):
        self._set_result(int.from_bytes(os.urandom(4), "little"))

    def _gettimeofday(self):
        time_address, zone_address = self._args()[:2]
        now = time.time()
        if time_address:
            self.memory.write_u64(time_address, int(now))
            self.memory.write_u64(time_address + 8, int((now % 1) * 1_000_000))
        if zone_address:
            self.memory.write_u64(zone_address, 0)
        self._set_result(0)

    def _cf_string_create_with_cstring(self):
        args = self._args()
        value = self.memory.c_string(args[1])
        self._set_result(FAKE_HANDLE if value in ("IOPlatformSerialNumber", "IOPlatformUUID", "board-id") else 0)

    def _cf_string_get_cstring(self):
        args = self._args()
        if args[1] and args[2]:
            self.engine.mem_write(args[1], b"\0")
            self._set_result(1)
        else:
            self._set_result(0)

    def _io_iterator_next(self):
        self.iterator += 1
        self._set_result(self.iterator % 2)

    def _io_registry_entry_get_parent_entry(self):
        output = self._args()[2]
        self.memory.write_u32(output, 0xFFFFFFFF)
        self._set_result(0)

    def _io_service_get_matching_services(self):
        output = self._args()[2]
        self.iterator = 0
        self.memory.write_u32(output, 0xFFFFFFFF)
        self._set_result(0)

    def _io_service_get_matching_service(self):
        self._set_result(0xFFFFFFFF)

    def _os_atomic_compare_and_swap32_barrier(self):
        old, new, address = self._args()[:3]
        current = self.memory.read_u32(address)
        if current != old:
            self._set_result(0)
            return
        self.memory.write_u32(address, new)
        self._set_result(1)

    def _error(self):
        self._set_result(self.errno_address)

    def _dlopen(self):
        path = self.memory.c_string(self._args()[0])
        self._set_result(FAKE_HANDLE if path.endswith("CoreFP.framework/CoreFP") else 0)

    def _dlsym(self):
        name = self.memory.c_string(self._args()[1])
        self._set_result(self.core_exports.get("_" + name, 0))

    def _open(self):
        path = self.memory.c_string(self._args()[0])
        if path.endswith("CoreFP.icxs"):
            self.icxs_offset = 0
            self._set_result(3)
        else:
            self._set_result(FAKE_HANDLE)

    def _pthread_once(self):
        control, initializer = self._args()[:2]
        if self.memory.read_u64(control) == 0:
            self._set_result(0)
            return
        self.memory.write_u64(control, 0)
        stack = self.engine.reg_read(_reg("RSP")) - 8
        self.memory.write_u64(stack, initializer)
        self.engine.reg_write(_reg("RSP"), stack)
        self._set_result(0)

    def _read(self):
        descriptor, address, requested = self._args()[:3]
        if descriptor != 3:
            self._set_result(FAKE_HANDLE)
            return
        amount = min(requested, len(self.icxs) - self.icxs_offset)
        if amount:
            self.engine.mem_write(address, self.icxs[self.icxs_offset : self.icxs_offset + amount])
            self.icxs_offset += amount
        self._set_result(amount)

    def _objc_msg_send(self):
        selector = self.memory.c_string(self._args()[1])
        self._set_result(FAKE_HANDLE if selector == "objectForKey:" else 0)

    def close(self):
        if not self.closed:
            self.closed = True
            if self._hook:
                close = getattr(self._hook, "close", None)
                if close is not None:
                    close()
                else:
                    self.engine.hook_del(self._hook)


class SapGuest:
    """Run CoreFP + CommerceKit SAP calls using the local guest machine."""

    def __init__(self, asset_dir):
        self.asset_dir = Path(asset_dir)
        self.engine = Uc(UC_ARCH_X86, UC_MODE_64)
        self._map_base_regions()
        self.memory = GuestMemory(self.engine)
        self.images = {}
        self.exports = {}
        self.shims = None
        self._load_images()
        self.entry = {
            key: self.images["CommerceKit"].export_address(symbol, COMMERCE_KIT_BASE)
            for key, symbol in {
                "initialize": "_cp2g1b9ro",
                "exchange": "_Mib5yocT",
                "sign": "_Fc3vhtJDvr",
                "teardown": "_IPaI1oem5iL",
                "dispose": "_jEHf8Xzsv8K",
            }.items()
        }

    def _map_base_regions(self):
        for address, size in (
            (RETURN_ADDRESS, PAGE),
            (SCRATCH_BASE, SCRATCH_SIZE),
            (HEAP_BASE, HEAP_SIZE),
            (STACK_BASE, STACK_SIZE),
        ):
            self.engine.mem_map(address, size)
        self.engine.mem_write(RETURN_ADDRESS, b"\xF4")

    def _load_images(self):
        files = {
            "CoreFP": (CORE_FP_BASE, "CoreFP"),
            "CommerceCore": (COMMERCE_CORE_BASE, "CommerceCore"),
            "CommerceKit": (COMMERCE_KIT_BASE, "CommerceKit"),
        }
        for key, (_base, filename) in files.items():
            path = self.asset_dir / filename
            if not path.is_file():
                raise NativeClientError("missing SAP asset %s" % path)
            self.images[key] = MachOImage(key, path.read_bytes())
        self.shims = HostShims(
            self.engine,
            self.memory,
            self.exports,
            (self.asset_dir / "CoreFP.icxs").read_bytes(),
        )
        for key, (base, _filename) in files.items():
            image = self.images[key]
            for symbol in image.exports:
                self.exports[symbol] = image.export_address(symbol, base)
            image.load(self.engine, base, self._resolve)

    def _resolve(self, name):
        if name in self.exports:
            return self.exports[name]
        return self.shims.resolve(name)

    def _invoke(self, address, args):
        if not address:
            raise NativeClientError("SAP entry point is unavailable")
        for register, value in zip(("RDI", "RSI", "RDX", "RCX", "R8", "R9"), args):
            self.engine.reg_write(_reg(register), int(value) & 0xFFFFFFFFFFFFFFFF)
        extra = list(args[6:])
        stack = STACK_END - (len(extra) + 1) * 8
        if stack % 16 != 8:
            stack -= 8
        self.memory.write_u64(stack, RETURN_ADDRESS)
        for index, value in enumerate(extra):
            self.memory.write_u64(stack + 8 + index * 8, value)
        self.engine.reg_write(_reg("RSP"), stack)
        self.shims.fault = None
        try:
            self.engine.emu_start(address, RETURN_ADDRESS, timeout=60 * 1_000_000)
        except Exception as exc:
            if self.shims.fault:
                raise self.shims.fault from exc
            rip = self.engine.reg_read(_reg("RIP"))
            rsp = self.engine.reg_read(_reg("RSP"))
            raise NativeClientError(
                "SAP guest execution failed at RIP=%#x RSP=%#x: %s" % (rip, rsp, exc)
            ) from exc
        if self.shims.fault:
            raise self.shims.fault
        return self.engine.reg_read(_reg("RAX"))

    def initialize(self, hardware_id):
        self.memory.begin()
        context_field = self.memory.scratch(b"\0" * 8, 8)
        hardware = struct.pack("<I", len(hardware_id)) + bytes(hardware_id).ljust(20, b"\0")
        hardware_address = self.memory.scratch(hardware)
        try:
            status = self._invoke(self.entry["initialize"], [context_field, hardware_address])
            if status & 0xFFFFFFFF:
                raise NativeClientError("SAP initialization returned %d" % status)
            context = self.memory.read_u64(context_field)
            if not context:
                raise NativeClientError("SAP initialization returned a null context")
            return context
        finally:
            self.memory.clear_scratch()

    def exchange(self, version, hardware_id, context, incoming):
        self.memory.begin()
        hardware = struct.pack("<I", len(hardware_id)) + bytes(hardware_id).ljust(20, b"\0")
        hardware_address = self.memory.scratch(hardware)
        input_address = self.memory.scratch(incoming)
        output_field = self.memory.scratch(b"\0" * 8, 8)
        length_field = self.memory.scratch(b"\0" * 8, 8)
        result_field = self.memory.scratch(b"\0" * 4, 4)
        try:
            status = self._invoke(
                self.entry["exchange"],
                [version, hardware_address, context, input_address, len(incoming), output_field, length_field, result_field],
            )
            if status & 0xFFFFFFFF:
                raise NativeClientError("SAP exchange returned %d" % status)
            pointer = self.memory.read_u64(output_field)
            length = self.memory.read_u64(length_field)
            output = bytes(self.engine.mem_read(pointer, length)) if pointer and length else b""
            if pointer:
                self._invoke(self.entry["dispose"], [pointer])
            return output, struct.unpack("<i", struct.pack("<I", self.memory.read_u32(result_field)))[0]
        finally:
            self.memory.clear_scratch()

    def sign(self, context, body):
        self.memory.begin()
        input_address = self.memory.scratch(body)
        output_field = self.memory.scratch(b"\0" * 8, 8)
        length_field = self.memory.scratch(b"\0" * 8, 8)
        try:
            status = self._invoke(
                self.entry["sign"],
                [context, input_address, len(body), output_field, length_field],
            )
            if status & 0xFFFFFFFF:
                raise NativeClientError("SAP signing returned %d" % status)
            pointer = self.memory.read_u64(output_field)
            length = self.memory.read_u64(length_field)
            output = bytes(self.engine.mem_read(pointer, length)) if pointer and length else b""
            if pointer:
                self._invoke(self.entry["dispose"], [pointer])
            return output
        finally:
            self.memory.clear_scratch()

    def teardown(self, context):
        self._invoke(self.entry["teardown"], [context])

    def close(self):
        if self.shims:
            self.shims.close()
        close = getattr(self.engine, "close", None)
        if close is not None:
            close()


def _align(value, alignment):
    return (int(value) + alignment - 1) & ~(alignment - 1)
