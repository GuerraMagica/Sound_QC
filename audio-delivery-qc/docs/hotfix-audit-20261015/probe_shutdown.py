from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import json
import sys
from audio_qc.diagnostics import RunLog, SafeFileHandler

root=Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=True)
folder=root/'shutdown_log_failure'
folder.mkdir(exist_ok=False)
out,err=StringIO(),StringIO()
original=SafeFileHandler.close
failed=set()
def close(self):
    if self.baseFilename.endswith('/scan.log') and id(self) not in failed:
        failed.add(id(self))
        raise OSError('Injected log close failure')
    return original(self)
with redirect_stdout(out),redirect_stderr(err):
    logs=RunLog()
    logs.attach(folder)
    logs.logger.info('Before shutdown')
    with patch.object(SafeFileHandler,'close',close):
        logs.close()
    for handler in logs.files:
        original(handler)
result={'console_stdout':out.getvalue(),'console_stderr':err.getvalue(),
        'file_log':(folder/'scan.log').read_text(),
        'stderr_warning_visible':'Cannot close diagnostic log' in err.getvalue()}
(root/'shutdown_observation.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
