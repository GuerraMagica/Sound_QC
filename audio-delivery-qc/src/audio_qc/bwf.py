"""Read RIFF/RF64/BW64 chunks by seeking; never read the entire data chunk."""
from pathlib import Path
import struct


def _text(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", errors="replace").rstrip()


def inspect_bwf(path: Path) -> dict:
    result = {"supported_container": False, "present": None, "time_reference": None,
              "originator": None, "origination_date": None, "origination_time": None,
              "coding_history": None, "warnings": [], "errors": []}
    with path.open("rb") as f:
        total = path.stat().st_size
        head = f.read(12)
        if len(head) < 12 or head[:4] not in (b"RIFF", b"RF64", b"BW64") or head[8:] != b"WAVE":
            return result
        result.update(supported_container=True, present=False, container=head[:4].decode())
        declared = struct.unpack_from("<I", head, 4)[0]
        rf64 = head[:4] in (b"RF64", b"BW64")
        if not rf64 and declared + 8 > total:
            result["errors"].append("RIFF size extends beyond end of file (truncated container)")
        if not rf64 and declared + 8 < total:
            result["warnings"].append("Bytes exist after the declared RIFF container")
        end = total if rf64 else min(total, declared + 8)
        data64 = None
        size_table = {}
        data_seen = False
        for _ in range(100000):
            pos = f.tell()
            if pos >= end:
                break
            h = f.read(8)
            if len(h) != 8 or pos + 8 > end:
                result["errors"].append("Incomplete RIFF chunk header")
                break
            chunk, size = struct.unpack("<4sI", h)
            if size == 0xFFFFFFFF:
                size = data64 if chunk == b"data" and not data_seen else (size_table.get(chunk) or [None]).pop(0)
                if size is None:
                    result["errors"].append("RF64 chunk has no ds64 size")
                    break
            start = f.tell()
            if start + size > end:
                result["errors"].append(f"{chunk!r} chunk extends beyond end of container")
                break
            if chunk == b"ds64":
                raw = f.read(min(size, 28 + 12 * 4096))
                if len(raw) < 28:
                    result["errors"].append("Truncated ds64 chunk")
                else:
                    riff64, data64, frames, table_len = struct.unpack_from("<QQQI", raw)
                    result["ds64_sample_count"] = frames
                    if riff64 + 8 > total:
                        result["errors"].append("RF64 size extends beyond end of file")
                    if table_len > 4096 or 28 + table_len * 12 > len(raw):
                        result["errors"].append("Unsupported or truncated ds64 size table")
                    else:
                        for offset in range(28, 28 + table_len * 12, 12):
                            key, value = struct.unpack_from("<4sQ", raw, offset)
                            size_table.setdefault(key, []).append(value)
            elif chunk == b"fmt ":
                raw = f.read(min(size, 40))
                if len(raw) < 16:
                    result["errors"].append("Truncated format chunk")
                else:
                    code, channels, rate, _, align, bits = struct.unpack_from("<HHIIHH", raw)
                    result.update(format_tag=code, block_align=align, container_bits=bits)
            elif chunk == b"data":
                data_seen = True
                result["data_bytes"] = result.get("data_bytes", 0) + size
            elif chunk == b"bext":
                result["present"] = True
                raw = f.read(min(size, 602 + 65536))
                if len(raw) < 602:
                    result["warnings"].append("bext is shorter than the 602-byte fixed header")
                if len(raw) >= 348:
                    result.update(description=_text(raw[:256]), originator=_text(raw[256:288]),
                                  originator_reference=_text(raw[288:320]),
                                  origination_date=_text(raw[320:330]), origination_time=_text(raw[330:338]),
                                  time_reference=struct.unpack_from("<Q", raw, 338)[0],
                                  version=struct.unpack_from("<H", raw, 346)[0],
                                  coding_history=_text(raw[602:]) if len(raw) >= 602 else None)
                if size > 602 + 65536:
                    result["warnings"].append("CodingHistory display limited to 64 KiB")
            f.seek(start + size + (size % 2))
        else:
            result["warnings"].append("Chunk inspection stopped at 100,000 chunks")
        if rf64 and data64 is None:
            result["errors"].append("RF64/BW64 is missing a valid ds64 chunk")
        if not data_seen:
            result["errors"].append("No readable data chunk")
        if result.get("block_align") and result.get("format_tag") in (1, 3, 65534):
            size = result.get("data_bytes", 0)
            if size % result["block_align"]:
                result["errors"].append("PCM data contains an incomplete sample frame")
            result["declared_sample_frames"] = size // result["block_align"]
    return result
