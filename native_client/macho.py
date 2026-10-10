"""Minimal, defensive x86-64 Mach-O loader for the independent SAP runtime.

Only the parts needed by the Apple SAP images are implemented.  The parser is
purpose-built and has no dependency on Go, Rust, or the ipatool source tree.
"""

import struct
from dataclasses import dataclass

from .errors import NativeClientError


PAGE = 0x1000
U64_MASK = 0xFFFFFFFFFFFFFFFF
FAT_MAGIC = 0xCAFEBABE
MH_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_X86_64 = 0x01000007
LC_SEGMENT_64 = 0x19
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_SYMTAB = 0x2

N_TYPE = 0x0E
N_UNDF = 0x00
N_SECT = 0x0E
N_EXT = 0x01

BIND_OPCODE_MASK = 0xF0
BIND_IMMEDIATE_MASK = 0x0F
BIND_OPCODE_DONE = 0x00
BIND_OPCODE_SET_DYLIB_ORDINAL_IMM = 0x10
BIND_OPCODE_SET_DYLIB_ORDINAL_ULEB = 0x20
BIND_OPCODE_SET_DYLIB_SPECIAL_IMM = 0x30
BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM = 0x40
BIND_OPCODE_SET_TYPE_IMM = 0x50
BIND_OPCODE_SET_ADDEND_SLEB = 0x60
BIND_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB = 0x70
BIND_OPCODE_ADD_ADDR_ULEB = 0x80
BIND_OPCODE_DO_BIND = 0x90
BIND_OPCODE_DO_BIND_ADD_ADDR_ULEB = 0xA0
BIND_OPCODE_DO_BIND_ADD_ADDR_IMM_SCALED = 0xB0
BIND_OPCODE_DO_BIND_ULEB_TIMES_SKIPPING_ULEB = 0xC0

REBASE_OPCODE_MASK = 0xF0
REBASE_IMMEDIATE_MASK = 0x0F
REBASE_OPCODE_DONE = 0x00
REBASE_OPCODE_SET_TYPE_IMM = 0x10
REBASE_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB = 0x20
REBASE_OPCODE_ADD_ADDR_ULEB = 0x30
REBASE_OPCODE_ADD_ADDR_IMM_SCALED = 0x40
REBASE_OPCODE_DO_REBASE_IMM_TIMES = 0x50
REBASE_OPCODE_DO_REBASE_ULEB_TIMES = 0x60
REBASE_OPCODE_DO_REBASE_ADD_ADDR_ULEB = 0x70
REBASE_OPCODE_DO_REBASE_ULEB_TIMES_SKIPPING_ULEB = 0x80
REBASE_TYPE_POINTER = 1


class MachOError(NativeClientError):
    pass


@dataclass(frozen=True)
class Segment:
    name: str
    vmaddr: int
    vmsize: int
    fileoff: int
    filesize: int


@dataclass(frozen=True)
class Symbol:
    name: str
    value: int
    defined: bool
    external: bool


def _read_u32(data, offset, endian="<"):
    if offset < 0 or offset + 4 > len(data):
        raise MachOError("Mach-O read exceeds file")
    return struct.unpack_from(endian + "I", data, offset)[0]


def _read_u64(data, offset, endian="<"):
    if offset < 0 or offset + 8 > len(data):
        raise MachOError("Mach-O read exceeds file")
    return struct.unpack_from(endian + "Q", data, offset)[0]


def _uleb(data, offset):
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value & U64_MASK, offset
        shift += 7
        if shift > 63:
            break
    raise MachOError("invalid ULEB128 value")


def _sleb(data, offset):
    value = 0
    shift = 0
    byte = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            if shift < 64 and byte & 0x40:
                value |= -1 << shift
            return value, offset
        if shift > 63:
            break
    raise MachOError("invalid SLEB128 value")


def _cstring(data, offset):
    if offset < 0 or offset >= len(data):
        raise MachOError("Mach-O string offset is outside the file")
    end = data.find(b"\0", offset)
    if end < 0:
        raise MachOError("unterminated Mach-O string")
    return data[offset:end].decode("utf-8", "replace")


