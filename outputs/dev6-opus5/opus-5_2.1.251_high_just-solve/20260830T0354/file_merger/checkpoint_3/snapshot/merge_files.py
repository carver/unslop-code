#!/usr/bin/env python3
"""Merge heterogeneous tabular inputs into one schema-aligned, globally sorted CSV.

Supported inputs: CSV, TSV, JSON Lines (NDJSON) and Parquet, each optionally
gzip compressed.  The tool is streaming end to end: text formats are read line
by line, Parquet is read row group / batch wise, and sorting uses an external
(on-disk) merge sort so that inputs much larger than ``--memory-limit-mb`` can
be processed.

Output is a single CSV by default.  When any partitioning flag is given
(--partition-by / --max-rows-per-file / --max-bytes-per-file) --output names a
directory instead: rows are laid out in Hive-style ``col=value`` directories
and/or cut into sequentially numbered ``part-00000.csv`` shards.  The directory
is built in a sibling temporary directory and renamed into place on success, so
a failed run leaves no partial tree behind.

Schema reconciliation (when --schema is not given) resolves each column from
the evidence every input offers about it: Parquet declares its own types,
JSON Lines carries typed values, CSV/TSV are inferred from their text.
--schema-strategy picks between disagreeing inputs -- ``authoritative`` trusts
the most strongly typed source (parquet > jsonl > csv/tsv), ``consensus`` takes
the type most files agree on (ties widen to a common type), ``union`` takes the
simplest type able to hold every observed value.

Exit codes
    0  success
    1  unexpected internal error
    2  usage / CLI error (bad flags, missing input, undetectable input format)
    3  schema error (invalid --schema, key column absent from resolved schema)
    4  cast error with --on-type-error=fail
    5  malformed input (bad CSV/TSV/JSONL, compression mismatch, literal tab)
    6  unsupported structure (nested JSONL or Parquet values)
"""

from __future__ import annotations

import argparse
import array
import csv
import gzip
import heapq
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
from datetime import date as _date, datetime, time as _time, timedelta, timezone

UTC = timezone.utc
PROG = "merge_files.py"

# --------------------------------------------------------------------------
# Errors / exit codes
# --------------------------------------------------------------------------

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_SCHEMA = 3
EXIT_TYPE = 4
EXIT_INPUT = 5
EXIT_UNSUPPORTED = 6


class AppError(Exception):
    """An error that is reported to the user with a specific exit code."""

    def __init__(self, message, code=EXIT_USAGE):
        Exception.__init__(self, message)
        self.code = code


def usage_error(msg):
    return AppError(msg, EXIT_USAGE)


def schema_error(msg):
    return AppError(msg, EXIT_SCHEMA)


def type_error(msg):
    return AppError(msg, EXIT_TYPE)


def input_error(msg):
    return AppError(msg, EXIT_INPUT)


def unsupported_error(msg):
    return AppError(msg, EXIT_UNSUPPORTED)


# Backwards compatible alias (checkpoint 1 name).
UserError = AppError


# --------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------

M_TS, M_DATE, M_BOOL, M_INT, M_FLOAT, M_STR = 1, 2, 4, 8, 16, 32
M_ALL = M_TS | M_DATE | M_BOOL | M_INT | M_FLOAT | M_STR

# Priority: timestamp > date > bool > int > float > string
TYPE_PRIORITY = (
    (M_TS, "timestamp"),
    (M_DATE, "date"),
    (M_BOOL, "bool"),
    (M_INT, "int"),
    (M_FLOAT, "float"),
    (M_STR, "string"),
)
VALID_TYPES = {name for _, name in TYPE_PRIORITY}

# The set of output types that can losslessly *hold* a value already known to
# be of the given type.  Used to widen conflicting types to a common one.
HOLDS = {
    "timestamp": M_TS | M_STR,
    "date": M_DATE | M_TS | M_STR,
    "bool": M_BOOL | M_STR,
    "int": M_INT | M_FLOAT | M_STR,
    "float": M_FLOAT | M_STR,
    "string": M_STR,
}

INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A timestamp *for inference purposes* must carry a time component, otherwise a
# plain ``YYYY-MM-DD`` column would be promoted to ``timestamp`` by priority.
TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?"
    r"(?:[Zz]|[+-]\d{2}:?\d{2}(?::\d{2})?)?$"
)

INT64_MIN, INT64_MAX = -(2 ** 63), 2 ** 63 - 1


def pick_type(mask: int) -> str:
    for m, name in TYPE_PRIORITY:
        if mask & m:
            return name
    return "string"


def widen(types):
    """Simplest single type able to hold every one of ``types``."""
    mask = M_ALL
    for t in types:
        mask &= HOLDS.get(t, M_STR)
    return pick_type(mask)


# --------------------------------------------------------------------------
# Casting
# --------------------------------------------------------------------------


def _cast_string(raw: str):
    return (raw, raw)


def _cast_int(raw: str):
    s = raw.strip()
    if INT_RE.match(s):
        v = int(s)
        return (str(v), v)
    return None


def _cast_float(raw: str):
    s = raw.strip()
    if FLOAT_RE.match(s):
        v = float(s)
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return (repr(v), v)
    return None


def _cast_bool(raw: str):
    s = raw.strip().lower()
    if s in ("true", "1"):
        return ("true", 1)
    if s in ("false", "0"):
        return ("false", 0)
    return None


def _cast_date(raw: str):
    s = raw.strip()
    if DATE_RE.match(s):
        try:
            d = _date.fromisoformat(s)
        except ValueError:
            return None
        return (d.isoformat(), d.toordinal())
    return None


def _parse_iso_datetime(s: str):
    """Parse an ISO-8601 date or date-time.  Returns a datetime or None."""
    s = s.strip()
    if not s:
        return None
    t = s
    if t[-1] in ("z", "Z"):
        t = t[:-1] + "+00:00"
    t = t.replace(",", ".", 1) if ("," in t and "." not in t) else t
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y%m%dT%H%M%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


def _format_ts(dt: datetime) -> str:
    out = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
    )
    if dt.microsecond:
        out += ".%06d" % dt.microsecond
    return out + "Z"


def _cast_timestamp(raw: str):
    dt = _parse_iso_datetime(raw)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return (_format_ts(dt), dt.timestamp())


CASTERS = {
    "string": _cast_string,
    "int": _cast_int,
    "float": _cast_float,
    "bool": _cast_bool,
    "date": _cast_date,
    "timestamp": _cast_timestamp,
}


# --------------------------------------------------------------------------
# Inference
# --------------------------------------------------------------------------


def value_candidates(raw: str) -> int:
    """Bit mask of the types a single non-null cell could be parsed as."""
    mask = M_STR
    s = raw.strip()
    if not s:
        return mask
    c0 = s[0]
    if c0.isdigit() or c0 in "+-.":
        if INT_RE.match(s):
            mask |= M_INT | M_FLOAT
            if s in ("0", "1"):
                mask |= M_BOOL
        elif FLOAT_RE.match(s):
            mask |= M_FLOAT
        if DATE_RE.match(s):
            if _cast_date(s) is not None:
                mask |= M_DATE
        elif TS_RE.match(s):
            if _cast_timestamp(s) is not None:
                mask |= M_TS
    else:
        low = s.lower()
        if low in ("true", "false"):
            mask |= M_BOOL
    return mask


# --------------------------------------------------------------------------
# Typed value normalisation
# --------------------------------------------------------------------------
#
# JSONL and Parquet hand us real Python objects.  They are normalised to the
# canonical text form the CSV/TSV path would have produced, so that a single
# set of cast rules applies to every cell no matter where it came from.
# ``MISSING`` marks "null / absent" and is rendered with the null literal.

MISSING = object()

_TRUE_FALSE = ("false", "true")


def normalize_typed(value, where):
    """Return canonical text for a typed value, or ``MISSING`` for null."""
    if value is None:
        return MISSING
    t = value.__class__
    if t is str:
        return value
    if t is bool:
        return _TRUE_FALSE[value]
    if t is int:
        return str(value)
    if t is float:
        # "prefer int if integer and within range; otherwise float"
        if value == value and -1e308 < value < 1e308:
            iv = int(value)
            if iv == value and INT64_MIN <= iv <= INT64_MAX:
                return str(iv)
        return repr(value)
    if t is datetime:
        if value.tzinfo is None:
            return _format_ts(value)
        return _format_ts(value.astimezone(UTC))
    if t is _date:
        return value.isoformat()
    if t is _time:
        return value.isoformat()
    if t is bytes or t is bytearray:
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, (list, dict, tuple, set)):
        raise unsupported_error(
            "nested value is not supported (flat records only) in %s" % where
        )
    if isinstance(value, bool):
        return _TRUE_FALSE[value]
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return normalize_typed(float(value), where)
    if isinstance(value, datetime):
        return normalize_typed(datetime.fromtimestamp(value.timestamp(), UTC), where)
    if isinstance(value, _date):
        return value.isoformat()
    return str(value)


def typed_candidates(value, where):
    """Candidate type mask for a typed (JSONL/Parquet) value."""
    if value is None:
        return None
    if value.__class__ is bool or isinstance(value, bool):
        return M_BOOL | M_STR
    if isinstance(value, float) and not isinstance(value, int):
        text = normalize_typed(value, where)
        if INT_RE.match(text):
            return M_INT | M_FLOAT | M_STR
        return M_FLOAT | M_STR
    text = normalize_typed(value, where)
    if text is MISSING:
        return None
    return value_candidates(text)


# --------------------------------------------------------------------------
# Snappy (raw block format) decompression -- pure Python
# --------------------------------------------------------------------------


def snappy_decompress(data):
    n = len(data)
    pos = 0
    shift = 0
    length = 0
    while pos < n:
        b = data[pos]
        pos += 1
        length |= (b & 0x7F) << shift
        if not b & 0x80:
            break
        shift += 7
        if shift > 32:
            raise input_error("corrupt snappy stream (bad length prefix)")
    out = bytearray()
    while pos < n:
        tag = data[pos]
        pos += 1
        kind = tag & 0x03
        if kind == 0:
            ln = tag >> 2
            if ln >= 60:
                extra = ln - 59
                ln = int.from_bytes(data[pos:pos + extra], "little")
                pos += extra
            ln += 1
            out += data[pos:pos + ln]
            pos += ln
            continue
        if kind == 1:
            ln = 4 + ((tag >> 2) & 0x07)
            offset = ((tag >> 5) & 0x07) << 8 | data[pos]
            pos += 1
        elif kind == 2:
            ln = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 2], "little")
            pos += 2
        else:
            ln = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
        if offset == 0 or offset > len(out):
            raise input_error("corrupt snappy stream (bad copy offset)")
        start = len(out) - offset
        if offset >= ln:
            out += out[start:start + ln]
        else:
            for i in range(ln):
                out.append(out[start + i])
    if length and len(out) != length:
        raise input_error("corrupt snappy stream (length mismatch)")
    return bytes(out)


