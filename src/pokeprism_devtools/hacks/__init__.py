"""One package per hack these tools can read. Everything that knows a
particular hack's source dialect, file layout, or engine lives under its name
here; nothing outside `hacks/` may branch on which hack it is talking to.
`shared/paths` is the mount point — today it only says yes to prism or no by
name, and when a second adapter exists it becomes the layout→adapter resolver.
"""
