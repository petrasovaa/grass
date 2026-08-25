# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests of loading the C libraries into the process with init(load_libs=True)

This file is meant to be executed also standalone (pytest with this file as
the only argument) against an installation which was moved away from the
prefix it was configured with. Only then the GRASS libraries cannot find each
other through their RUNPATH and the tests actually fail without the loading.
"""

import json
import os
import subprocess
import sys
from textwrap import dedent

import pytest

import grass.app.runtime
import grass.script as gs


def run_in_clean_environment(code, tmp_path):
    """Run code in a subprocess without the dynamic library search path variable

    The variable is what a parent GRASS session or a manual setup uses to make
    the GRASS libraries available, so removing it leaves the loading done by
    init as the only mechanism which can make grass.lib work.

    :returns: the completed process, so that the output streams are available
    """
    source_file = tmp_path / "code.py"
    source_file.write_text(dedent(code))
    env = os.environ.copy()
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("DYLD_LIBRARY_PATH", None)
    result = subprocess.run(
        [sys.executable, os.fspath(source_file)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, (
        f"code failed with {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


@pytest.mark.usefixtures("mock_no_session")
def test_grass_lib_usable_with_load_libs(tmp_path):
    """Check that grass.lib is usable after init with load_libs"""
    project = tmp_path / "test"
    code = f"""
        import json
        import grass.script as gs

        gs.create_project(r"{project}")
        with gs.setup.init(r"{project}", load_libs=True):
            import grass.lib.gis as libgis
            import grass.lib.raster as libraster

            libgis.G_gisinit(b"test")
            gs.run_command("g.region", rows=2, cols=2)
            gs.mapcalc("ones = 1")
            fd = libraster.Rast_open_old(b"ones", b"")
            libraster.Rast_close(fd)
        print(json.dumps({{"raster_opened": True}}))
    """
    result = run_in_clean_environment(code, tmp_path=tmp_path)
    assert json.loads(result.stdout)["raster_opened"]


@pytest.mark.usefixtures("mock_no_session")
def test_grass_lib_usable_with_load_libs_and_custom_env(tmp_path):
    """Check that grass.lib is usable with load_libs and a custom environment

    A session which keeps its variables in its own environment reaches the
    libraries only through the loader and through the environment of the
    libraries themselves, because they read neither the session environment
    nor, on Windows, the global one.
    """
    project = tmp_path / "test"
    code = f"""
        import json
        import os
        import grass.script as gs

        gs.create_project(r"{project}")
        env = os.environ.copy()
        with gs.setup.init(r"{project}", env=env, load_libs=True):
            import grass.lib.gis as libgis

            libgis.G_gisinit(b"test")
            session = [
                libgis.G_gisdbase().decode(),
                libgis.G_location().decode(),
                libgis.G_mapset().decode(),
            ]
        print(
            json.dumps(
                {{
                    "session_seen_by_c_library": session,
                    "gisbase_in_global_env": "GISBASE" in os.environ,
                }}
            )
        )
    """
    result = json.loads(run_in_clean_environment(code, tmp_path=tmp_path).stdout)
    # The library works with the session which init created, not with another
    # one it may have found in the environment.
    assert result["session_seen_by_c_library"] == [
        str(tmp_path),
        project.name,
        "PERMANENT",
    ]
    # The session did not fall back to the global environment for the lookup.
    assert not result["gisbase_in_global_env"]


@pytest.mark.usefixtures("mock_no_session")
def test_library_messages_are_reported(tmp_path):
    """Check that a message from the C libraries reaches the standard error

    Printing a message needs GISBASE, so a library which does not have it
    fails to report the failure as well and ends the process without saying
    anything at all.
    """
    project = tmp_path / "test"
    code = f"""
        import os
        import grass.script as gs

        gs.create_project(r"{project}")
        with gs.setup.init(r"{project}", env=os.environ.copy(), load_libs=True):
            import grass.lib.gis as libgis

            libgis.G_warning(b"message from the library")
        print("{{}}")
    """
    result = run_in_clean_environment(code, tmp_path=tmp_path)
    assert "message from the library" in result.stderr


@pytest.mark.usefixtures("mock_no_session")
def test_libraries_not_loaded_by_default(tmp_path, monkeypatch):
    """Check that a session does not load the C libraries unless asked to"""
    calls = []

    def record_call(install_path):
        calls.append(install_path)

    monkeypatch.setattr(grass.app.runtime, "preload_dynamic_libraries", record_call)
    project = tmp_path / "test"
    gs.create_project(project)
    with gs.setup.init(project, env=os.environ.copy()):
        pass
    assert not calls
    with gs.setup.init(project, env=os.environ.copy(), load_libs=True):
        pass
    assert calls


def test_preload_reports_libraries_which_cannot_be_loaded(tmp_path):
    """Check that libraries which fail to load are reported, not raised"""
    lib_path = tmp_path / "lib"
    lib_path.mkdir()
    broken = lib_path / "libgrass_notalibrary.so"
    broken.write_text("This is not a shared library.")
    failures = grass.app.runtime.preload_dynamic_libraries(install_path=tmp_path)
    if sys.platform.startswith("win"):
        assert failures == []
    else:
        # Paths are compared by name because the function resolves them and
        # the temporary directory may be behind a symbolic link.
        assert [path.name for path, _error in failures] == [broken.name]
