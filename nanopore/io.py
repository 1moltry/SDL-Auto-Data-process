"""ABF file reading.

pyabf refuses float ABF1 files ("Support for float data is not implemented");
those are exactly what pCLAMP ships in `Sample Data/` (kchann, singles, etc.),
so float-ABF1 files are read by our own minimal reader and everything else is
deferred to pyabf. We sniff the file signature ourselves rather than relying on
pyabf's exception text, so a float file is dispatched correctly no matter what
pyabf raises, and corrupt/unsupported files get an explicit diagnostic.

Returns the current channel as a 1-D float array in the recording unit plus
metadata.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# ABF1 header byte layout (Axon ABFHEADR.H, 1-byte packed). Offsets match pyabf's
# HeaderV1 and were cross-checked against pCLAMP Sample Data.
_ABF1_OPS = {
    1: "variable-length events",
    2: "fixed-length events",
    3: "gap-free",
    4: "high-speed oscilloscope",
    5: "waveform",
}

_ADC_COUNT = 16


def _abf1_int(h: bytes, off: int) -> int:
    return struct.unpack_from("<h", h, off)[0]


def _abf1_long(h: bytes, off: int) -> int:
    return struct.unpack_from("<i", h, off)[0]


def _abf1_float(h: bytes, off: int) -> float:
    return struct.unpack_from("<f", h, off)[0]


def _abf1_str(h: bytes, off: int, width: int) -> str:
    return h[off:off + width].split(b"\0", 1)[0].decode("latin-1", "replace").strip()


def _clean(s: str) -> str:
    """Strip NUL padding pyabf leaves on fixed-width ABF1 header strings."""
    return s.split("\0", 1)[0].strip() if s else s


def _is_voltage_unit(u: str) -> bool:
    """A channel whose unit denotes a command/membrane voltage (mV / V)."""
    lu = u.lower()
    return "mv" in lu or lu in {"v", "volt", "voltage"}


@dataclass
class AbfRecording:
    path: Path
    current: np.ndarray      # recording unit, first (or requested) current channel
    sample_rate_hz: float
    units: str
    n_channels: int
    sweep_count: int
    channel_names: list[str] | None = None
    channel_units: list[str] | None = None
    operation_mode: str | None = None
    data: np.ndarray | None = None      # (n, n_channels) raw-ish per-channel data
    current_channel: int = 0
    voltage: np.ndarray | None = None   # recorded voltage ADC trace, same length as current
    voltage_channel: int | None = None
    command_voltage: np.ndarray | None = None  # commanded protocol waveform (mV), same length
                                               # as current — present even when no voltage ADC
                                               # channel was recorded (tPAL-style files)

    @property
    def dt_s(self) -> float:
        return 1.0 / self.sample_rate_hz

    @property
    def protocol_voltage(self) -> np.ndarray | None:
        """Best available voltage trace for protocol-segment detection: the
        recorded voltage ADC when present, else the commanded protocol waveform."""
        return self.voltage if self.voltage is not None else self.command_voltage

    @property
    def duration_s(self) -> float:
        return len(self.current) / self.sample_rate_hz

    def _auto_channel(self, predicate, default: int | None) -> int | None:
        chans = self.channel_units or []
        for i, u in enumerate(chans):
            if predicate(u):
                return i
        return default


def _sniff_kind(path: Path) -> str:
    """Classify an ABF file from its header: 'abf2', 'abf1_int', 'abf1_float'."""
    with open(path, "rb") as f:
        head = f.read(2048)
    if head[0:4] == b"ABF2":
        return "abf2"
    if head[0:4] != b"ABF ":
        raise ValueError(f"not an ABF file: {path.name!r} has signature {head[0:4]!r}")
    fmt = _abf1_int(head, 100)  # nDataFormat is at file byte 100
    return "abf1_float" if fmt == 1 else "abf1_int"


def read_abf(path: str | Path, channel: int = 0) -> AbfRecording:
    path = Path(path)
    kind = _sniff_kind(path)

    if kind == "abf1_float":
        return _read_abf1_float(path, channel=channel)

    import pyabf

    abf = pyabf.ABF(str(path))
    names = [_clean(str(n)) for n in (getattr(abf, "adcNames", []) or [])]
    ch_units = [_clean(str(u)) for u in (getattr(abf, "adcUnits", []) or [])]
    nch = abf.channelCount
    # channel Y data from a sweep is only for the channel selected by setSweep;
    # build the full per-channel matrix so voltage can be recovered alongside current.
    sweeps = []
    data_cols: list[np.ndarray] = []
    for s in range(abf.sweepCount):
        abf.setSweep(s, channel=channel)
        sweeps.append(np.asarray(abf.sweepY, dtype=np.float64))
        if nch > 1:
            row = np.empty((abf.sweepY.size, nch), dtype=np.float64)
            for c in range(nch):
                abf.setSweep(s, channel=c)
                row[:, c] = abf.sweepY
            data_cols.append(row)
    current = sweeps[0] if len(sweeps) == 1 else np.concatenate(sweeps)
    data = np.concatenate(data_cols, axis=0) if data_cols else None
    cur_unit = ch_units[channel] if channel < len(ch_units) else str(getattr(abf, "sweepUnitsY", "pA"))
    # pick a voltage channel (mV/V) different from the current channel
    vch = None
    voltage = None
    if data is not None and ch_units:
        for c, u in enumerate(ch_units):
            if c != channel and _is_voltage_unit(u):
                vch = c
                voltage = data[:, c].astype(np.float64, copy=False)
                break
    # commanded protocol waveform (mV) from the header DAC/epoch table: available
    # even when no voltage ADC channel was recorded (tPAL-style files), so the
    # anomaly stage can still find protocol segments (reverse-voltage / wash).
    command_voltage = _command_waveform(abf)
    return AbfRecording(
        path=path,
        current=current,
        sample_rate_hz=float(abf.dataRate),
        units=cur_unit,
        n_channels=nch,
        sweep_count=abf.sweepCount,
        channel_names=names or None,
        channel_units=ch_units or None,
        operation_mode=_ABF1_OPS.get(int(getattr(abf, "nOperationMode", 0)), "mode " + str(getattr(abf, "nOperationMode", ""))),
        data=data,
        current_channel=channel,
        voltage=voltage,
        voltage_channel=vch,
        command_voltage=command_voltage,
    )


def _command_waveform(abf) -> np.ndarray | None:
    """Concatenate the commanded protocol waveform (mV) across sweeps.

    pyabf exposes ``sweepC`` from the header's DAC/epoch table. Returns None
    when the table is empty (no protocol) or cannot be read.
    """
    try:
        if not getattr(abf, "dacNames", None):
            return None
        parts = []
        for s in range(abf.sweepCount):
            abf.setSweep(s, channel=0)
            c = np.asarray(abf.sweepC, dtype=np.float64)
            parts.append(c)
        if not parts:
            return None
        return np.concatenate(parts)
    except Exception:
        return None


def _read_abf1_float(path: Path, channel: int = 0) -> AbfRecording:
    """Read an ABF1 float32 (nDataFormat==1) file.

    Float ABF1 data are already scaled to the recording unit (pA for current
    channels) when written; the instrument/signal/programmable-gain fields are
    informational only and must NOT be applied (verified against pyabf's int
    ABF1 path, which scales ints by those gains into real units).
    """
    with open(path, "rb") as f:
        head = f.read(2048)
        if head[0:4] != b"ABF ":
            raise ValueError(f"not ABF1: signature {head[0:4]!r}")
        fmt = _abf1_int(head, 100)
        if fmt != 1:
            raise ValueError(f"expected nDataFormat=1 (float), got {fmt}")
        nch = _abf1_int(head, 120)
        if nch < 1:
            raise ValueError(f"invalid nADCNumChannels={nch}")
        interval_us = _abf1_float(head, 122)
        if not (interval_us > 0) or interval_us > 1e9:
            raise ValueError(f"invalid fADCSampleInterval={interval_us} µs")
        episodes = _abf1_long(head, 16)
        n_ignored = _abf1_int(head, 14)
        acq_len = _abf1_long(head, 10)
        data_ptr_blocks = _abf1_long(head, 40)
        op_mode = _abf1_int(head, 8)

        # multi-channel metadata
        names = [_abf1_str(head, 442 + i * 10, 10) for i in range(_ADC_COUNT)]
        units = [_abf1_str(head, 602 + i * 8, 8) for i in range(_ADC_COUNT)]
        sampling_seq = list(struct.unpack_from("<16h", head, 410))

        data_start = data_ptr_blocks * 512 + n_ignored
        f.seek(data_start)
        file_len = _file_size(path)
        avail = max(0, (file_len - data_start) // 4)
        if acq_len > avail:
            raise ValueError(
                f"{path.name}: header declares {acq_len} samples but file only has "
                f"{avail} (data start @{data_start}, {file_len} bytes total); corrupt or truncated"
            )
        raw = np.fromfile(f, dtype="<f4", count=acq_len)
        if raw.size < acq_len:
            raise ValueError(f"{path.name}: truncated data ({raw.size}/{acq_len} samples)")

    ch = int(channel)
    if ch >= nch:
        raise ValueError(f"channel {ch} out of range (file has {nch} channel(s))")

    matrix = raw.reshape(-1, nch) if nch > 1 else raw.reshape(-1, 1)
    current = matrix[:, ch]
    logical_units = _logical_units(units, sampling_seq, nch)
    vch = None
    voltage = None
    if nch > 1:
        for c in range(nch):
            if c != ch and _is_voltage_unit(logical_units[c]):
                vch = c
                voltage = matrix[:, c]
                break

    sr = 1e6 / (interval_us * nch)
    return AbfRecording(
        path=path,
        current=current.astype(np.float64, copy=False),
        sample_rate_hz=float(sr),
        units=logical_units[ch] if logical_units else _abf1_unit_for(units, sampling_seq, ch),
        n_channels=int(nch),
        sweep_count=int(episodes),
        channel_names=_logical_names(names, sampling_seq, nch),
        channel_units=logical_units,
        operation_mode=_ABF1_OPS.get(op_mode, f"mode {op_mode}"),
        data=matrix.astype(np.float64, copy=False),
        current_channel=ch,
        voltage=voltage.astype(np.float64, copy=False) if voltage is not None else None,
        voltage_channel=vch,
    )


def _file_size(path: Path) -> int:
    return path.stat().st_size


def _phys_for(seq: list[int], ch: int) -> int:
    """Physical ADC sampled at mux position ch (pyabf: nADCSamplingSeq[ch])."""
    if 0 <= ch < len(seq) and 0 <= seq[ch] < _ADC_COUNT:
        return seq[ch]
    return ch


def _logical_names(names: list[str], seq: list[int], nch: int) -> list[str]:
    return [names[_phys_for(seq, i)] for i in range(nch)]


def _logical_units(units: list[str], seq: list[int], nch: int) -> list[str]:
    return [units[_phys_for(seq, i)] for i in range(nch)]


def _abf1_unit_for(units: list[str], seq: list[int], ch: int) -> str:
    return units[_phys_for(seq, ch)]
