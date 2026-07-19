"""One package per hack these tools can read. Everything that knows a
particular hack's source dialect, file layout, or engine lives under its name
here; nothing outside `hacks/` may branch on which hack it is talking to.
`mount.py` is the mount point: the layout→adapter resolver, and the one
module allowed to know the names.
"""
