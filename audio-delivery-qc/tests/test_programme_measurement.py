from copy import deepcopy
from pathlib import Path
import pytest
from test_programme import audio, build


def eligible_setup(tmp_path, origins=(172800000,172800000), mode='auto'):
    files = [audio(tmp_path, role, origin=origin) for role,origin in zip(('L','R'),origins)]
    group, = build(files)
    group['requested_alignment'] = mode
    signatures = {a.path: (Path(a.path).stat().st_size,Path(a.path).stat().st_mtime_ns,Path(a.path).stat().st_ino) for a in files}
    return group,files,signatures


@pytest.mark.parametrize('origins,mode,want', [((0,0),'auto',True),((2**60,2**60),'auto',True),
 ((None,None),'auto',False),((None,None),'common_file_start',True),
 ((0,1),'common_file_start',False)])
def test_eligibility_timing_and_immutability(tmp_path, origins, mode, want):
    from audio_qc.programme_measurement import programme_eligibility
    args = eligible_setup(tmp_path, origins, mode)
    before=deepcopy(args)
    assert programme_eligibility(*args).eligible is want
    assert args == before


@pytest.mark.parametrize('change', ['nonfinite','samples','rate','count','missing','signature'])
def test_ineligible_facts(tmp_path, change):
    from audio_qc.programme_measurement import programme_eligibility
    from audio_qc.models import MeasurementOutcome, MeasurementState
    group,files,sigs=eligible_setup(tmp_path)
    if change=='nonfinite': files[0].measurements['nonfinite_samples']=1
    if change=='samples': files[0].measurement_outcomes['samples']=MeasurementOutcome(MeasurementState.ERROR)
    if change=='rate': files[0].sample_rate=44100
    if change=='count': files[0].measurements['decoded_sample_frames']+=1
    if change=='missing': files.pop()
    if change=='signature': sigs.clear()
    assert not programme_eligibility(group,files,sigs).eligible


def test_source_changed_between_passes(tmp_path):
    from audio_qc.programme_measurement import programme_eligibility, verify_programme_sources
    from audio_qc.process import ToolError
    group,files,sigs=eligible_setup(tmp_path)
    result=programme_eligibility(group,files,sigs)
    Path(files[0].path).write_bytes(b'changed')
    with pytest.raises(ToolError,match='Source changed'):
        verify_programme_sources(result.input)


def test_bwf_read_failure_is_not_missing_bwf(tmp_path):
    from audio_qc.programme_measurement import programme_eligibility
    group,files,sigs=eligible_setup(tmp_path,(None,None),'common_file_start')
    files[0].operational('bwf_unavailable','permission denied',required=True,affects_analysis=True)
    assert not programme_eligibility(group,files,sigs).eligible