# --------------------------------------------------------------------------
# Thrift compact protocol reader (enough for Parquet metadata)
# --------------------------------------------------------------------------

T_STOP = 0
T_TRUE = 1
T_FALSE = 2
T_BYTE = 3
T_I16 = 4
T_I32 = 5
T_I64 = 6
T_DOUBLE = 7
T_BINARY = 8
T_LIST = 9
T_SET = 10
T_MAP = 11
T_STRUCT = 12


class ThriftReader:
    """Minimal reader for the Thrift compact protocol."""

    __slots__ = ("buf", "pos")

    def __init__(self, buf, pos=0):
        self.buf = buf
        self.pos = pos

    def byte(self):
        b = self.buf[self.pos]
        self.pos += 1
        return b

    def varint(self):
        buf = self.buf
        pos = self.pos
        result = 0
        shift = 0
        while True:
            b = buf[pos]
            pos += 1
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
            if shift > 70:
                raise input_error("corrupt thrift data (varint overflow)")
        self.pos = pos
        return result

    def zigzag(self):
        n = self.varint()
        return (n >> 1) ^ -(n & 1)

    def binary(self):
        size = self.varint()
        out = self.buf[self.pos:self.pos + size]
        self.pos += size
        return out

    def double(self):
        v = struct.unpack_from("<d", self.buf, self.pos)[0]
        self.pos += 8
        return v

    def skip(self, ttype):
        if ttype in (T_TRUE, T_FALSE):
            return
        if ttype == T_BYTE:
            self.pos += 1
        elif ttype in (T_I16, T_I32, T_I64):
            self.varint()
        elif ttype == T_DOUBLE:
            self.pos += 8
        elif ttype == T_BINARY:
            size = self.varint()
            self.pos += size
        elif ttype in (T_LIST, T_SET):
            size, etype = self.list_header()
            for _ in range(size):
                self.skip(etype)
        elif ttype == T_MAP:
            size = self.varint()
            if size:
                kv = self.byte()
                ktype, vtype = kv >> 4, kv & 0x0F
                for _ in range(size):
                    self.skip(ktype)
                    self.skip(vtype)
        elif ttype == T_STRUCT:
            for _fid, ftype in self.fields():
                self.skip(ftype)
        else:
            raise input_error("corrupt thrift data (unknown type %d)" % ttype)

    def list_header(self):
        b = self.byte()
        size = b >> 4
        etype = b & 0x0F
        if size == 15:
            size = self.varint()
        return size, etype

    def fields(self):
        """Iterate ``(field_id, type)`` of one struct, up to its STOP marker."""
        last = 0
        while True:
            b = self.byte()
            if b == T_STOP:
                return
            delta = (b & 0xF0) >> 4
            ftype = b & 0x0F
            if delta:
                fid = last + delta
            else:
                fid = self.zigzag()
            last = fid
            yield fid, ftype

    def value(self, ttype):
        if ttype == T_TRUE:
            return True
        if ttype == T_FALSE:
            return False
        if ttype == T_BYTE:
            v = self.buf[self.pos]
            self.pos += 1
            return v - 256 if v > 127 else v
        if ttype in (T_I16, T_I32, T_I64):
            return self.zigzag()
        if ttype == T_DOUBLE:
            return self.double()
        if ttype == T_BINARY:
            return self.binary()
        raise input_error("corrupt thrift data (unexpected type %d)" % ttype)


# --------------------------------------------------------------------------
# Parquet
# --------------------------------------------------------------------------

# Physical types
PQ_BOOLEAN, PQ_INT32, PQ_INT64, PQ_INT96, PQ_FLOAT, PQ_DOUBLE, PQ_BYTE_ARRAY, \
    PQ_FLBA = range(8)

# ConvertedType
CT_UTF8, CT_MAP, CT_MAP_KEY_VALUE, CT_LIST, CT_ENUM, CT_DECIMAL, CT_DATE, \
    CT_TIME_MILLIS, CT_TIME_MICROS, CT_TIMESTAMP_MILLIS, CT_TIMESTAMP_MICROS, \
    CT_UINT_8, CT_UINT_16, CT_UINT_32, CT_UINT_64, CT_INT_8, CT_INT_16, \
    CT_INT_32, CT_INT_64, CT_JSON, CT_BSON, CT_INTERVAL = range(22)

# Encodings
ENC_PLAIN = 0
ENC_PLAIN_DICTIONARY = 2
ENC_RLE = 3
ENC_BIT_PACKED = 4
ENC_DELTA_BINARY_PACKED = 5
ENC_DELTA_LENGTH_BYTE_ARRAY = 6
ENC_DELTA_BYTE_ARRAY = 7
ENC_RLE_DICTIONARY = 8
ENC_BYTE_STREAM_SPLIT = 9

SUPPORTED_ENCODINGS = frozenset((
    ENC_PLAIN, ENC_PLAIN_DICTIONARY, ENC_RLE, ENC_BIT_PACKED,
    ENC_DELTA_BINARY_PACKED, ENC_DELTA_LENGTH_BYTE_ARRAY, ENC_DELTA_BYTE_ARRAY,
    ENC_RLE_DICTIONARY, ENC_BYTE_STREAM_SPLIT,
))

CODEC_NAMES = {
    0: "UNCOMPRESSED", 1: "SNAPPY", 2: "GZIP", 3: "LZO", 4: "BROTLI",
    5: "LZ4", 6: "ZSTD", 7: "LZ4_RAW",
}

REP_REQUIRED, REP_OPTIONAL, REP_REPEATED = 0, 1, 2

_LITTLE = sys.byteorder == "little"
_EPOCH_ORDINAL = _date(1970, 1, 1).toordinal()
_JULIAN_UNIX_EPOCH = 2440588  # julian day number of 1970-01-01


def _zstd_decompress(data):
    try:
        from compression import zstd as _zstd  # Python 3.14+
        return _zstd.decompress(data)
    except ImportError:
        pass
    try:
        import zstandard
    except ImportError:
        raise unsupported_error(
            "parquet ZSTD compression needs the 'zstandard' package or pyarrow"
        )
    return zstandard.ZstdDecompressor().decompress(data, max_output_size=1 << 31)


def _lz4_raw_decompress(data, expected):
    try:
        import lz4.block
    except ImportError:
        raise unsupported_error(
            "parquet LZ4 compression needs the 'lz4' package or pyarrow"
        )
    return lz4.block.decompress(data, uncompressed_size=expected)


def _brotli_decompress(data):
    try:
        import brotli
    except ImportError:
        raise unsupported_error(
            "parquet BROTLI compression needs the 'brotli' package or pyarrow"
        )
    return brotli.decompress(data)


def decompress_page(codec, data, expected):
    if codec == 0:
        return data
    if codec == 1:
        return snappy_decompress(data)
    if codec == 2:
        return gzip.decompress(data)
    if codec == 6:
        return _zstd_decompress(data)
    if codec in (5, 7):
        return _lz4_raw_decompress(data, expected)
    if codec == 4:
        return _brotli_decompress(data)
    raise unsupported_error(
        "parquet compression codec %s is not supported"
        % CODEC_NAMES.get(codec, codec)
    )


# ---- bit / RLE decoding ---------------------------------------------------


def _read_varint(buf, pos):
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def _unpack_bits(buf, pos, nbytes, bit_width, count, out):
    """Append ``count`` LSB-first bit-packed values of ``bit_width`` bits."""
    if bit_width == 0:
        out.extend([0] * count)
        return
    mask = (1 << bit_width) - 1
    acc = 0
    bits = 0
    end = pos + nbytes
    n = 0
    while pos < end and n < count:
        acc |= buf[pos] << bits
        pos += 1
        bits += 8
        while bits >= bit_width and n < count:
            out.append(acc & mask)
            acc >>= bit_width
            bits -= bit_width
            n += 1
    while n < count:
        out.append(0)
        n += 1


def decode_rle_hybrid(buf, pos, bit_width, count, end=None):
    """Decode the RLE / bit-packing hybrid used for levels and dict indices."""
    out = []
    byte_width = (bit_width + 7) // 8
    limit = len(buf) if end is None else end
    while len(out) < count:
        if pos >= limit:
            out.extend([0] * (count - len(out)))
            break
        header, pos = _read_varint(buf, pos)
        if header & 1:
            groups = header >> 1
            n = groups * 8
            nbytes = groups * bit_width
            want = min(n, count - len(out))
            _unpack_bits(buf, pos, nbytes, bit_width, want, out)
            pos += nbytes
        else:
            run = header >> 1
            if byte_width:
                val = int.from_bytes(buf[pos:pos + byte_width], "little")
                pos += byte_width
            else:
                val = 0
            if run:
                out.extend([val] * min(run, count - len(out)))
    return out, pos


def _bit_width(max_value):
    w = 0
    while max_value:
        w += 1
        max_value >>= 1
    return w


# ---- PLAIN & delta decoding ----------------------------------------------


def _plain_ints(buf, code, count, itemsize):
    arr = array.array(code)
    need = count * itemsize
    if len(buf) < need:
        raise input_error("truncated parquet data page")
    arr.frombytes(bytes(buf[:need]))
    if not _LITTLE:
        arr.byteswap()
    return arr.tolist(), need


def decode_plain(buf, phys, count, type_length):
    """Decode PLAIN encoded values; returns (values, bytes_consumed)."""
    if phys == PQ_BOOLEAN:
        out = []
        nbytes = (count + 7) // 8
        _unpack_bits(buf, 0, nbytes, 1, count, out)
        return [bool(v) for v in out], nbytes
    if phys == PQ_INT32:
        return _plain_ints(buf, "i", count, 4)
    if phys == PQ_INT64:
        return _plain_ints(buf, "q", count, 8)
    if phys == PQ_FLOAT:
        return _plain_ints(buf, "f", count, 4)
    if phys == PQ_DOUBLE:
        return _plain_ints(buf, "d", count, 8)
    if phys == PQ_INT96:
        out = []
        pos = 0
        for _ in range(count):
            lo = int.from_bytes(buf[pos:pos + 8], "little")
            day = int.from_bytes(buf[pos + 8:pos + 12], "little", signed=True)
            pos += 12
            out.append((day, lo))
        return out, pos
    if phys == PQ_FLBA:
        out = []
        pos = 0
        for _ in range(count):
            out.append(bytes(buf[pos:pos + type_length]))
            pos += type_length
        return out, pos
    # BYTE_ARRAY
    out = []
    pos = 0
    unpack = struct.unpack_from
    for _ in range(count):
        ln = unpack("<I", buf, pos)[0]
        pos += 4
        out.append(bytes(buf[pos:pos + ln]))
        pos += ln
    return out, pos


