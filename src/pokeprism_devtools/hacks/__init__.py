"""One package per hack these tools can read. Everything that knows a
particular hack's source dialect, file layout, or engine lives under its name
here; nothing outside `hacks/` may branch on which hack it is talking to.

This folder holds adapters and nothing else. The mount point — the
layout→adapter resolver, and the one module allowed to know the names — is
`contract/mount.py`, because the studio has to find an adapter somehow and a
studio that imports `hacks/` to do it is not separable from the adapters it
mounts. Each hack answers the mount from its own `claim.py`.
"""
