# Companion release files

The web UI expects release archives in this directory using the names configured
in `../config.js`. Build the Windows archive with
`powershell -File scripts/build_companion.ps1`; the generated archive is written
to `dist/` and should be copied here (or the URL in `config.js` should be changed
to the corresponding release asset URL) before deploying the static website.

Do not commit private signing certificates or release credentials.
