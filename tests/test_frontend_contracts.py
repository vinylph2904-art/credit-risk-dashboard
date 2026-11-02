"""Run dependency-free JavaScript contracts as part of the regular test suite."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('filename', ['layout.test.cjs', 'mini_hover.test.cjs', 'reference.test.cjs'])
def test_frontend_contract(filename):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is required for JavaScript contract tests.')
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, '--test', str(root / 'tests/js' / filename)],
                            cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
