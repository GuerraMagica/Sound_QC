from copy import deepcopy
import pytest
from audio_qc import rules
from audio_qc.config import load_config
from audio_qc.models import AudioFile, MeasurementOutcome, MeasurementState as MS, Status
from audio_qc.programme_measurement import ProgrammeMeasurement


def measured():
    return AudioFile('mono.wav','mono.wav',channels=1,sample_rate=48000,
                     measurements={'integrated_lufs':-40.,'true_peak_dbtp':-4.},
                     measurement_outcomes={k:MeasurementOutcome(MS.SUCCESS) for k in ('integrated_lufs','true_peak_dbtp')})


def test_programme_target_evaluated_once_and_inputs_not_mutated():
    a=measured(); before=deepcopy(a); c=load_config(preset='BROADCAST_EBU_R128')
    file=rules.assess_file(a,c,level_scope='PROGRAMME_MEMBER')
    assert not any(x.code in ('integrated_loudness','true_peak') and x.status==Status.FAIL for x in file.checks)
    result=ProgrammeMeasurement('SUCCESS',measurements=a.measurements,measurement_outcomes=a.measurement_outcomes)
    checks=rules.assess_programme(result,c)
    assert sum(x.code=='integrated_loudness' and x.status==Status.FAIL for x in checks)==1
    assert a==before
    assert any(x.status==Status.FAIL for x in rules.assess_file(a,c).checks)


@pytest.mark.parametrize('state,want',[('NOT_EVALUATED',Status.INCOMPLETE),('ERROR',Status.INCOMPLETE),('DISABLED',Status.INFO)])
def test_impossible_and_disabled(state,want):
    checks=rules.assess_programme(ProgrammeMeasurement(state),load_config(preset='BROADCAST_EBU_R128'))
    assert checks[0].status==want


def test_scope_cannot_silently_disable_levels():
    with pytest.raises(ValueError): rules.assess_file(measured(),load_config(),level_scope='TYPO')


@pytest.mark.integration
def test_mono_error_optional_only_for_declared_member(tmp_path,monkeypatch):
    from audio_qc.scanner import inspect_file
    from audio_qc.synthetic import sine,write_wav
    from audio_qc.process import ToolError
    import audio_qc.scanner as scanner
    path=write_wav(tmp_path/'mono.wav',sine(),bext=True)
    def failed(*args,**kwargs): raise ToolError('controlled mono EBU failure')
    monkeypatch.setattr(scanner,'measure_loudness',failed)
    c=load_config(preset='BROADCAST_EBU_R128')
    physical=inspect_file(path,c)
    member=inspect_file(path,c,level_scope='PROGRAMME_MEMBER')
    assert physical.status==Status.INCOMPLETE
    assert member.status!=Status.INCOMPLETE
    assert member.measurement_outcomes['integrated_lufs'].state==MS.ERROR
    assert any(d.code=='integrated_lufs' and not d.required for d in member.operational_diagnostics)
    assert physical.measurements==member.measurements


def test_failed_integrated_retains_true_peak_noncompliance():
    result=ProgrammeMeasurement('ERROR',measurements={'integrated_lufs':None,'true_peak_dbtp':0.},
        measurement_outcomes={'integrated_lufs':MeasurementOutcome(MS.ERROR,'bad I'),
                              'true_peak_dbtp':MeasurementOutcome(MS.SUCCESS)})
    checks=rules.assess_programme(result,load_config(preset='BROADCAST_EBU_R128'))
    assert any(c.code=='integrated_loudness' and c.status==Status.INCOMPLETE for c in checks)
    assert any(c.code=='true_peak' and c.status==Status.FAIL for c in checks)
