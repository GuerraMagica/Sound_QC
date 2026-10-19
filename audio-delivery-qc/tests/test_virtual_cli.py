import json
from copy import deepcopy
import pytest
from audio_qc.cli import main
from audio_qc.config import load_config, save_config
from m6_fixtures import make_programme_fixture


@pytest.mark.integration
@pytest.mark.parametrize('scenario,exit_code,scope,state',[
 ('pass',0,'PASS','SUCCESS'),('fail',1,'FAIL','SUCCESS'),('disabled',0,'NOT_EVALUATED','DISABLED'),
 ('invalid',2,'NOT_EVALUATED','NOT_EVALUATED'),('engine_error',2,'INCOMPLETE','ERROR')])
def test_cli_scopes_and_exit_codes(tmp_path,monkeypatch,scenario,exit_code,scope,state):
    import audio_qc.programme_measurement as pm
    from audio_qc.process import ToolError
    from audio_qc.programme_measurement import source_signature
    f=make_programme_fixture(tmp_path/'fixture',layout='stereo',seconds=4)
    before={str(p):source_signature(p) for p in f['members'].values()}
    c=load_config(preset='CUSTOM');c['loudness'].update(enabled=True,target_lufs=-24,tolerance=20)
    c['defects']['enabled']=False
    if scenario=='fail': c['loudness'].update(target_lufs=0,tolerance=.1)
    if scenario=='disabled': c['loudness'].update(enabled=False,target_lufs=None,tolerance=None)
    if scenario=='invalid':
        # Keep missing physical source as an invalid declared group.
        f['members']['R'].unlink();before.pop(str(f['members']['R']))
    if scenario=='engine_error':
        def fail(*a,**kw): raise ToolError('controlled FFmpeg failure')
        monkeypatch.setattr(pm,'run_loudness',fail)
    cfg=tmp_path/'custom.yaml';save_config(cfg,c)
    output=tmp_path/'report'
    code=main(['inspect',str(tmp_path/'fixture'/'sources'),'--groups',str(f['manifest']),
               '--config',str(cfg),'--no-defects','--output',str(output)])
    assert code==exit_code
    r=json.loads((output/'QC_REPORT.json').read_text());g=r['programme_groups'][0]
    assert r['schema_version']==5
    assert g['programme_measurement']['state']==state
    assert g['programme_compliance']==scope
    assert r['compliance_scope']=='PHYSICAL_FILES_AND_PROGRAMME_LEVELS'
    assert not any(check['code']=='integrated_loudness' for a in r['files'] for check in a['checks'])
    assert before=={p:source_signature(p) for p in before}
    assert (output/'QC_COMPLETE.json').exists()
    html=(output/'QC_REPORT.html').read_text()
    assert 'Programme compliance: '+scope in html
    assert 'Not measured in M5.' not in html
    assert g['defect_coverage']=='NOT_MEASURED'
