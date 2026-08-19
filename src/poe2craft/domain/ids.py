"""Thin NewType wrappers so ids from different CoE tables can't be mixed up by accident."""
from typing import NewType

ModId = NewType("ModId", str)
BaseId = NewType("BaseId", str)
BaseGroupId = NewType("BaseGroupId", str)
EssenceId = NewType("EssenceId", str)
SocketableId = NewType("SocketableId", str)
CatalystId = NewType("CatalystId", str)

# The mutual-exclusion family a mod belongs to (from `modgroups`, or a synthetic
# per-mod key when a mod has no shared family).
GroupKey = NewType("GroupKey", str)
