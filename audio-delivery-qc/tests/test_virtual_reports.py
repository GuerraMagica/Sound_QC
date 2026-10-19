import json
from dataclasses import asdict
from copy import deepcopy
import pytest
from test_programme import audio,build,event
from audio_qc.models import Status
from audio_qc.reports import build_report,write_reports


def test_successful_levels_never_hide_capped_defect_coverage(tmp_path,config):
    files=[audio(tmp_path,role) for role in ('L','R')]
    for a in files:
        a.defects=[event()]
        a.add('defects_capped',Status.WARNING,'coverage incomplete')
    groups=build(files)
    group=groups[0]
    group.update(programme_compliance='PASS',level_checks=[],programme_measurement={
        'state':'SUCCESS','method':'virtual_multichannel','measurements':{'integrated_lufs':-23},
        'operational_diagnostics':[]})
    before=deepcopy((files,groups))
    report=build_report(tmp_path,files,[],config,{},0,programme_groups=groups)
    write_reports(report,tmp_path)
    assert (files,groups)==before
    saved=json.loads((tmp_path/'QC_REPORT.json').read_text())
    assert saved['programme_groups'][0]['defect_coverage']=='INCOMPLETE'
    assert saved['programme_groups'][0]['programme_compliance']=='PASS'
    html=(tmp_path/'QC_REPORT.html').read_text()
    assert 'These retained results do not represent full defect coverage' in html
    assert 'Programme compliance: PASS' in html


@pytest.mark.integration
def test_cancel_evidence_keeps_finished_measurements(tmp_path,monkeypatch):
    import audio_qc.cli as cli
    from audio_qc.synthetic import sine,write_wav
    from audio_qc.process import ScanCancelled
    source=write_wav(tmp_path/'test.wav',sine(),bext=True)
    def cancel(*args,**kwargs): raise ScanCancelled()
    monkeypatch.setattr(cli,'export_snippets',cancel)
    output=tmp_path/'report'
    assert cli.main(['inspect',str(source),'--export-defect-snippets','--output',str(output)])==130
    assert not (output/'QC_COMPLETE.json').exists()
    saved=json.loads((output/'QC_RECOVERY.json').read_text())
    assert saved['files'][0]['measurements']['decoded_sample_frames']==192000


@pytest.mark.integration
@pytest.mark.parametrize('failure',[False,True])
def test_cancel_during_report_keeps_programme_measurements(tmp_path,monkeypatch,failure):
    import audio_qc.cli as cli
    import audio_qc.reports as reports
    from audio_qc.process import CancellationToken,ScanCancelled
    from m6_fixtures import make_programme_fixture
    f=make_programme_fixture(tmp_path/'fixture',layout='stereo',seconds=4)
    token=CancellationToken();original=cli.write_reports
    def interrupted(report,directory,**kwargs):
        token.cancel()
        if failure: raise OSError('concurrent disk failure')
        raise ScanCancelled()
    monkeypatch.setattr(cli,'write_reports',interrupted)
    monkeypatch.setattr(cli,'CancellationToken',lambda:token)
    # Supply a closed, local control pipe; the token is cancelled by report injection.
    import os
    read_fd,write_fd=os.pipe();os.close(write_fd)
    with os.fdopen(read_fd) as control:
        monkeypatch.setattr(cli.sys,'stdin',control)
        out=tmp_path/'report'
        code=cli.main(['inspect',str(tmp_path/'fixture'/'sources'),'--groups',str(f['manifest']),
                       '--gui-control-stdin','--no-defects','--output',str(out)])
    assert code==130
    recovery=json.loads((out/'QC_RECOVERY.json').read_text())
    assert recovery['compliance_scope']=='PHYSICAL_FILES_AND_PROGRAMME_LEVELS'
    assert recovery['programme_groups'][0]['programme_measurement']['state']=='SUCCESS'
    assert recovery['programme_groups'][0]['programme_measurement']['measurements']['decoded_sample_frames']==192000
    assert not (out/'QC_COMPLETE.json').exists()
    if failure:
        assert any('concurrent disk failure' in d['message'] for d in recovery['operational_diagnostics'])


@pytest.mark.integration
def test_cancel_mid_programmes_keeps_completed_and_marks_pending(tmp_path,monkeypatch):
    import audio_qc.cli as cli
    from audio_qc.process import ScanCancelled
    from m6_fixtures import make_programme_fixture
    make_programme_fixture(tmp_path/'fixtures'/'one',layout='stereo',seconds=1)
    make_programme_fixture(tmp_path/'fixtures'/'two',layout='stereo',seconds=1)
    original=cli.measure_programme;calls=[]
    def cancel_second(*args,**kwargs):
        calls.append(args[0].group_id)
        if len(calls)==2: raise ScanCancelled()
        return original(*args,**kwargs)
    monkeypatch.setattr(cli,'measure_programme',cancel_second)
    output=tmp_path/'report'
    assert cli.main(['inspect',str(tmp_path/'fixtures'),'--detect-groups','--no-defects','--output',str(output)])==130
    report=json.loads((output/'QC_RECOVERY.json').read_text())
    assert [g['programme_measurement']['state'] for g in report['programme_groups']]==['SUCCESS','NOT_EVALUATED']
    assert report['programme_group_configuration'] is not None
    assert report['audio_compliance']=='INCOMPLETE'
    assert report['programme_groups'][0]['programme_measurement']['measurements']['decoded_sample_frames']==48000
