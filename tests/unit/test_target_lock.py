import subprocess
import sys

import pytest

pytest.importorskip("fcntl")
from testbed.state.lock_store import TargetLock


def test_target_lock_exclusion_and_release(tmp_path):
    with TargetLock(tmp_path, "policy:ue"):
        with pytest.raises(FileExistsError):
            with TargetLock(tmp_path, "policy:ue"):
                pytest.fail("second owner acquired the lock")
        with TargetLock(tmp_path, "policy:other"):
            pass
    with TargetLock(tmp_path, "policy:ue"):
        pass


def test_process_death_releases_lock_without_deleting_inode(tmp_path):
    code = """
import sys
import time
from pathlib import Path
from testbed.state.lock_store import TargetLock
with TargetLock(Path(sys.argv[1]), 'policy:ue'):
    print('locked', flush=True)
    time.sleep(60)
"""
    process = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "locked"
        with pytest.raises(FileExistsError):
            with TargetLock(tmp_path, "policy:ue"):
                pytest.fail("second process acquired the lock")
    finally:
        process.kill()
        process.wait(timeout=5)
    assert (tmp_path / "policy_ue.lock").exists()
    with TargetLock(tmp_path, "policy:ue"):
        pass