def decode_delta_binary_packed(buf, pos, count):
    block_size, pos = _read_varint(buf, pos)
    miniblocks, pos = _read_varint(buf, pos)
    total, pos = _read_varint(buf, pos)
    zz, pos = _read_varint(buf, pos)
    value = (zz >> 1) ^ -(zz & 1)
    if count is None:
        count = total
    out = []
    if count:
        out.append(value)
    per_miniblock = block_size // miniblocks if miniblocks else 0
    while len(out) < count:
        zz, pos = _read_varint(buf, pos)
        min_delta = (zz >> 1) ^ -(zz & 1)
        widths = list(buf[pos:pos + miniblocks])
        pos += miniblocks
        for w in widths:
            if len(out) >= count:
                # Still need to skip the miniblock bytes to stay aligned.
                pos += (per_miniblock * w) // 8
                continue
            deltas = []
            nbytes = (per_miniblock * w) // 8
            _unpack_bits(buf, pos, nbytes, w, per_miniblock, deltas)
            pos += nbytes
            for d in deltas:
                if len(out) >= count:
                    break
                value = value + min_delta + d
                out.append(value)
    return out[:count], pos


def decode_delta_length_byte_array(buf, pos, count):
    lengths, pos = decode_delta_binary_packed(buf, pos, count)
    out = []
    for ln in lengths:
        out.append(bytes(buf[pos:pos + ln]))
        pos += ln
    return out, pos


def decode_delta_byte_array(buf, pos, count):
    prefixes, pos = decode_delta_binary_packed(buf, pos, count)
    suffixes, pos = decode_delta_length_byte_array(buf, pos, count)
    out = []
    prev = b""
    for i in range(len(suffixes)):
        p = prefixes[i] if i < len(prefixes) else 0
        cur = prev[:p] + suffixes[i]
        out.append(cur)
        prev = cur
    return out, pos


def decode_byte_stream_split(buf, phys, count, type_length):
    if phys == PQ_FLOAT:
        width = 4
    elif phys == PQ_DOUBLE:
        width = 8
    elif phys == PQ_FLBA:
        width = type_length
    elif phys == PQ_INT32:
        width = 4
    elif phys == PQ_INT64:
        width = 8
    else:
        raise unsupported_error("BYTE_STREAM_SPLIT for physical type %d" % phys)
    raw = bytearray(count * width)
    for k in range(width):
        base = k * count
        for i in range(count):
            raw[i * width + k] = buf[base + i]
    return decode_plain(raw, phys, count, type_length)[0], count * width


# ---- schema / metadata ----------------------------------------------------


class PqColumn:
    """One flat leaf column of a Parquet file."""

    __slots__ = ("name", "phys", "type_length", "converted", "logical",
                 "max_def", "scale", "precision", "type_name", "convert")

    def __init__(self, name, phys, type_length, converted, logical, max_def,
                 scale, precision):
        self.name = name
        self.phys = phys
        self.type_length = type_length
        self.converted = converted
        self.logical = logical
        self.max_def = max_def
        self.scale = scale
        self.precision = precision
        self.type_name, self.convert = _column_converter(self)


def _decimal_from_bytes(raw, scale):
    from decimal import Decimal
    unscaled = int.from_bytes(raw, "big", signed=True)
    if not scale:
        return Decimal(unscaled)
    return Decimal(unscaled).scaleb(-scale)


def _decimal_from_int(value, scale):
    from decimal import Decimal
    if not scale:
        return Decimal(value)
    return Decimal(value).scaleb(-scale)


_EPOCH_DT = datetime(1970, 1, 1, tzinfo=UTC)
_EPOCH_DT_NAIVE = datetime(1970, 1, 1)


def _dt_from_units(value, unit, utc):
    if unit == "millis":
        us = value * 1000
    elif unit == "nanos":
        us = value // 1000
    else:
        us = value
    base = _EPOCH_DT if utc else _EPOCH_DT_NAIVE
    return base + timedelta(microseconds=us)


def _time_from_units(value, unit):
    if unit == "millis":
        us = value * 1000
    elif unit == "nanos":
        us = value // 1000
    else:
        us = value
    us %= 86400000000
    return (_EPOCH_DT_NAIVE + timedelta(microseconds=us)).time()


def _column_converter(col):
    """Return ``(logical type name, converter)`` for a leaf column."""
    phys = col.phys
    lg = col.logical
    conv = col.converted
    kind = lg[0] if lg else None

    if phys == PQ_BOOLEAN:
        return "bool", None
    if phys == PQ_INT96:
        return "timestamp", lambda v: _dt_from_units(
            (v[0] - _JULIAN_UNIX_EPOCH) * 86400000000000 + v[1], "nanos", True)
    if phys in (PQ_FLOAT, PQ_DOUBLE):
        return "float", None

    if kind == "decimal" or conv == CT_DECIMAL:
        scale = col.scale or 0
        if phys in (PQ_BYTE_ARRAY, PQ_FLBA):
            return "float", lambda v, s=scale: _decimal_from_bytes(v, s)
        return "float", lambda v, s=scale: _decimal_from_int(v, s)

    if phys == PQ_INT32:
        if kind == "date" or conv == CT_DATE:
            return "date", lambda v: _date.fromordinal(_EPOCH_ORDINAL + v)
        if kind == "time" or conv in (CT_TIME_MILLIS,):
            unit = lg[2] if kind == "time" else "millis"
            return "string", lambda v, u=unit: _time_from_units(v, u)
        if kind == "integer" and not lg[2]:
            bits = lg[1]
            return "int", lambda v, m=(1 << bits) - 1: v & m
        if conv in (CT_UINT_8, CT_UINT_16, CT_UINT_32):
            return "int", lambda v: v & 0xFFFFFFFF
        return "int", None
    if phys == PQ_INT64:
        if kind == "timestamp":
            unit, utc = lg[2], lg[1]
            return "timestamp", lambda v, u=unit, a=utc: _dt_from_units(v, u, a)
        if conv == CT_TIMESTAMP_MILLIS:
            return "timestamp", lambda v: _dt_from_units(v, "millis", True)
        if conv == CT_TIMESTAMP_MICROS:
            return "timestamp", lambda v: _dt_from_units(v, "micros", True)
        if kind == "time" or conv == CT_TIME_MICROS:
            unit = lg[2] if kind == "time" else "micros"
            return "string", lambda v, u=unit: _time_from_units(v, u)
        if kind == "integer" and not lg[2]:
            return "int", lambda v: v & 0xFFFFFFFFFFFFFFFF
        if conv == CT_UINT_64:
            return "int", lambda v: v & 0xFFFFFFFFFFFFFFFF
        return "int", None

    # BYTE_ARRAY / FIXED_LEN_BYTE_ARRAY
    if kind == "float16":
        return "float", lambda v: struct.unpack("<e", v)[0]
    if kind == "uuid":
        return "string", lambda v: "%s-%s-%s-%s-%s" % (
            v[0:4].hex(), v[4:6].hex(), v[6:8].hex(), v[8:10].hex(), v[10:16].hex())
    if kind in ("string", "json", "bson", "enum") or conv in (
            CT_UTF8, CT_JSON, CT_BSON, CT_ENUM):
        return "string", lambda v: v.decode("utf-8", "replace")
    return "string", lambda v: v.decode("utf-8", "replace")


_LOGICAL_UNITS = {1: "millis", 2: "micros", 3: "nanos"}


def _parse_time_unit(tr):
    unit = "millis"
    for fid, ftype in tr.fields():
        if fid in _LOGICAL_UNITS and ftype == T_STRUCT:
            unit = _LOGICAL_UNITS[fid]
            tr.skip(ftype)
        else:
            tr.skip(ftype)
    return unit


def _parse_logical_type(tr):
    """Parse the LogicalType union; returns a small descriptive tuple."""
    result = None
    for fid, ftype in tr.fields():
        if fid == 1:
            tr.skip(ftype)
            result = ("string",)
        elif fid == 2:
            tr.skip(ftype)
            result = ("map",)
        elif fid == 3:
            tr.skip(ftype)
            result = ("list",)
        elif fid == 4:
            tr.skip(ftype)
            result = ("enum",)
        elif fid == 5:
            scale = precision = 0
            for f2, t2 in tr.fields():
                if f2 == 1:
                    scale = tr.value(t2)
                elif f2 == 2:
                    precision = tr.value(t2)
                else:
                    tr.skip(t2)
            result = ("decimal", scale, precision)
        elif fid == 6:
            tr.skip(ftype)
            result = ("date",)
        elif fid in (7, 8):
            utc = False
            unit = "millis"
            for f2, t2 in tr.fields():
                if f2 == 1:
                    utc = bool(tr.value(t2))
                elif f2 == 2 and t2 == T_STRUCT:
                    unit = _parse_time_unit(tr)
                else:
                    tr.skip(t2)
            result = ("time" if fid == 7 else "timestamp", utc, unit)
        elif fid == 10:
            bits = 64
            signed = True
            for f2, t2 in tr.fields():
                if f2 == 1:
                    bits = tr.value(t2)
                elif f2 == 2:
                    signed = bool(tr.value(t2))
                else:
                    tr.skip(t2)
            result = ("integer", bits, signed)
        elif fid == 12:
            tr.skip(ftype)
            result = ("json",)
        elif fid == 13:
            tr.skip(ftype)
            result = ("bson",)
        elif fid == 14:
            tr.skip(ftype)
            result = ("uuid",)
        elif fid == 15:
            tr.skip(ftype)
            result = ("float16",)
        else:
            tr.skip(ftype)
    return result


def _parse_schema_element(tr):
    el = {"type": None, "type_length": 0, "repetition": REP_REQUIRED,
          "name": "", "num_children": 0, "converted": None, "scale": 0,
          "precision": 0, "logical": None}
    for fid, ftype in tr.fields():
        if fid == 1:
            el["type"] = tr.value(ftype)
        elif fid == 2:
            el["type_length"] = tr.value(ftype)
        elif fid == 3:
            el["repetition"] = tr.value(ftype)
        elif fid == 4:
            el["name"] = tr.value(ftype).decode("utf-8", "replace")
        elif fid == 5:
            el["num_children"] = tr.value(ftype)
        elif fid == 6:
            el["converted"] = tr.value(ftype)
        elif fid == 7:
            el["scale"] = tr.value(ftype)
        elif fid == 8:
            el["precision"] = tr.value(ftype)
        elif fid == 10 and ftype == T_STRUCT:
            el["logical"] = _parse_logical_type(tr)
        else:
            tr.skip(ftype)
    return el


