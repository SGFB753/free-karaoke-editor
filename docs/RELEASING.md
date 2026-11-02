# Publishing a release

Use the **Windows release** workflow with the intended version tag. It runs
the tests, builds in a clean environment, exercises the finished EXE, uploads
the assets and only then publishes the release. Wait for the workflow to finish.

Do not publish a local archive and create a public version tag first: that
starts a second CI build after users can already download the first archive.
A local successful build is useful verification, but does not replace the clean
release build. Use the workflow's `publish=false` input for verification builds
without changing any public release or tag.

Qwen dependencies and the Node binary are separate runtime assets. They are
installed into the user's persistent cache on first use. Model weights remain
in their existing cache. The core ZIP must not contain these optional runtimes.
The small `nodejs_wheel` Python shim remains in the core for pytubefix.

Runtime assets use the immutable `runtime-v1` release and a Python ABI in their
filenames. Do not overwrite an already published runtime asset. Bump its
revision when dependency compatibility changes. Test the core EXE against the
separate staged runtime before publication; importing from the developer venv
does not verify the package. CI also checks the new core against the existing
published runtimes, since users keep those cached across core updates. A
compatibility failure requires a new runtime revision, not overwriting v1.

Changelog entries describe differences from the previously published version.
Do not list fixes made while developing a new, not-yet-published feature as
separate release changes.

For a real update rehearsal, build first, then run:

```powershell
.\.venv\Scripts\python.exe app\tests\test_update_install_live.py --old-archive PATH_TO_PREVIOUS_RELEASE.zip --new-archive dist\KaraokeStudio-windows-x64.zip
```

This uses the previous release's compiled download/handoff code and frozen
updater, then repeats with the new installation's updater. A private HTTP asset
server replaces GitHub for the download; the writable sandbox uses the elevated
worker flag to suppress UAC and GUI restart. The installed real EXE is then
started headlessly and checked over HTTP. It checks obsolete library removal,
projects/settings/exports, cached runtimes, model sentinels, helper retirement
and temporary disk usage. It does not exercise the interactive UAC prompt.
The sandbox is removed afterwards; logs and the report remain in
`build/update-e2e/`. The current installation and user data are not touched.
