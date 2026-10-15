"""Reproducible M4 smoke: GUI save/scan, then the exact saved YAML in the CLI.

Run with the launcher's Python and a NEW output folder. Qt runs offscreen;
this verifies real GUI handlers/QProcess workers, not interactive visual use.
"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import unicodedata

import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

import audio_qc
import audio_qc.config
import audio_qc.gui_window
from audio_qc.config import load_config
from audio_qc.gui_window import QCWindow
from audio_qc.synthetic import sine, write_wav


def fingerprint(path):
    return {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'size':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns}


def main(output):
    output.mkdir(parents=True,exist_ok=False)
    samples=sine(3,channels=2,amplitude=.03,frequency=220)
    samples[48000:48003]+=.7
    samples[48004:48012]+=.8
    write_wav(output/'prueba estéreo.wav',samples,mask=3,bext=True,time_reference=172800000)
    # Use the same Unicode spelling for BOTH entry points. Qt's macOS process
    # launch decomposes accents even when APFS enumerates a composed filename.
    source=next(output.glob('*.wav'))
    if sys.platform == 'darwin':
        source=Path(unicodedata.normalize('NFD',str(source)))
    before=fingerprint(source)
    app=QApplication.instance() or QApplication([])
    window=QCWindow()
    window.preset.setCurrentText('CUSTOM')
    editor=window.spec_editor
    editor.select(editor.rate_mode,True)
    editor.rate_value.setText('48000')
    editor.select(editor.bits_required,24)
    editor.select(editor.loudness_mode,'target')
    editor.target.setText('-14,0')
    editor.tolerance.setText('1,0')
    editor.select(editor.peak_mode,True)
    editor.peak_value.setText('-6,0')
    editor.select(editor.bwf_mode,'required')
    editor.channels.setText('2, 6')
    window.snippets.setChecked(True)
    window.hashes.setChecked(True)
    specification=output/'Especificación CUSTOM.yaml'
    effective=window.effective_config()
    assert window.save_yaml(specification),window.status.text()
    assert load_config(specification)==effective
    window.close()
    # Fresh editor instance loads the saved configuration; no in-memory edits
    # from the first editor are required to reproduce the effective policy.
    window=QCWindow()
    assert window.load_yaml(specification)
    assert window.effective_config()==effective
    window.source.setText(str(source))
    window.snippets.setChecked(True)
    window.hashes.setChecked(True)
    window.run_button.click()
    deadline=time.monotonic()+30
    while window._running and time.monotonic()<deadline:
        app.processEvents()
        QTest.qWait(10)
    assert not window._running,window.log.toPlainText()
    assert window.open_button.isEnabled(),window.log.toPlainText()
    gui_path=window.report_path.with_suffix('.json')
    gui=json.loads(gui_path.read_text())
    gui_exit=window.process.exitCode()
    window.close()
    command=[sys.executable,'-u','-m','audio_qc','inspect',str(source),'--config',str(specification),
             '--hash','--export-defect-snippets','--output',str(output/'cli'),'--quiet']
    process=subprocess.run(command,capture_output=True,text=True,check=False)
    print(process.stdout,end='')
    cli_path=output/'cli/QC_REPORT.json'
    cli=json.loads(cli_path.read_text())
    def comparable(report):
        result=deepcopy(report)
        for key in ('scan_date','elapsed_seconds'):
            result.pop(key)
        return result
    assert comparable(gui)==comparable(cli)
    assert gui['configuration']==effective and gui['schema_version']==3
    assert gui_exit==process.returncode==(1 if gui['status']=='FAIL' else 0)
    snippets=[]
    for report_path,report in ((gui_path,gui),(cli_path,cli)):
        issue,=report['files'][0]['defects']
        assert issue['channels']==[1,2] and len(issue['channel_events'])==2
        assert issue['merged_candidate_count']==4
        path=report_path.parent/issue['snippet']
        pcm=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','f64le','-c:a','pcm_f64le','-'],
                           capture_output=True,check=True).stdout
        first=max(0,issue['cluster_first_sample']-48000)
        end=min(len(samples),issue['cluster_last_sample']+1+48000)
        expected=np.rint(samples[first:end]*2**23)/2**23
        np.testing.assert_array_equal(np.frombuffer(pcm,dtype='<f8').reshape(-1,2),expected)
        snippets.append(str(path))
    assert fingerprint(source)==before
    result={'python':sys.executable,'audio_qc':audio_qc.__file__,
            'configuration_module':audio_qc.config.__file__,'gui_module':audio_qc.gui_window.__file__,
            'gui_mode':'offscreen automated handlers and real QProcess worker',
            'specification':str(specification),'gui_report':str(gui_path),'cli_report':str(cli_path),
            'cli_command':command,'gui_exit':gui_exit,'cli_exit':process.returncode,'status':gui['status'],
            'schema_version':3,'reports_equal_except_date_elapsed':True,'source_before':before,
            'source_after':fingerprint(source),'source_unchanged':True,'snippets_sample_equal':snippets}
    (output/'verification.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':
    main(Path(sys.argv[1]).expanduser().absolute())