def _parse_column_meta(tr):
    meta = {"type": None, "encodings": [], "path": [], "codec": 0,
            "num_values": 0, "data_page_offset": 0, "dict_page_offset": None,
            "total_compressed_size": 0}
    for fid, ftype in tr.fields():
        if fid == 1:
            meta["type"] = tr.value(ftype)
        elif fid == 2:
            size, etype = tr.list_header()
            meta["encodings"] = [tr.value(etype) for _ in range(size)]
        elif fid == 3:
            size, etype = tr.list_header()
            meta["path"] = [tr.value(etype).decode("utf-8", "replace")
                            for _ in range(size)]
        elif fid == 4:
            meta["codec"] = tr.value(ftype)
        elif fid == 5:
            meta["num_values"] = tr.value(ftype)
        elif fid == 7:
            meta["total_compressed_size"] = tr.value(ftype)
        elif fid == 9:
            meta["data_page_offset"] = tr.value(ftype)
        elif fid == 11:
            meta["dict_page_offset"] = tr.value(ftype)
        else:
            tr.skip(ftype)
    return meta


def _parse_row_group(tr):
    rg = {"columns": [], "total_byte_size": 0, "num_rows": 0}
    for fid, ftype in tr.fields():
        if fid == 1:
            size, etype = tr.list_header()
            cols = []
            for _ in range(size):
                chunk = {"file_path": None, "meta": None}
                for f2, t2 in tr.fields():
                    if f2 == 1:
                        chunk["file_path"] = tr.value(t2).decode("utf-8", "replace")
                    elif f2 == 3 and t2 == T_STRUCT:
                        chunk["meta"] = _parse_column_meta(tr)
                    else:
                        tr.skip(t2)
                cols.append(chunk)
            rg["columns"] = cols
        elif fid == 2:
            rg["total_byte_size"] = tr.value(ftype)
        elif fid == 3:
            rg["num_rows"] = tr.value(ftype)
        else:
            tr.skip(ftype)
    return rg


def parse_file_metadata(buf):
    tr = ThriftReader(buf)
    meta = {"schema": [], "num_rows": 0, "row_groups": [], "created_by": None}
    for fid, ftype in tr.fields():
        if fid == 2:
            size, etype = tr.list_header()
            meta["schema"] = [_parse_schema_element(tr) for _ in range(size)]
        elif fid == 3:
            meta["num_rows"] = tr.value(ftype)
        elif fid == 4:
            size, etype = tr.list_header()
            meta["row_groups"] = [_parse_row_group(tr) for _ in range(size)]
        elif fid == 6:
            meta["created_by"] = tr.value(ftype).decode("utf-8", "replace")
        else:
            tr.skip(ftype)
    return meta


# ---- page level reading ---------------------------------------------------

PT_DATA_PAGE, PT_INDEX_PAGE, PT_DICTIONARY_PAGE, PT_DATA_PAGE_V2 = range(4)
_HEADER_PROBE = 1 << 16


def _parse_page_header(buf):
    tr = ThriftReader(buf)
    hdr = {"type": None, "uncompressed": 0, "compressed": 0, "v1": None,
           "dict": None, "v2": None}
    for fid, ftype in tr.fields():
        if fid == 1:
            hdr["type"] = tr.value(ftype)
        elif fid == 2:
            hdr["uncompressed"] = tr.value(ftype)
        elif fid == 3:
            hdr["compressed"] = tr.value(ftype)
        elif fid == 5 and ftype == T_STRUCT:
            sub = {"num_values": 0, "encoding": ENC_PLAIN,
                   "def_encoding": ENC_RLE, "rep_encoding": ENC_RLE}
            for f2, t2 in tr.fields():
                if f2 == 1:
                    sub["num_values"] = tr.value(t2)
                elif f2 == 2:
                    sub["encoding"] = tr.value(t2)
                elif f2 == 3:
                    sub["def_encoding"] = tr.value(t2)
                elif f2 == 4:
                    sub["rep_encoding"] = tr.value(t2)
                else:
                    tr.skip(t2)
            hdr["v1"] = sub
        elif fid == 7 and ftype == T_STRUCT:
            sub = {"num_values": 0, "encoding": ENC_PLAIN}
            for f2, t2 in tr.fields():
                if f2 == 1:
                    sub["num_values"] = tr.value(t2)
                elif f2 == 2:
                    sub["encoding"] = tr.value(t2)
                else:
                    tr.skip(t2)
            hdr["dict"] = sub
        elif fid == 8 and ftype == T_STRUCT:
            sub = {"num_values": 0, "num_nulls": 0, "num_rows": 0,
                   "encoding": ENC_PLAIN, "def_len": 0, "rep_len": 0,
                   "is_compressed": True}
            for f2, t2 in tr.fields():
                if f2 == 1:
                    sub["num_values"] = tr.value(t2)
                elif f2 == 2:
                    sub["num_nulls"] = tr.value(t2)
                elif f2 == 3:
                    sub["num_rows"] = tr.value(t2)
                elif f2 == 4:
                    sub["encoding"] = tr.value(t2)
                elif f2 == 5:
                    sub["def_len"] = tr.value(t2)
                elif f2 == 6:
                    sub["rep_len"] = tr.value(t2)
                elif f2 == 7:
                    sub["is_compressed"] = bool(tr.value(t2))
                else:
                    tr.skip(t2)
            hdr["v2"] = sub
        else:
            tr.skip(ftype)
    return hdr, tr.pos


def _unpack_bits_msb(buf, pos, nbytes, bit_width, count):
    """Legacy BIT_PACKED level decoding (MSB first)."""
    out = []
    acc = 0
    bits = 0
    for i in range(nbytes):
        acc = (acc << 8) | buf[pos + i]
        bits += 8
        while bits >= bit_width and len(out) < count:
            bits -= bit_width
            out.append((acc >> bits) & ((1 << bit_width) - 1))
            acc &= (1 << bits) - 1
        if len(out) >= count:
            break
    while len(out) < count:
        out.append(0)
    return out


def _decode_values(encoding, data, pos, count, col, dictionary):
    """Decode ``count`` non-null values starting at ``pos``."""
    phys = col.phys
    if encoding in (ENC_PLAIN_DICTIONARY, ENC_RLE_DICTIONARY):
        if dictionary is None:
            raise input_error("parquet data page references a missing dictionary")
        if count == 0:
            return []
        bit_width = data[pos]
        idx, _ = decode_rle_hybrid(data, pos + 1, bit_width, count)
        return [dictionary[i] for i in idx]
    if encoding == ENC_PLAIN:
        return decode_plain(memoryview(data)[pos:], phys, count, col.type_length)[0]
    if encoding == ENC_RLE:
        # Boolean values stored with the hybrid encoding.
        length = struct.unpack_from("<I", data, pos)[0]
        vals, _ = decode_rle_hybrid(data, pos + 4, 1, count, end=pos + 4 + length)
        return [bool(v) for v in vals]
    if encoding == ENC_DELTA_BINARY_PACKED:
        return decode_delta_binary_packed(data, pos, count)[0]
    if encoding == ENC_DELTA_LENGTH_BYTE_ARRAY:
        return decode_delta_length_byte_array(data, pos, count)[0]
    if encoding == ENC_DELTA_BYTE_ARRAY:
        return decode_delta_byte_array(data, pos, count)[0]
    if encoding == ENC_BYTE_STREAM_SPLIT:
        return decode_byte_stream_split(memoryview(data)[pos:], phys, count,
                                        col.type_length)[0]
    raise unsupported_error("parquet encoding %d is not supported" % encoding)