def _slice_x86_64(data):
    if len(data) < 4:
        raise MachOError("Mach-O file is truncated")
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic != FAT_MAGIC:
        return bytes(data)
    nfat = _read_u32(data, 4, ">")
    for index in range(nfat):
        offset = 8 + index * 20
        if offset + 20 > len(data):
            raise MachOError("fat architecture table is truncated")
        cputype, _cpusubtype, fileoff, size, _align = struct.unpack_from(">IIIII", data, offset)
        if cputype == CPU_TYPE_X86_64:
            end = fileoff + size
            if end < fileoff or end > len(data):
                raise MachOError("x86-64 slice exceeds Mach-O file")
            return bytes(data[fileoff:end])
    raise MachOError("universal Mach-O has no x86-64 slice")


class MachOImage:
    def __init__(self, name, raw):
        self.name = str(name)
        self.data = _slice_x86_64(raw)
        if _read_u32(self.data, 0, "<") != MH_MAGIC_64:
            raise MachOError("%s is not an x86-64 Mach-O image" % self.name)
        self._parse_header()

    def _parse_header(self):
        if len(self.data) < 32:
            raise MachOError("%s Mach-O header is truncated" % self.name)
        _magic, cputype, _subtype, _filetype, ncmds, sizeofcmds, _flags, _reserved = struct.unpack_from(
            "<IiiIIIII", self.data, 0
        )
        if cputype != CPU_TYPE_X86_64:
            raise MachOError("%s has unsupported CPU type %x" % (self.name, cputype))
        if 32 + sizeofcmds > len(self.data):
            raise MachOError("%s load commands are truncated" % self.name)
        self.segments = []
        self._symtab = None
        self._dyld = None
        offset = 32
        for _ in range(ncmds):
            cmd = _read_u32(self.data, offset, "<")
            size = _read_u32(self.data, offset + 4, "<")
            if size < 8 or offset + size > len(self.data):
                raise MachOError("%s contains an invalid load command" % self.name)
            if cmd == LC_SEGMENT_64:
                if size < 72:
                    raise MachOError("%s contains a truncated segment command" % self.name)
                raw_name = self.data[offset + 8 : offset + 24]
                name = raw_name.split(b"\0", 1)[0].decode("ascii", "replace")
                vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", self.data, offset + 24)
                if fileoff + filesize < fileoff or fileoff + filesize > len(self.data):
                    raise MachOError("%s segment exceeds the file" % self.name)
                self.segments.append(Segment(name, vmaddr, vmsize, fileoff, filesize))
            elif cmd == LC_SYMTAB:
                if size < 24:
                    raise MachOError("%s contains a truncated symbol table command" % self.name)
                self._symtab = struct.unpack_from("<IIII", self.data, offset + 8)
            elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
                if size < 48:
                    raise MachOError("%s contains a truncated dyld command" % self.name)
                self._dyld = struct.unpack_from("<IIIIIIIIII", self.data, offset + 8)
            offset += size

        loadable = [segment.vmaddr for segment in self.segments if segment.name != "__PAGEZERO" and segment.vmsize]
        if not loadable:
            raise MachOError("%s has no loadable segments" % self.name)
        self.image_base = min(loadable)

    @property
    def span(self):
        end = max(
            segment.vmaddr + segment.vmsize
            for segment in self.segments
            if segment.name != "__PAGEZERO" and segment.vmsize
        )
        return _align(end - self.image_base, PAGE)

    def _symbols(self):
        if self._symtab is None:
            return []
        symoff, nsyms, stroff, strsize = self._symtab
        if stroff + strsize > len(self.data) or symoff + nsyms * 16 > len(self.data):
            raise MachOError("%s symbol table exceeds the file" % self.name)
        output = []
        for index in range(nsyms):
            offset = symoff + index * 16
            strx, n_type, _sect, _desc, value = struct.unpack_from("<IBBHQ", self.data, offset)
            if strx >= strsize:
                continue
            name = _cstring(self.data, stroff + strx)
            output.append(
                Symbol(
                    name=name,
                    value=value,
                    defined=(n_type & N_TYPE) == N_SECT,
                    external=bool(n_type & N_EXT),
                )
            )
        return output

    @property
    def exports(self):
        return {
            item.name: item.value
            for item in self._symbols()
            if item.defined and item.external and item.value >= self.image_base
        }

    @property
    def imports(self):
        return sorted(
            {
                item.name
                for item in self._symbols()
                if not item.defined and item.external and item.name
            }
        )

    def export_address(self, name, load_base):
        try:
            value = self.exports[name]
        except KeyError as exc:
            raise MachOError("%s export %s is not present" % (self.name, name)) from exc
        return load_base + (value - self.image_base)

    def _segment_address(self, index, segment_offset, load_base, size=8):
        try:
            segment = self.segments[index]
        except IndexError as exc:
            raise MachOError("%s fixup references invalid segment" % self.name) from exc
        if segment_offset < 0 or segment_offset + size > segment.vmsize:
            raise MachOError(
                "%s fixup exceeds segment %s at offset %#x (segment size %#x)"
                % (self.name, segment.name, segment_offset, segment.vmsize)
            )
        return load_base + segment.vmaddr - self.image_base + segment_offset

    @staticmethod
    def _write_pointer(engine, address, value):
        engine.mem_write(address, struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF))

    def _apply_rebases(self, engine, load_base):
        if not self._dyld:
            return
        rebase_off, rebase_size = self._dyld[0], self._dyld[1]
        if not rebase_size:
            return
        stream = self.data[rebase_off : rebase_off + rebase_size]
        if len(stream) != rebase_size:
            raise MachOError("%s rebase stream exceeds the file" % self.name)
        segment_index = 0
        segment_offset = 0
        rebase_type = REBASE_TYPE_POINTER
        position = 0

        def rebase_one():
            nonlocal segment_offset
            address = self._segment_address(segment_index, segment_offset, load_base)
            old = struct.unpack("<Q", engine.mem_read(address, 8))[0]
            engine.mem_write(address, struct.pack("<Q", load_base + old - self.image_base))
            segment_offset = (segment_offset + 8) & U64_MASK

        while position < len(stream):
            opcode = stream[position]
            position += 1
            kind = opcode & REBASE_OPCODE_MASK
            immediate = opcode & REBASE_IMMEDIATE_MASK
            if kind == REBASE_OPCODE_DONE:
                break
            if rebase_type != REBASE_TYPE_POINTER and kind not in (
                REBASE_OPCODE_SET_TYPE_IMM,
                REBASE_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB,
            ):
                raise MachOError("%s uses unsupported rebase type" % self.name)
            if kind == REBASE_OPCODE_SET_TYPE_IMM:
                rebase_type = immediate
            elif kind == REBASE_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB:
                segment_index = immediate
                segment_offset, position = _uleb(stream, position)
            elif kind == REBASE_OPCODE_ADD_ADDR_ULEB:
                value, position = _uleb(stream, position)
                segment_offset = (segment_offset + value) & U64_MASK
            elif kind == REBASE_OPCODE_ADD_ADDR_IMM_SCALED:
                segment_offset = (segment_offset + immediate * 8) & U64_MASK
            elif kind == REBASE_OPCODE_DO_REBASE_IMM_TIMES:
                for _ in range(immediate):
                    rebase_one()
            elif kind == REBASE_OPCODE_DO_REBASE_ULEB_TIMES:
                count, position = _uleb(stream, position)
                for _ in range(count):
                    rebase_one()
            elif kind == REBASE_OPCODE_DO_REBASE_ADD_ADDR_ULEB:
                rebase_one()
                value, position = _uleb(stream, position)
                segment_offset = (segment_offset + value) & U64_MASK
            elif kind == REBASE_OPCODE_DO_REBASE_ULEB_TIMES_SKIPPING_ULEB:
                count, position = _uleb(stream, position)
                skip, position = _uleb(stream, position)
                for _ in range(count):
                    rebase_one()
                    segment_offset = (segment_offset + skip) & U64_MASK
            else:
                raise MachOError("%s uses unsupported rebase opcode %#x" % (self.name, kind))

    def _apply_binds(self, engine, load_base, resolver):
        if not self._dyld:
            return
        self._apply_bind_stream(engine, load_base, resolver, self._dyld[2], self._dyld[3])

    def _apply_lazy_binds(self, engine, load_base, resolver):
        if not self._dyld:
            return
        self._apply_bind_stream(engine, load_base, resolver, self._dyld[6], self._dyld[7], lazy=True)

    def _apply_bind_stream(self, engine, load_base, resolver, bind_off, bind_size, lazy=False):
        if not bind_size:
            return
        stream = self.data[bind_off : bind_off + bind_size]
        if len(stream) != bind_size:
            raise MachOError("%s bind stream exceeds the file" % self.name)
        segment_index = 0
        segment_offset = 0
        bind_type = 1
        addend = 0
        symbol = None
        position = 0

        def bind_one():
            nonlocal segment_offset
            if bind_type != 1:
                raise MachOError("%s uses unsupported bind type %d" % (self.name, bind_type))
            if symbol is None:
                raise MachOError("%s bind has no symbol" % self.name)
            try:
                address = self._segment_address(segment_index, segment_offset, load_base)
            except MachOError as exc:
                raise MachOError(
                    "%s while binding %s (segment index %d, offset %#x)"
                    % (exc, symbol, segment_index, segment_offset)
                ) from exc
            target = resolver(symbol) + addend
            self._write_pointer(engine, address, target)
            segment_offset = (segment_offset + 8) & U64_MASK

        while position < len(stream):
            opcode = stream[position]
            position += 1
            kind = opcode & BIND_OPCODE_MASK
            immediate = opcode & BIND_IMMEDIATE_MASK
            if kind == BIND_OPCODE_DONE:
                if not lazy:
                    break
                # Lazy-bind information is a concatenation of independent
                # entries. DONE terminates one entry, not the whole stream.
                segment_index = 0
                segment_offset = 0
                bind_type = 1
                addend = 0
                symbol = None
                continue
            if kind == BIND_OPCODE_SET_DYLIB_ORDINAL_IMM:
                continue
            if kind == BIND_OPCODE_SET_DYLIB_ORDINAL_ULEB:
                _unused, position = _uleb(stream, position)
            elif kind == BIND_OPCODE_SET_DYLIB_SPECIAL_IMM:
                continue
            elif kind == BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM:
                end = stream.find(b"\0", position)
                if end < 0:
                    raise MachOError("%s bind symbol is unterminated" % self.name)
                symbol = stream[position:end].decode("utf-8", "replace")
                position = end + 1
            elif kind == BIND_OPCODE_SET_TYPE_IMM:
                bind_type = immediate
            elif kind == BIND_OPCODE_SET_ADDEND_SLEB:
                addend, position = _sleb(stream, position)
            elif kind == BIND_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB:
                segment_index = immediate
                segment_offset, position = _uleb(stream, position)
            elif kind == BIND_OPCODE_ADD_ADDR_ULEB:
                value, position = _uleb(stream, position)
                segment_offset = (segment_offset + value) & U64_MASK
            elif kind == BIND_OPCODE_DO_BIND:
                bind_one()
            elif kind == BIND_OPCODE_DO_BIND_ADD_ADDR_ULEB:
                bind_one()
                value, position = _uleb(stream, position)
                segment_offset = (segment_offset + value) & U64_MASK
            elif kind == BIND_OPCODE_DO_BIND_ADD_ADDR_IMM_SCALED:
                bind_one()
                segment_offset = (segment_offset + immediate * 8) & U64_MASK
            elif kind == BIND_OPCODE_DO_BIND_ULEB_TIMES_SKIPPING_ULEB:
                count, position = _uleb(stream, position)
                skip, position = _uleb(stream, position)
                for _ in range(count):
                    bind_one()
                    segment_offset = (segment_offset + skip) & U64_MASK
            else:
                raise MachOError("%s uses unsupported bind opcode %#x" % (self.name, kind))

    def load(self, engine, load_base, resolver=lambda _name: 0):
        """Map segments, apply pointer rebases/binds, and copy image bytes."""
        engine.mem_map(load_base, self.span)
        for segment in self.segments:
            if segment.name == "__PAGEZERO" or not segment.vmsize:
                continue
            address = load_base + segment.vmaddr - self.image_base
            if segment.filesize:
                engine.mem_write(address, self.data[segment.fileoff : segment.fileoff + segment.filesize])
        self._apply_rebases(engine, load_base)
        self._apply_binds(engine, load_base, resolver)
        self._apply_lazy_binds(engine, load_base, resolver)


def _align(value, alignment):
    return (value + alignment - 1) & ~(alignment - 1)
