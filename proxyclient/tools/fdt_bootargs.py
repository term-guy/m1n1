"""Read /chosen/bootargs from an FDT without dumping private DT properties."""
import struct


def bootargs_from_fdt(blob):
    magic, size, off_struct, off_strings = struct.unpack_from(">4I", blob)
    if magic != 0xd00dfeed or not 40 <= size <= len(blob):
        raise ValueError("Invalid FDT header/size")
    cursor = off_struct
    path = []
    while cursor < size:
        token, = struct.unpack_from(">I", blob, cursor)
        cursor += 4
        if token == 1:  # FDT_BEGIN_NODE
            end = blob.index(b"\0", cursor, size)
            path.append(blob[cursor:end].decode("ascii"))
            cursor = (end + 4) & ~3
        elif token == 2:  # FDT_END_NODE
            path.pop()
        elif token == 3:  # FDT_PROP
            length, nameoff = struct.unpack_from(">2I", blob, cursor)
            cursor += 8
            name_start = off_strings + nameoff
            name_end = blob.index(b"\0", name_start, size)
            if path == ["", "chosen"] and blob[name_start:name_end] == b"bootargs":
                value = blob[cursor:cursor+length]
                if not value.endswith(b"\0") or b"\0" in value[:-1]:
                    raise ValueError("FDT bootargs is not one NUL-terminated string")
                return value[:-1].decode("ascii")
            cursor = (cursor + length + 3) & ~3
        elif token == 4:  # FDT_NOP
            pass
        elif token == 9:  # FDT_END
            break
        else:
            raise ValueError(f"Unknown FDT token {token}")
    raise ValueError("FDT /chosen/bootargs missing")


def reservations_from_fdt(blob):
    """Return (memreserve [(addr, size)], [(name, [(addr, size)], nomap)]) for
    /reserved-memory children. Only addresses/names, no private properties."""
    magic, size, off_struct, off_strings, off_rsv = struct.unpack_from(">5I", blob)
    if magic != 0xd00dfeed or not 40 <= size <= len(blob):
        raise ValueError("Invalid FDT header/size")
    rsv = []
    cur = off_rsv
    while True:
        addr, length = struct.unpack_from(">2Q", blob, cur)
        cur += 16
        if not addr and not length:
            break
        rsv.append((addr, length))
    nodes, path, node = [], [], None
    cursor = off_struct
    while cursor < size:
        token, = struct.unpack_from(">I", blob, cursor)
        cursor += 4
        if token == 1:
            end = blob.index(b"\0", cursor, size)
            path.append(blob[cursor:end].decode("ascii"))
            cursor = (end + 4) & ~3
            if len(path) == 3 and path[1] == "reserved-memory":
                node = [path[2], [], False]
                nodes.append(node)
        elif token == 2:
            path.pop()
            node = None if len(path) < 3 else node
        elif token == 3:
            length, nameoff = struct.unpack_from(">2I", blob, cursor)
            cursor += 8
            name_start = off_strings + nameoff
            name = blob[name_start:blob.index(b"\0", name_start, size)]
            if node is not None and len(path) == 3:
                if name == b"reg":
                    vals = struct.unpack_from(">%dQ" % (length // 8), blob, cursor)
                    node[1] = list(zip(vals[0::2], vals[1::2]))
                elif name == b"no-map":
                    node[2] = True
            cursor = (cursor + length + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            break
        else:
            raise ValueError(f"Unknown FDT token {token}")
    return rsv, [tuple(n) for n in nodes]
