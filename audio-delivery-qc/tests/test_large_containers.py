import struct
from audio_qc.bwf import inspect_bwf
from audio_qc.synthetic import chunk


def test_sparse_rf64_over_four_gib_and_bext_after_audio(tmp_path):
    """Sparse fixture exercises 64-bit seeks without allocating/reading 4 GiB."""
    path = tmp_path/"large.rf64"
    data_size = 2**32 + 2  # divisible by a 24-bit mono frame
    fmt = chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 48000, 144000, 3, 24))
    bext = bytearray(602)
    struct.pack_into("<Q", bext, 338, 2**40)
    bext = chunk(b"bext", bytes(bext))
    size = 12+36+len(fmt)+8+data_size+len(bext)
    with path.open("xb") as f:
        f.write(b"RF64\xff\xff\xff\xffWAVE")
        f.write(chunk(b"ds64", struct.pack("<QQQI", size-8, data_size, data_size//3, 0)))
        f.write(fmt)
        f.write(b"data\xff\xff\xff\xff")
        f.seek(data_size, 1)
        f.write(bext)
    result = inspect_bwf(path)
    assert result["data_bytes"] == data_size
    assert result["time_reference"] == 2**40
    assert result["declared_sample_frames"] == data_size//3
    assert not result["errors"]
