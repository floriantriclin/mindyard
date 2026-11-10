# SPDX-License-Identifier: AGPL-3.0-or-later
import mindyard


def test_version_is_exposed() -> None:
    assert mindyard.__version__
