from pathlib import Path
from dataclasses import replace
import subprocess
import numpy as np
import pytest
from audio_qc.config import load_config
from audio_qc.rules import measurement_requirements
from audio_qc.scanner import inspect_file
from audio_qc.loudness import measure_loudness
from audio_qc.models import MeasurementState as MS
from m6_fixtures import make_programme_fixture


def virtual_input(fixture, layout):
    from audio_qc.programme_measurement import ProgrammeInput, source_signature
    return ProgrammeInput('test', layout, tuple(fixture['members'].items()), 48000,
                          fixture['sample_count'], 'bwf_time_reference',
                          {str(p): source_signature(p) for p in fixture['members'].values()})


@pytest.mark.integration
@pytest.mark.parametrize('layout,case', [('stereo','asymmetric'),('5.1','asymmetric'),('5.1','lfe'),
                                        ('5.1','lfe_peak'),('stereo','silence'),('stereo','below_gate')])
def test_virtual_metrics_and_pcm(tmp_path, layout, case):
    from audio_qc.programme_measurement import measure_programme, virtual_input_args
    fixture = make_programme_fixture(tmp_path, layout=layout, case=case)
    inputs=virtual_input(fixture,layout)
    config=load_config(preset='BROADCAST_EBU_R128')
    reference=inspect_file(fixture['reference'],config)
    result=measure_programme(inputs,measurement_requirements(config))
    assert result.state=='SUCCESS'
    for metric,limit in [('integrated_lufs',.1),('lra_lu',.1),('true_peak_dbtp',.1)]:
        expected=reference.measurements.get(metric)
        actual=result.measurements.get(metric)
        assert result.measurement_outcomes[metric].state==reference.measurement_outcomes[metric].state
        if expected is None: assert actual is None
        else: assert actual==pytest.approx(expected,abs=limit)
    assert result.measurements['decoded_sample_frames']==fixture['sample_count']
    if case=='lfe':
        assert result.measurement_outcomes['integrated_lufs'].state==MS.UNAVAILABLE
        assert result.measurements['true_peak_dbtp']==pytest.approx(-.4,abs=.1)
    args,graph=virtual_input_args(replace(inputs,ordered_members=tuple(reversed(inputs.ordered_members))))
    raw=subprocess.check_output(args+['-filter_complex',graph+'[out]','-map','[out]',
                                     '-c:a','pcm_f64le','-f','f64le','-'],stderr=subprocess.DEVNULL)
    actual=np.frombuffer(raw,'<f8').reshape(-1,len(fixture['members']))
    for i,expected in enumerate(fixture['pcm_by_role'].values()):
        np.testing.assert_array_equal(actual[:,i],expected)


@pytest.mark.integration
@pytest.mark.parametrize('mode',['failure','timeout','missing','short','changed'])
def test_virtual_failure_is_not_unavailable(tmp_path, monkeypatch, mode):
    import audio_qc.programme_measurement as pm
    from audio_qc.process import ToolError
    fixture=make_programme_fixture(tmp_path,layout='stereo',seconds=1)
    inputs=virtual_input(fixture,'stereo')
    if mode in ('failure','timeout'):
        def failed(*a,**kw): raise ToolError('timeout' if mode=='timeout' else 'FFmpeg failed')
        monkeypatch.setattr(pm,'run_loudness',failed)
    elif mode=='missing':
        monkeypatch.setattr(pm,'run_loudness',lambda *a,**kw: {})
    elif mode=='short':
        inputs=replace(inputs,sample_count=48001)
    else:
        Path(inputs.ordered_members[0][1]).write_bytes(b'changed')
    result=pm.measure_programme(inputs,measurement_requirements(load_config(preset='BROADCAST_EBU_R128')))
    assert result.state=='ERROR'
    assert any(d.required for d in result.operational_diagnostics)
    assert result.measurement_outcomes['integrated_lufs'].state==MS.ERROR


@pytest.mark.integration
@pytest.mark.parametrize('seconds', [.00002,.399,.401,1.023,1.025])
def test_tail_frames_are_never_padded_or_lost(tmp_path,seconds):
    from audio_qc.programme_measurement import virtual_input_args
    f=make_programme_fixture(tmp_path,layout='5.1',seconds=seconds)
    args,graph=virtual_input_args(virtual_input(f,'5.1'))
    for _ in range(3):
        raw=subprocess.check_output(args+['-filter_complex',graph+'[out]','-map','[out]',
                                          '-c:a','pcm_f64le','-f','f64le','-'],stderr=subprocess.DEVNULL)
        actual=np.frombuffer(raw,'<f8').reshape(-1,6)
        np.testing.assert_array_equal(actual,np.column_stack(list(f['pcm_by_role'].values())))


@pytest.mark.integration
def test_mixed_pcm_formats_preserve_values_and_roles(tmp_path):
    from audio_qc.programme_measurement import virtual_input_args, ProgrammeInput, source_signature
    from audio_qc.synthetic import write_wav
    from audio_qc.programme import LAYOUTS
    roles=('L','R','C','LFE','Ls','Rs');members=[];expected=[]
    for i,role in enumerate(roles):
        values=np.array([0.,2**-23,-.125,(i+1)/16]*1031)
        bits=16 if i==0 else 32 if i==2 else 24
        if i==0: values=np.rint(values*2**15)/2**15
        p=write_wav(tmp_path/f'{role}.wav',values,bits=bits,float_pcm=i==2)
        expected.append(values);members.append((role,p))
    inputs=ProgrammeInput('mixed','5.1',tuple(reversed(members)),48000,len(values),'common_file_start',
                          {str(p):source_signature(p) for _,p in members})
    args,graph=virtual_input_args(inputs)
    raw=subprocess.check_output(args+['-filter_complex',graph+'[out]','-map','[out]',
                                      '-c:a','pcm_f64le','-f','f64le','-'],stderr=subprocess.DEVNULL)
    np.testing.assert_array_equal(np.frombuffer(raw,'<f8').reshape(-1,6),np.column_stack(expected))


@pytest.mark.integration
def test_source_change_during_pass_invalidates_measurement(tmp_path,monkeypatch):
    import audio_qc.programme_measurement as pm
    f=make_programme_fixture(tmp_path,layout='stereo',seconds=1)
    inputs=virtual_input(f,'stereo');original=pm.run_loudness
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        inputs.ordered_members[0][1].touch()
        return result
    monkeypatch.setattr(pm,'run_loudness',changed)
    result=pm.measure_programme(inputs,measurement_requirements(load_config()))
    assert result.state=='ERROR'
    assert result.measurements['integrated_lufs'] is None


@pytest.mark.integration
def test_cancel_during_real_virtual_pass_reaps_ffmpeg(tmp_path,monkeypatch):
    import os
    from audio_qc.programme_measurement import measure_programme
    from audio_qc.process import CancellationToken, ScanCancelled
    f=make_programme_fixture(tmp_path,layout='5.1',seconds=15)
    token=CancellationToken();seen=[]
    import audio_qc.process as process
    original=process.subprocess.Popen
    def track(*args,**kwargs):
        child=original(*args,**kwargs)
        seen.append(child)
        return child
    monkeypatch.setattr(process.subprocess,'Popen',track)
    def cancel_on_progress(fraction):
        token.cancel()
    with pytest.raises(ScanCancelled):
        measure_programme(virtual_input(f,'5.1'),measurement_requirements(load_config()),cancel_on_progress,cancel=token)
    assert seen
    for child in seen:
        assert child.poll() is not None
        with pytest.raises(ProcessLookupError): os.kill(child.pid,0)