class ParquetReader:
    """Streaming, row-group-wise Parquet reader (flat schemas only)."""

    def __init__(self, path):
        self.path = path
        try:
            self.fh = open(path, "rb")
        except OSError as exc:
            raise usage_error("cannot open %s: %s" % (path, exc))
        try:
            self._read_footer()
        except AppError:
            self.close()
            raise
        except (IndexError, struct.error, ValueError) as exc:
            self.close()
            raise input_error("%s: malformed parquet file (%s)" % (path, exc))

    def close(self):
        try:
            self.fh.close()
        except OSError:
            pass

    def _read_footer(self):
        fh = self.fh
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size < 12:
            raise input_error("%s: not a parquet file (too small)" % self.path)
        fh.seek(0)
        if fh.read(4) != b"PAR1":
            raise input_error("%s: not a parquet file (bad magic)" % self.path)
        fh.seek(size - 8)
        tail = fh.read(8)
        if tail[4:] != b"PAR1":
            raise input_error("%s: not a parquet file (bad footer magic)" % self.path)
        flen = struct.unpack("<I", tail[:4])[0]
        if flen + 8 > size:
            raise input_error("%s: malformed parquet footer" % self.path)
        fh.seek(size - 8 - flen)
        meta = parse_file_metadata(fh.read(flen))
        self.meta = meta
        elements = meta["schema"]
        if not elements:
            raise input_error("%s: parquet file has no schema" % self.path)
        cols = []
        for el in elements[1:]:
            if el["num_children"]:
                raise unsupported_error(
                    "%s: nested column %r is not supported (flat schemas only)"
                    % (self.path, el["name"]))
            if el["repetition"] == REP_REPEATED:
                raise unsupported_error(
                    "%s: repeated column %r is not supported (flat schemas only)"
                    % (self.path, el["name"]))
            if el["type"] is None:
                raise unsupported_error(
                    "%s: group column %r is not supported (flat schemas only)"
                    % (self.path, el["name"]))
            if el["logical"] and el["logical"][0] in ("list", "map"):
                raise unsupported_error(
                    "%s: nested column %r is not supported (flat schemas only)"
                    % (self.path, el["name"]))
            if el["converted"] in (CT_LIST, CT_MAP, CT_MAP_KEY_VALUE):
                raise unsupported_error(
                    "%s: nested column %r is not supported (flat schemas only)"
                    % (self.path, el["name"]))
            cols.append(PqColumn(
                el["name"], el["type"], el["type_length"], el["converted"],
                el["logical"], 1 if el["repetition"] == REP_OPTIONAL else 0,
                el["scale"], el["precision"]))
        self.columns = cols
        self.num_rows = meta["num_rows"]

    def declared_types(self):
        return {c.name: c.type_name for c in self.columns}

    def uses_unsupported_features(self):
        """True when a codec/encoding this reader cannot handle is present."""
        for rg in self.meta["row_groups"]:
            for chunk in rg["columns"]:
                cm = chunk["meta"]
                if cm is None:
                    return True
                if cm["codec"] in (3, 4, 5, 6, 7):
                    return True
                for enc in cm["encodings"]:
                    if enc not in SUPPORTED_ENCODINGS:
                        return True
        return False

    def _page_header(self, offset):
        fh = self.fh
        probe = _HEADER_PROBE
        while True:
            fh.seek(offset)
            buf = fh.read(probe)
            if not buf:
                raise input_error("%s: truncated parquet column chunk" % self.path)
            try:
                hdr, hlen = _parse_page_header(buf)
            except IndexError:
                if len(buf) < probe:
                    raise input_error("%s: truncated parquet page header" % self.path)
                probe *= 4
                continue
            return hdr, offset + hlen

    def _column_values(self, chunk_meta, col):
        """Yield every value (``None`` for null) of one column chunk."""
        fh = self.fh
        codec = chunk_meta["codec"]
        offset = chunk_meta["data_page_offset"]
        dict_off = chunk_meta["dict_page_offset"]
        if dict_off:
            offset = min(offset, dict_off)
        remaining = chunk_meta["num_values"]
        dictionary = None
        convert = col.convert
        max_def = col.max_def
        bw = _bit_width(max_def)
        while remaining > 0:
            hdr, data_off = self._page_header(offset)
            fh.seek(data_off)
            raw = fh.read(hdr["compressed"])
            offset = data_off + hdr["compressed"]
            ptype = hdr["type"]
            if ptype == PT_DICTIONARY_PAGE and hdr["dict"] is not None:
                data = decompress_page(codec, raw, hdr["uncompressed"])
                n = hdr["dict"]["num_values"]
                vals = decode_plain(memoryview(data), col.phys, n, col.type_length)[0]
                dictionary = [convert(v) for v in vals] if convert else vals
                continue
            if ptype == PT_INDEX_PAGE:
                continue
            if ptype == PT_DATA_PAGE_V2 and hdr["v2"] is not None:
                info = hdr["v2"]
                nvals = info["num_values"]
                rl, dl = info["rep_len"], info["def_len"]
                levels_part = raw[:rl + dl]
                body = raw[rl + dl:]
                if info["is_compressed"]:
                    body = decompress_page(
                        codec, body, hdr["uncompressed"] - rl - dl)
                if max_def:
                    levels, _ = decode_rle_hybrid(levels_part, rl, bw, nvals,
                                                  end=rl + dl)
                else:
                    levels = None
                non_null = nvals - info["num_nulls"] if max_def else nvals
                values = _decode_values(info["encoding"], body, 0, non_null,
                                        col, dictionary)
            elif ptype == PT_DATA_PAGE and hdr["v1"] is not None:
                info = hdr["v1"]
                nvals = info["num_values"]
                data = decompress_page(codec, raw, hdr["uncompressed"])
                pos = 0
                levels = None
                if max_def:
                    if info["def_encoding"] == ENC_BIT_PACKED:
                        nbytes = (nvals * bw + 7) // 8
                        levels = _unpack_bits_msb(data, pos, nbytes, bw, nvals)
                        pos += nbytes
                    else:
                        length = struct.unpack_from("<I", data, pos)[0]
                        pos += 4
                        levels, _ = decode_rle_hybrid(data, pos, bw, nvals,
                                                      end=pos + length)
                        pos += length
                    non_null = 0
                    for lv in levels:
                        if lv == max_def:
                            non_null += 1
                else:
                    non_null = nvals
                values = _decode_values(info["encoding"], data, pos, non_null,
                                        col, dictionary)
            else:
                continue

            if convert and info["encoding"] not in (
                    ENC_PLAIN_DICTIONARY, ENC_RLE_DICTIONARY):
                values = [convert(v) for v in values]
            if levels is None:
                for v in values:
                    yield v
            else:
                it = iter(values)
                nxt = it.__next__
                for lv in levels:
                    yield nxt() if lv == max_def else None
            remaining -= nvals

    def iter_batches(self, batch_rows, wanted=None):
        """Yield ``(names, rows)`` batches, streaming within each row group."""
        cols = self.columns
        if wanted is None:
            selected = list(range(len(cols)))
        else:
            selected = [i for i, c in enumerate(cols) if c.name in wanted]
        names = [cols[i].name for i in selected]
        if not selected:
            for rg in self.meta["row_groups"]:
                left = rg["num_rows"]
                while left > 0:
                    n = min(batch_rows, left)
                    yield names, [[] for _ in range(n)]
                    left -= n
            return
        for rg in self.meta["row_groups"]:
            chunks = rg["columns"]
            gens = []
            for i in selected:
                col = cols[i]
                cm = self._chunk_for(chunks, col, i)
                gens.append(self._column_values(cm, col))
            rows = []
            for row in zip(*gens):
                rows.append(list(row))
                if len(rows) >= batch_rows:
                    yield names, rows
                    rows = []
            if rows:
                yield names, rows

    def _chunk_for(self, chunks, col, index):
        for chunk in chunks:
            cm = chunk["meta"]
            if cm is not None and cm["path"] and cm["path"][-1] == col.name:
                if chunk["file_path"]:
                    raise unsupported_error(
                        "%s: multi-file parquet datasets are not supported"
                        % self.path)
                return cm
        if index < len(chunks) and chunks[index]["meta"] is not None:
            return chunks[index]["meta"]
        raise input_error("%s: column %r missing from a row group"
                          % (self.path, col.name))

    def batch_rows_for(self, row_group_bytes, cap=65536):
        """Advisory batch sizing derived from --parquet-row-group-bytes."""
        avg = 0
        for rg in self.meta["row_groups"]:
            if rg["num_rows"]:
                avg = max(1.0, float(rg["total_byte_size"]) / rg["num_rows"])
                break
        if not avg:
            return cap
        return max(1, min(cap, int(row_group_bytes // avg) or 1))


# --------------------------------------------------------------------------
# pyarrow fallback (only used for parquet features the builtin reader lacks)
# --------------------------------------------------------------------------


def _try_pyarrow():
    if os.environ.get("MERGE_FILES_NO_PYARROW"):
        return None
    try:
        import pyarrow.parquet as pq  # noqa: F401
        return pq
    except Exception:
        return None


def _arrow_type_name(t, path, name):
    import pyarrow as pa
    if pa.types.is_boolean(t):
        return "bool"
    if pa.types.is_integer(t):
        return "int"
    if pa.types.is_floating(t) or pa.types.is_decimal(t):
        return "float"
    if pa.types.is_date(t):
        return "date"
    if pa.types.is_timestamp(t):
        return "timestamp"
    if pa.types.is_nested(t):
        raise unsupported_error(
            "%s: nested column %r is not supported (flat schemas only)"
            % (path, name))
    return "string"


class PyArrowReader:
    """Same surface as :class:`ParquetReader`, backed by pyarrow."""

    def __init__(self, path, pq):
        self.path = path
        try:
            self.pf = pq.ParquetFile(path)
        except Exception as exc:
            raise input_error("%s: cannot read parquet file (%s)" % (path, exc))
        schema = self.pf.schema_arrow
        self.types = {}
        for field in schema:
            self.types[field.name] = _arrow_type_name(field.type, path, field.name)
        self.num_rows = self.pf.metadata.num_rows if self.pf.metadata else 0

    def close(self):
        try:
            self.pf.close()
        except Exception:
            pass

    def declared_types(self):
        return dict(self.types)

    def batch_rows_for(self, row_group_bytes, cap=65536):
        md = self.pf.metadata
        avg = 0.0
        if md is not None and md.num_row_groups:
            rg = md.row_group(0)
            if rg.num_rows:
                avg = max(1.0, float(rg.total_byte_size) / rg.num_rows)
        if not avg:
            return cap
        return max(1, min(cap, int(row_group_bytes // avg) or 1))

    def iter_batches(self, batch_rows, wanted=None):
        names = list(self.types)
        if wanted is not None:
            names = [n for n in names if n in wanted]
        try:
            batches = self.pf.iter_batches(batch_size=batch_rows,
                                           columns=names or None)
            for batch in batches:
                cols = [batch.column(i).to_pylist() for i in range(batch.num_columns)]
                bnames = [f.name for f in batch.schema]
                rows = [list(r) for r in zip(*cols)] if cols else \
                    [[] for _ in range(batch.num_rows)]
                yield bnames, rows
        except AppError:
            raise
        except Exception as exc:
            raise input_error("%s: cannot read parquet file (%s)" % (self.path, exc))


# --------------------------------------------------------------------------
# Input format / compression detection
# --------------------------------------------------------------------------

GZIP_MAGIC = b"\x1f\x8b"
PARQUET_MAGIC = b"PAR1"

EXT_FORMAT = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
}


def _peek_raw(path, n=8):
    try:
        with open(path, "rb") as fh:
            return fh.read(n)
    except OSError as exc:
        raise usage_error("cannot read %s: %s" % (path, exc))


def _peek_decompressed(path, comp, n=8):
    try:
        if comp == "gzip":
            with gzip.open(path, "rb") as fh:
                return fh.read(n)
        with open(path, "rb") as fh:
            return fh.read(n)
    except OSError as exc:
        raise usage_error("cannot read %s: %s" % (path, exc))
    except (EOFError, gzip.BadGzipFile) as exc:
        raise input_error("%s: corrupt gzip stream (%s)" % (path, exc))


def resolve_compression(path, requested):
    """Decide gzip vs none for one input; mismatches are an input error."""
    head = _peek_raw(path, 2)
    looks_gzip = head[:2] == GZIP_MAGIC
    ext_gzip = path.lower().endswith(".gz")
    if requested == "gzip":
        if not looks_gzip:
            raise input_error(
                "%s: --compression=gzip but the file is not gzip compressed" % path)
        return "gzip"
    if requested == "none":
        if looks_gzip:
            raise input_error(
                "%s: --compression=none but the file is gzip compressed" % path)
        return "none"
    if ext_gzip and not looks_gzip:
        raise input_error(
            "%s: .gz extension but the file is not gzip compressed" % path)
    return "gzip" if (ext_gzip or looks_gzip) else "none"


def resolve_format(path, comp, requested):
    if requested != "auto":
        return requested
    name = os.path.basename(path).lower()
    if name.endswith(".gz"):
        name = name[:-3]
    ext = os.path.splitext(name)[1]
    fmt = EXT_FORMAT.get(ext)
    if fmt is not None:
        return fmt
    # Ambiguous extension: fall back to the magic bytes.
    if _peek_decompressed(path, comp, 4) == PARQUET_MAGIC:
        return "parquet"
    raise usage_error(
        "%s: cannot determine input format from the file name or contents; "
        "use --input-format" % path)


def open_text(path, comp):
    """Open a (possibly gzipped) text input for csv/tsv/jsonl reading."""
    try:
        if comp == "gzip":
            raw = gzip.open(path, "rb")
        else:
            raw = open(path, "rb")
    except OSError as exc:
        raise usage_error("cannot open %s: %s" % (path, exc))
    return io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")


# --------------------------------------------------------------------------
# Input sources
# --------------------------------------------------------------------------
#
# Every source yields ``(index_map, values)`` pairs.  ``index_map`` maps a
# column name to its position in ``values`` and is reused for as long as the
# layout stays the same, so consumers can cache their column lookups on it.

# Source precedence used by --schema-strategy=authoritative: the more a format
# knows about its own types, the more it is trusted.
RANK_UNTYPED, RANK_JSONL, RANK_PARQUET = 0, 1, 2


class Source:
    kind = ""
    typed = False
    rank = RANK_UNTYPED

    def __init__(self, path, comp, ctx):
        self.path = path
        self.comp = comp
        self.ctx = ctx
        self.line_num = 0

    def column_names(self):
        """Names known without reading data (None when a scan is required)."""
        return None

    def declared_types(self):
        return None

    def rows(self, wanted=None):
        raise NotImplementedError

    def close(self):
        pass


class DelimitedSource(Source):
    """CSV and TSV."""

    def __init__(self, path, comp, ctx, kind):
        Source.__init__(self, path, comp, ctx)
        self.kind = kind
        self._names = None

    def _reader_kwargs(self):
        args = self.ctx.args
        if self.kind == "tsv":
            return {"delimiter": "\t", "quoting": csv.QUOTE_NONE,
                    "quotechar": None, "escapechar": None,
                    "doublequote": False}
        kw = {"delimiter": ",", "quotechar": args.csv_quotechar}
        if args.csv_escapechar is not None:
            kw["doublequote"] = False
            kw["escapechar"] = args.csv_escapechar
        else:
            kw["doublequote"] = True
        return kw

    def column_names(self):
        if self._names is None:
            fh = open_text(self.path, self.comp)
            try:
                rd = csv.reader(fh, **self._reader_kwargs())
                try:
                    header = next(rd)
                except StopIteration:
                    header = []
                except csv.Error as exc:
                    raise input_error("%s: malformed %s header (%s)"
                                      % (self.path, self.kind, exc))
                except UnicodeDecodeError as exc:
                    raise input_error("%s: input is not valid UTF-8 (%s)"
                                      % (self.path, exc))
                except (EOFError, OSError) as exc:
                    raise input_error("%s: corrupt gzip stream (%s)"
                                      % (self.path, exc))
            finally:
                fh.close()
            if self.kind == "tsv" and header == []:
                raise input_error("%s: TSV input has no header row" % self.path)
            self._names = header
        return self._names

    def rows(self, wanted=None):
        fh = open_text(self.path, self.comp)
        try:
            rd = csv.reader(fh, **self._reader_kwargs())
            try:
                header = next(rd)
            except StopIteration:
                if self.kind == "tsv":
                    raise input_error("%s: TSV input has no header row" % self.path)
                return
            except csv.Error as exc:
                raise input_error("%s: malformed %s header (%s)"
                                  % (self.path, self.kind, exc))
            except UnicodeDecodeError as exc:
                raise input_error("%s: input is not valid UTF-8 (%s)"
                                  % (self.path, exc))
            except (EOFError, OSError) as exc:
                raise input_error("%s: corrupt gzip stream (%s)" % (self.path, exc))
            self._names = header
            imap = {}
            for pos, name in enumerate(header):
                if name not in imap:
                    imap[name] = pos
            width = len(header)
            strict_width = self.kind == "tsv"
            while True:
                try:
                    row = next(rd)
                except StopIteration:
                    break
                except csv.Error as exc:
                    raise input_error("%s: malformed %s input at line %d (%s)"
                                      % (self.path, self.kind, rd.line_num, exc))
                except UnicodeDecodeError as exc:
                    raise input_error("%s: input is not valid UTF-8 (%s)"
                                      % (self.path, exc))
                except (EOFError, OSError) as exc:
                    raise input_error("%s: corrupt gzip stream (%s)"
                                      % (self.path, exc))
                if not row:
                    continue
                self.line_num = rd.line_num
                if strict_width and len(row) > width:
                    raise input_error(
                        "%s: line %d has %d fields but the header has %d "
                        "(literal tab inside a TSV field?)"
                        % (self.path, rd.line_num, len(row), width))
                yield imap, row
        finally:
            fh.close()


class JsonlSource(Source):
    kind = "jsonl"
    typed = True
    rank = RANK_JSONL

    def __init__(self, path, comp, ctx):
        Source.__init__(self, path, comp, ctx)
        self._imaps = {}

    def rows(self, wanted=None):
        fh = open_text(self.path, self.comp)
        imaps = self._imaps
        try:
            lineno = 0
            while True:
                try:
                    line = fh.readline()
                except UnicodeDecodeError as exc:
                    raise input_error("%s: input is not valid UTF-8 (%s)"
                                      % (self.path, exc))
                except (EOFError, OSError) as exc:
                    raise input_error("%s: corrupt gzip stream (%s)"
                                      % (self.path, exc))
                if not line:
                    break
                lineno += 1
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError as exc:
                    raise input_error("%s: line %d is not valid JSON (%s)"
                                      % (self.path, lineno, exc))
                if not isinstance(obj, dict):
                    if isinstance(obj, list):
                        raise unsupported_error(
                            "%s: line %d is a JSON array; records must be flat "
                            "JSON objects" % (self.path, lineno))
                    raise input_error(
                        "%s: line %d is not a JSON object" % (self.path, lineno))
                keys = tuple(obj)
                imap = imaps.get(keys)
                if imap is None:
                    imap = {k: i for i, k in enumerate(keys)}
                    if len(imaps) > 4096:
                        imaps.clear()
                    imaps[keys] = imap
                self.line_num = lineno
                values = list(obj.values())
                for i, v in enumerate(values):
                    if v.__class__ is dict or v.__class__ is list:
                        raise unsupported_error(
                            "%s: line %d field %r has a nested value; records "
                            "must be flat" % (self.path, lineno, keys[i]))
                yield imap, values
        finally:
            fh.close()


class ParquetSource(Source):
    kind = "parquet"
    typed = True
    rank = RANK_PARQUET

    def __init__(self, path, comp, ctx):
        Source.__init__(self, path, comp, ctx)
        self._reader = None
        self._local = None

    def _local_path(self):
        if self.comp != "gzip":
            return self.path
        if self._local is None:
            fd, tmp = tempfile.mkstemp(prefix="pq_", suffix=".parquet",
                                       dir=self.ctx.tmpdir)
            try:
                with os.fdopen(fd, "wb") as out, gzip.open(self.path, "rb") as src:
                    shutil.copyfileobj(src, out, 1 << 20)
            except (OSError, EOFError, gzip.BadGzipFile) as exc:
                raise input_error("%s: corrupt gzip stream (%s)" % (self.path, exc))
            self._local = tmp
        return self._local

    def reader(self):
        if self._reader is None:
            path = self._local_path()
            rd = ParquetReader(path)
            rd.path = self.path
            if rd.uses_unsupported_features():
                pq = _try_pyarrow()
                if pq is not None:
                    rd.close()
                    rd = PyArrowReader(path, pq)
                    rd.path = self.path
            self._reader = rd
        return self._reader

    def close(self):
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    def column_names(self):
        rd = self.reader()
        return list(rd.declared_types())

    def declared_types(self):
        return self.reader().declared_types()

    def rows(self, wanted=None):
        rd = self.reader()
        batch_rows = rd.batch_rows_for(self.ctx.batch_bytes, self.ctx.batch_cap)
        imaps = {}
        for names, batch in rd.iter_batches(batch_rows, wanted):
            key = tuple(names)
            imap = imaps.get(key)
            if imap is None:
                imap = {n: i for i, n in enumerate(names)}
                imaps[key] = imap
            for row in batch:
                self.line_num += 1
                yield imap, row


def make_source(path, ctx):
    args = ctx.args
    if not os.path.exists(path):
        raise usage_error("input file not found: %s" % path)
    if os.path.isdir(path):
        raise usage_error("input is a directory: %s" % path)
    comp = resolve_compression(path, args.compression)
    fmt = resolve_format(path, comp, args.input_format)
    if fmt in ("csv", "tsv"):
        return DelimitedSource(path, comp, ctx, fmt)
    if fmt == "jsonl":
        return JsonlSource(path, comp, ctx)
    if fmt == "parquet":
        return ParquetSource(path, comp, ctx)
    raise usage_error("unsupported input format %r for %s" % (fmt, path))


# --------------------------------------------------------------------------
# Schema resolution
# --------------------------------------------------------------------------


def load_schema(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise schema_error("cannot read schema file %r: %s" % (path, exc))
    except ValueError as exc:
        raise schema_error("invalid JSON in schema file %r: %s" % (path, exc))
    if isinstance(data, list):
        data = {"columns": data}
    if not isinstance(data, dict) or not isinstance(data.get("columns"), list):
        raise schema_error("schema file must be an object with a 'columns' array")
    columns = []
    for i, col in enumerate(data["columns"]):
        if isinstance(col, str):
            columns.append((col, "string"))
            continue
        if not isinstance(col, dict) or "name" not in col:
            raise schema_error(
                "schema column #%d must be an object with a 'name'" % (i + 1))
        name = col["name"]
        typ = col.get("type", "string")
        if not isinstance(name, str) or not isinstance(typ, str):
            raise schema_error("schema column #%d has a non-string name/type" % (i + 1))
        if typ not in VALID_TYPES:
            raise schema_error(
                "schema column %r has unknown type %r (valid: %s)"
                % (name, typ, ", ".join(sorted(VALID_TYPES))))
        columns.append((name, typ))
    if not columns:
        raise schema_error("schema file declares no columns")
    return columns


def scan_source(src, ctx):
    """Collect column names and per-column type evidence for one input."""
    names = []
    seen_names = set()
    masks = {}
    seen = {}

    def add(name):
        if name not in seen_names:
            seen_names.add(name)
            names.append(name)
            masks[name] = M_ALL
            seen[name] = False

    declared = src.declared_types()
    if declared is not None:
        for name in declared:
            add(name)
            masks[name] = HOLDS.get(declared[name], M_STR)
            seen[name] = True
        return {"rank": src.rank, "names": names, "masks": masks,
                "seen": seen, "declared": declared}

    header = src.column_names()
    if header:
        for name in header:
            add(name)

    null_literal = ctx.null_literal
    typed = src.typed
    cached = None
    cols = ()
    for imap, values in src.rows():
        if imap is not cached:
            cached = imap
            for name in imap:
                add(name)
            cols = tuple(imap.items())
        n = len(values)
        for name, pos in cols:
            if pos >= n:
                continue
            v = values[pos]
            if typed:
                m = typed_candidates(v, src.path)
                if m is None:
                    continue
            else:
                if v is None or v == "" or (null_literal and v == null_literal):
                    continue
                m = value_candidates(v)
            seen[name] = True
            masks[name] &= m
    return {"rank": src.rank, "names": names, "masks": masks, "seen": seen,
            "declared": None}


def resolve_column_type(entries, strategy, infer):
    """Pick one output type from per-file evidence ``(rank, type, mask)``."""
    known = [e for e in entries if e[1] is not None]
    if not known:
        return "string"
    if strategy == "union":
        mask = M_ALL
        for _rank, _t, m in known:
            mask &= m
        return pick_type(mask)
    if strategy == "consensus":
        counts = {}
        for _rank, t, _m in known:
            counts[t] = counts.get(t, 0) + 1
        best = max(counts.values())
        tied = [t for t in counts if counts[t] == best]
        if len(tied) == 1:
            return tied[0]
        return widen(tied)
    # authoritative: the most strongly typed sources win.
    top = max(e[0] for e in known)
    group = [e for e in known if e[0] == top]
    types = {e[1] for e in group}
    if len(types) == 1:
        return types.pop()
    if infer == "loose":
        mask = M_ALL
        for _rank, _t, m in group:
            mask &= m
        return pick_type(mask)
    return "string"


def infer_schema(sources, ctx):
    """Infer output columns from every input; lexicographic column order."""
    args = ctx.args
    scans = [scan_source(src, ctx) for src in sources]
    names = set()
    for sc in scans:
        names.update(sc["names"])
    columns = []
    for name in sorted(names):
        entries = []
        for sc in scans:
            if name not in sc["masks"]:
                continue
            declared = sc["declared"]
            if declared is not None:
                entries.append((sc["rank"], declared[name], sc["masks"][name]))
            elif sc["seen"][name]:
                entries.append((sc["rank"], pick_type(sc["masks"][name]),
                                sc["masks"][name]))
            else:
                entries.append((sc["rank"], None, M_ALL))
        columns.append(
            (name, resolve_column_type(entries, args.schema_strategy, args.infer)))
    return columns


# --------------------------------------------------------------------------
# Record production
# --------------------------------------------------------------------------

NULL_KEY = [0]


def iter_records(sources, columns, key_positions, part_positions, ctx):
    """Yield ``[sortkey, seq, rendered_row]`` for every input row, in order.

    ``sortkey`` is the list of partition path segments (one per --partition-by
    column, already percent-encoded) followed by the comparable --key
    components.  Sorting on that prefix makes every partition's rows contiguous
    in the merged stream while keeping them ordered by --key inside it.
    """
    names = [c[0] for c in columns]
    types = [c[1] for c in columns]
    casters = [CASTERS[t] for t in types]
    ncols = len(columns)
    key_set = set(key_positions)
    part_set = set(part_positions)
    on_err = ctx.args.on_type_error
    null_literal = ctx.null_literal
    wanted = set(names)
    seq = 0

    for src in sources:
        typed = src.typed
        path = src.path
        cached = None
        idx = ()
        for imap, values in src.rows(wanted=wanted):
            if imap is not cached:
                cached = imap
                idx = [imap.get(n, -1) for n in names]
            rlen = len(values)
            rendered = [None] * ncols
            keys = {}
            parts = {}
            for c in range(ncols):
                p = idx[c]
                raw = values[p] if 0 <= p < rlen else None
                if typed:
                    text = MISSING if raw is None else normalize_typed(raw, path)
                elif raw is None or raw == "" or (null_literal and raw == null_literal):
                    text = MISSING
                else:
                    text = raw
                if text is MISSING:
                    rendered[c] = null_literal
                    if c in key_set:
                        keys[c] = NULL_KEY
                    if c in part_set:
                        parts[c] = NULL_SEGMENT
                    continue
                res = casters[c](text)
                if res is None:
                    if on_err == "fail":
                        raise type_error(
                            "cannot cast %r to type %r for column %r "
                            "(file %s, line %d)"
                            % (text, types[c], names[c], path, src.line_num))
                    if on_err == "keep-string":
                        rendered[c] = text
                        if c in key_set:
                            keys[c] = [1, 1, text]
                        if c in part_set:
                            parts[c] = encode_segment(text)
                        continue
                    rendered[c] = null_literal
                    if c in key_set:
                        keys[c] = NULL_KEY
                    if c in part_set:
                        parts[c] = NULL_SEGMENT
                    continue
                rendered[c] = res[0]
                if c in key_set:
                    keys[c] = [1, 0, res[1]]
                if c in part_set:
                    parts[c] = encode_segment(res[0])
            yield [[parts[c] for c in part_positions]
                   + [keys[c] for c in key_positions], seq, rendered]
            seq += 1
        src.close()


# --------------------------------------------------------------------------
# External sort
# --------------------------------------------------------------------------


def _key_asc(rec):
    return (rec[0], rec[1])


def _key_desc(rec):
    return (rec[0], -rec[1])


MAX_FANIN = 128


def estimate_size(rec):
    """Rough in-memory footprint of a buffered record, in bytes."""
    total = 200 + 200 * len(rec[0])
    for v in rec[2]:
        total += 60 + (len(v) if v else 0)
    return total


def _run_reader(fh):
    for line in fh:
        if line:
            yield json.loads(line)


def _write_run(records, path):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")


class _Sorter:
    """External merge sort with a bounded merge fan-in."""

    def __init__(self, desc, budget_bytes, tmpdir):
        self.desc = desc
        self.keyfn = _key_desc if desc else _key_asc
        self.budget = budget_bytes
        self.tmpdir = tmpdir
        self.runs = []
        self.handles = []
        self._counter = 0

    def _new_path(self):
        self._counter += 1
        return os.path.join(self.tmpdir, "run_%06d.jsonl" % self._counter)

    def _open(self, path):
        fh = open(path, "r", encoding="utf-8", newline="")
        self.handles.append(fh)
        return _run_reader(fh)

    def _merge(self, paths):
        return heapq.merge(*(self._open(p) for p in paths),
                           key=self.keyfn, reverse=self.desc)

    def close(self):
        for fh in self.handles:
            try:
                fh.close()
            except OSError:
                pass
        self.handles = []

    def sort(self, records):
        buf = []
        used = 0
        for rec in records:
            buf.append(rec)
            used += estimate_size(rec)
            if used >= self.budget:
                buf.sort(key=self.keyfn, reverse=self.desc)
                path = self._new_path()
                _write_run(buf, path)
                self.runs.append(path)
                buf = []
                used = 0

        if not self.runs:
            buf.sort(key=self.keyfn, reverse=self.desc)
            return iter(buf)

        if buf:
            buf.sort(key=self.keyfn, reverse=self.desc)
            path = self._new_path()
            _write_run(buf, path)
            self.runs.append(path)
            buf = []

        # Bound the number of simultaneously open run files.
        runs = self.runs
        while len(runs) > MAX_FANIN:
            merged_runs = []
            for i in range(0, len(runs), MAX_FANIN):
                group = runs[i:i + MAX_FANIN]
                if len(group) == 1:
                    merged_runs.append(group[0])
                    continue
                path = self._new_path()
                _write_run(self._merge(group), path)
                self.close()
                for old in group:
                    try:
                        os.remove(old)
                    except OSError:
                        pass
                merged_runs.append(path)
            runs = merged_runs
        return self._merge(runs)


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def writer_kwargs(args):
    kw = {"delimiter": ",", "quotechar": args.csv_quotechar}
    if args.csv_escapechar is not None:
        kw["doublequote"] = False
        kw["escapechar"] = args.csv_escapechar
    else:
        kw["doublequote"] = True
    kw["lineterminator"] = "\n"
    kw["quoting"] = csv.QUOTE_MINIMAL
    return kw


class OutputFile:
    """stdout, or a temporary file renamed over the target on success."""

    def __init__(self, target):
        self.target = target
        self.tmp = None
        if target == "-":
            self.fh = os.fdopen(os.dup(sys.stdout.fileno()), "w",
                                encoding="utf-8", newline="")
            return
        directory = os.path.dirname(os.path.abspath(target)) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, self.tmp = tempfile.mkstemp(prefix=".merge_files_", suffix=".tmp",
                                            dir=directory)
        except OSError as exc:
            raise usage_error("cannot write to %s: %s" % (target, exc))
        self.fh = os.fdopen(fd, "w", encoding="utf-8", newline="")

    def commit(self):
        self.fh.flush()
        if self.tmp is None:
            self.fh.close()
            return
        os.fsync(self.fh.fileno())
        self.fh.close()
        os.replace(self.tmp, self.target)
        self.tmp = None

    def abort(self):
        try:
            self.fh.close()
        except (OSError, ValueError):
            pass
        if self.tmp is not None:
            try:
                os.remove(self.tmp)
            except OSError:
                pass
            self.tmp = None


# --------------------------------------------------------------------------
# Partitioned output
# --------------------------------------------------------------------------

# Characters that survive a Hive-style path segment unescaped.
PART_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")

# Segment used when a partition column is null / missing for a row.
NULL_SEGMENT = "_null"

PART_NAME = "part-%05d.csv"


def encode_segment(value):
    """Percent-encode the UTF-8 bytes of *value* outside ``[A-Za-z0-9._-]``.

    Space becomes ``%20`` and ``/`` becomes ``%2F``, so a segment never escapes
    its own directory level.
    """
    out = []
    for byte in value.encode("utf-8"):
        ch = chr(byte)
        out.append(ch if ch in PART_SAFE else "%%%02X" % byte)
    return "".join(out)


class RowFormatter:
    """Renders a row to the exact CSV text that will land on disk."""

    def __init__(self, args):
        self._buf = io.StringIO()
        self._writer = csv.writer(self._buf, **writer_kwargs(args))

    def format(self, row):
        buf = self._buf
        buf.seek(0)
        buf.truncate(0)
        self._writer.writerow(row)
        return buf.getvalue()


class ShardWriter:
    """Sequentially numbered ``part-xxxxx.csv`` files inside one directory.

    A new file is started whenever appending the next row would break
    ``max_rows`` or ``max_bytes``; a row that cannot fit in an empty file is
    written on its own anyway, so no row is ever dropped or split.
    """

    def __init__(self, directory, header, max_rows, max_bytes):
        self.directory = directory
        self.header = header
        self.header_bytes = len(header.encode("utf-8"))
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.index = 0
        self.fh = None
        self.rows = 0
        self.size = 0

    def _open(self):
        path = os.path.join(self.directory, PART_NAME % self.index)
        self.index += 1
        self.fh = open(path, "w", encoding="utf-8", newline="")
        self.fh.write(self.header)
        self.rows = 0
        self.size = self.header_bytes

    def _must_cut(self, nbytes):
        if self.rows == 0:
            return False  # every file holds at least one row
        if self.max_rows is not None and self.rows + 1 > self.max_rows:
            return True
        if self.max_bytes is not None and self.size + nbytes > self.max_bytes:
            return True
        return False

    def start(self):
        """Make sure at least one (possibly header-only) file exists."""
        if self.fh is None:
            self._open()

    def write(self, text, nbytes):
        if self.fh is None:
            self._open()
        elif self._must_cut(nbytes):
            self.fh.close()
            self._open()
        self.fh.write(text)
        self.rows += 1
        self.size += nbytes

    def close(self):
        if self.fh is not None:
            self.fh.close()
            self.fh = None


class DirectoryOutput:
    """A partitioned output tree, staged in a sibling temp dir.

    Everything is written under ``<output>/../.merge_files_out_XXXX`` and only
    renamed onto ``--output`` once the whole run succeeded; ``abort`` removes
    the staging directory so a failed run leaves nothing partial behind.
    """

    def __init__(self, target, header, part_columns, max_rows, max_bytes):
        self.target = os.path.abspath(target)
        if os.path.lexists(self.target) and not os.path.isdir(self.target):
            raise usage_error(
                "--output %s exists and is not a directory" % target)
        self.parent = os.path.dirname(self.target) or "."
        try:
            os.makedirs(self.parent, exist_ok=True)
            self.tmp = tempfile.mkdtemp(prefix=".merge_files_out_", dir=self.parent)
        except OSError as exc:
            raise usage_error("cannot write to %s: %s" % (target, exc))
        self.header = header
        self.part_columns = [encode_segment(c) for c in part_columns]
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.current = None
        self.writer = None

    def _writer_for(self, segments):
        if self.writer is not None and segments == self.current:
            return self.writer
        if self.writer is not None:
            self.writer.close()
        directory = self.tmp
        if self.part_columns:
            for col, seg in zip(self.part_columns, segments):
                directory = os.path.join(directory, "%s=%s" % (col, seg))
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError as exc:
                raise usage_error("cannot create partition directory: %s" % exc)
        self.current = segments
        self.writer = ShardWriter(directory, self.header,
                                  self.max_rows, self.max_bytes)
        return self.writer

    def write_row(self, segments, text, nbytes):
        self._writer_for(segments).write(text, nbytes)

    def commit(self):
        if self.writer is not None:
            self.writer.close()
            self.writer = None
        elif not self.part_columns:
            # Nothing was emitted and there are no partition directories to
            # speak for the schema: still write the header-only first shard.
            self._writer_for(()).start()
            self.writer.close()
            self.writer = None
        tmp, self.tmp = self.tmp, None
        try:
            if not os.path.lexists(self.target):
                os.rename(tmp, self.target)
                return
            # Replace an existing output directory in two renames so the
            # target is never observed half written.
            backup = tempfile.mkdtemp(prefix=".merge_files_old_", dir=self.parent)
            os.rmdir(backup)
            os.rename(self.target, backup)
            try:
                os.rename(tmp, self.target)
            except OSError:
                os.rename(backup, self.target)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        except OSError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise usage_error("cannot write to %s: %s" % (self.target, exc))

    def abort(self):
        if self.writer is not None:
            try:
                self.writer.close()
            except OSError:
                pass
            self.writer = None
        if self.tmp is not None:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def one_char(value):
    if len(value) != 1:
        raise argparse.ArgumentTypeError("expected a single character, got %r" % value)
    return value


def positive_int(value):
    try:
        iv = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected an integer, got %r" % value)
    if iv <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer, got %r" % value)
    return iv


class Ctx:
    """Per-run state shared by the readers."""

    def __init__(self, args, tmpdir):
        self.args = args
        self.tmpdir = tmpdir
        self.null_literal = args.csv_null_literal
        limit = args.memory_limit_mb * 1024 * 1024
        self.budget = max(1024 * 1024, int(limit * 0.35))
        self.batch_cap = max(256, min(8192, args.memory_limit_mb * 64))
        self.batch_bytes = min(args.parquet_row_group_bytes, self.budget)


def build_parser():
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Merge CSV/TSV/JSONL/Parquet inputs into one sorted CSV.",
        epilog="exit codes: 0 ok, 2 usage, 3 schema/key, 4 cast, "
               "5 malformed input, 6 unsupported structure",
    )
    p.add_argument("--output", required=True, metavar="PATH|-",
                   help="output CSV path, or '-' for stdout; an output "
                        "directory when a partitioning flag is used")
    p.add_argument("--key", required=True, metavar="col[,col...]",
                   help="comma separated composite sort key")
    p.add_argument("--partition-by", metavar="col[,col...]",
                   help="write one Hive-style col=value directory tree per "
                        "distinct combination of these columns")
    p.add_argument("--max-rows-per-file", type=positive_int, metavar="INT",
                   help="cut output into part files of at most INT data rows")
    p.add_argument("--max-bytes-per-file", type=positive_int, metavar="INT",
                   help="cut output into part files of at most INT bytes on "
                        "disk, header included")
    p.add_argument("--desc", action="store_true",
                   help="sort descending (applies to all key columns)")
    p.add_argument("--schema", metavar="SCHEMA_JSON",
                   help="JSON file giving the exact output schema and column order")
    p.add_argument("--infer", choices=("strict", "loose"), default="strict",
                   help="type inference mode when --schema is not given (default: strict)")
    p.add_argument("--schema-strategy",
                   choices=("authoritative", "consensus", "union"),
                   default="authoritative",
                   help="how to reconcile conflicting column types: authoritative "
                        "prefers typed sources (parquet > jsonl > csv/tsv), consensus "
                        "takes the majority type, union widens to a common type "
                        "(default: authoritative)")
    p.add_argument("--on-type-error", choices=("coerce-null", "fail", "keep-string"),
                   default="coerce-null", help="behaviour on cast failure (default: coerce-null)")
    p.add_argument("--memory-limit-mb", type=positive_int, default=128, metavar="INT",
                   help="approximate in-memory budget before spilling to disk (default: 128)")
    p.add_argument("--temp-dir", metavar="PATH", help="directory for temporary spill files")
    p.add_argument("--csv-quotechar", type=one_char, default='"', metavar="CHAR")
    p.add_argument("--csv-escapechar", type=one_char, default=None, metavar="CHAR")
    p.add_argument("--csv-null-literal", default="", metavar="STRING",
                   help="text emitted for null/missing values (default: empty string)")
    p.add_argument("--input-format", choices=("auto", "csv", "tsv", "jsonl", "parquet"),
                   default="auto", help="force the input format (default: auto)")
    p.add_argument("--compression", choices=("auto", "none", "gzip"), default="auto",
                   help="force input compression (default: auto)")
    p.add_argument("--parquet-row-group-bytes", type=positive_int,
                   default=64 * 1024 * 1024, metavar="INT",
                   help="advisory parquet batch size in bytes (default: 67108864)")
    p.add_argument("inputs", nargs="*", metavar="INPUT")
    return p


def run(args):
    inputs = list(args.inputs)
    if not inputs:
        raise usage_error("no input files given")

    keys = [k.strip() for k in args.key.split(",")]
    if not keys or any(k == "" for k in keys):
        raise usage_error("--key must be a comma separated list of column names")

    part_cols = []
    if args.partition_by is not None:
        part_cols = [c.strip() for c in args.partition_by.split(",")]
        if not part_cols or any(c == "" for c in part_cols):
            raise usage_error(
                "--partition-by must be a comma separated list of column names")

    partitioned = bool(part_cols) or args.max_rows_per_file is not None \
        or args.max_bytes_per_file is not None
    if partitioned and args.output == "-":
        raise usage_error(
            "--output must be a directory path (not '-') when --partition-by, "
            "--max-rows-per-file or --max-bytes-per-file is used")

    tmpdir = None
    sources = []
    sorter = None
    out = None
    try:
        base_tmp = args.temp_dir
        if base_tmp:
            try:
                os.makedirs(base_tmp, exist_ok=True)
            except OSError as exc:
                raise usage_error("cannot create --temp-dir %s: %s" % (base_tmp, exc))
        tmpdir = tempfile.mkdtemp(prefix="merge_files_", dir=base_tmp)
        ctx = Ctx(args, tmpdir)

        sources = [make_source(path, ctx) for path in inputs]

        if args.schema:
            columns = load_schema(args.schema)
        else:
            columns = infer_schema(sources, ctx)
        if not columns:
            raise schema_error("no columns could be resolved from the inputs")

        names = [c[0] for c in columns]
        name_index = {}
        for i, n in enumerate(names):
            name_index.setdefault(n, i)
        missing = [k for k in keys if k not in name_index]
        if missing:
            raise schema_error(
                "key column(s) not present in resolved schema: %s" % ", ".join(missing))
        key_positions = [name_index[k] for k in keys]
        missing = [c for c in part_cols if c not in name_index]
        if missing:
            raise schema_error(
                "partition column(s) not present in resolved schema: %s"
                % ", ".join(missing))
        part_positions = [name_index[c] for c in part_cols]

        records = iter_records(sources, columns, key_positions, part_positions, ctx)
        sorter = _Sorter(args.desc, ctx.budget, tmpdir)
        merged = sorter.sort(records)

        fmt = RowFormatter(args)
        header = fmt.format(names)

        if not partitioned:
            out = OutputFile(args.output)
            out.fh.write(header)
            for rec in merged:
                out.fh.write(fmt.format(rec[2]))
            out.commit()
            out = None
        else:
            npart = len(part_positions)
            out = DirectoryOutput(args.output, header, part_cols,
                                  args.max_rows_per_file, args.max_bytes_per_file)
            for rec in merged:
                text = fmt.format(rec[2])
                out.write_row(tuple(rec[0][:npart]), text,
                              len(text.encode("utf-8")))
            out.commit()
            out = None
    finally:
        if sorter is not None:
            sorter.close()
        for src in sources:
            try:
                src.close()
            except Exception:
                pass
        if out is not None:
            out.abort()
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return EXIT_OK


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        csv.field_size_limit(2 ** 27)
    except (OverflowError, ValueError):
        pass
    try:
        return run(args)
    except AppError as exc:
        sys.stderr.write("%s: error: %s\n" % (PROG, exc))
        return exc.code
    except BrokenPipeError:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return EXIT_INTERNAL
    except KeyboardInterrupt:
        sys.stderr.write("%s: interrupted\n" % PROG)
        return 130
    except RecursionError as exc:
        sys.stderr.write("%s: error: %s\n" % (PROG, exc))
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
