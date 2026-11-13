# Companion release files

Companion archives are versioned GitHub Release assets. The website checks the
exact repository/tag in `../config.js` before enabling an architecture's link.
Missing/private releases are shown as unavailable. Never place a GitHub token
in this static directory. A private source repository requires a separately
authorized distribution arrangement for anonymous visitors.

Builds are written to `dist/<target>/`; the release workflow publishes only after
all native builds and checks pass. Vercel excludes local ZIP/tar.gz/DMG files.
See `docs/COMPANION_RELEASES.md` for installation, signing and publication.
