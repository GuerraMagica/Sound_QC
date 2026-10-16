"""Read-only hotfix audit; invoke with a NEW artifact directory argument."""
from contextlib import contextmanager, nullcontext, redirect_stdout, redirect_stderr
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import errno
import hashlib
import json
import sys
import numpy as np
from audio_qc.cli import main
from audio_qc.diagnostics import RunLog, SafeFileHandler
from audio_qc.process import ToolError
from audio_qc.synthetic import sine, write_wav

root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=False)
source = write_wav(root/'source.wav', sine(), bext=True)
silent = write_wav(root/'silent.wav', np.zeros((192000,1)), bext=True)
signal = sine()
signal[48000, 0] += .6
click = write_wav(root/'click.wav', signal, bext=True)
def fingerprint(path):
    return {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'size':path.stat().st_size, 'mtime_ns':path.stat().st_mtime_ns}
before = {str(p):fingerprint(p) for p in (source,silent,click)}
results = {}

def run(name, source_path=source, injection=None, options=()):
    target = root/name
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err), (injection or nullcontext()):
        code = main(['inspect',str(source_path),'--preset','BROADCAST_EBU_R128',
                     '--output',str(target),*options])
    data = json.loads((target/'QC_REPORT.json').read_text()) if (target/'QC_REPORT.json').exists() else None
    html = (target/'QC_REPORT.html').read_text() if (target/'QC_REPORT.html').exists() else ''
    (root/(name+'-console.txt')).write_text(out.getvalue()+'\nSTDERR:\n'+err.getvalue())
    audio = data['files'][0] if data else None
    result = {'exit_code':code,'report_status':data['status'] if data else None,
              'file_status':audio['status'] if audio else None,
              'measurements':audio['measurements'] if audio else None,
              'checks':audio['checks'] if audio else None,
              'group_checks':data['group_checks'] if data else None,
              'execution_status_present':bool(data and 'execution_status' in data),
              'html_has_report_status':bool(data and ('>'+data['status']+'</span>') in html),
              'stderr':err.getvalue()}
    results[name] = result
    return result

run('valid')
run('silence',silent)
for name, error in [('ffmpeg_error',ToolError('Injected FFmpeg decoder failure')),
                    ('ffmpeg_timeout',ToolError('Process exceeded configured timeout (1s)'))]:
    run(name,injection=patch('audio_qc.scanner.measure_loudness',side_effect=error))

def stream_lines(lines):
    @contextmanager
    def stream(args, timeout, feed):
        for line in lines: feed(line)
        yield BytesIO()
    return stream
run('missing_summary',injection=patch('audio_qc.loudness.stream_process',stream_lines([])))
run('missing_integrated',injection=patch('audio_qc.loudness.stream_process',stream_lines([
    'Summary:','True peak:','Peak: -20.0 dBFS'])))
run('invalid_final_integrated',injection=patch('audio_qc.loudness.stream_process',stream_lines([
    'lavfi.r128.I=-23.000','lavfi.r128.I=nan','Summary:','True peak:','Peak: -20.0 dBFS'])))
run('click_baseline',click,options=['--defects'])
for name, error in [('snippet_permission',PermissionError(errno.EACCES,'Injected evidence directory denied')),
                    ('snippet_unexpected',RuntimeError('Injected exporter error'))]:
    run(name,click,patch('audio_qc.cli.export_snippets',side_effect=error),['--export-defect-snippets'])
run('snippet_ffmpeg',click,patch('audio_qc.snippets.stream_process',side_effect=ToolError('Injected snippet ffmpeg failure')),
    ['--export-defect-snippets'])
run('early_log_failure',injection=patch.object(SafeFileHandler,'_open',side_effect=PermissionError('Injected log denied')))
real_emit=SafeFileHandler.emit
def late_emit(self, record):
    if record.getMessage().startswith('HTML report:'):
        self.failure='Injected late diagnostic failure'
    else:
        real_emit(self,record)
run('late_log_failure',injection=patch.object(SafeFileHandler,'emit',late_emit))
for name,error in [('report_disk_full',OSError(errno.ENOSPC,'Injected disk full')),
                    ('report_permission',PermissionError(errno.EACCES,'Injected report denied'))]:
    run(name,injection=patch('audio_qc.cli.write_reports',side_effect=error))
run('cancelled',injection=patch('audio_qc.scanner.measure_loudness',side_effect=KeyboardInterrupt()))
logs = RunLog()
logs.files=[SimpleNamespace(baseFilename=r'C:\reports\error.log', stream=object(),failure=None)]
results['windows_error_saved']={'actual':logs.error_saved(),'expected':True}
logs.close()
after = {str(p):fingerprint(p) for p in (source,silent,click)}
results['source_integrity']={'before':before,'after':after,'unchanged':before==after}
(root/'observations.json').write_text(json.dumps(results,indent=2,ensure_ascii=False))
for name,result in results.items():
    print(name, {k:result[k] for k in ('exit_code','report_status','file_status','actual','unchanged') if k in result})
