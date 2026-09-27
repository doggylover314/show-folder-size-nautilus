"""Import show_folder_size with Nautilus stubbed out.

Shared by the tests that exercise the extension's own logic on a machine
with PyGObject but no file manager.  gi.require_version is made to accept
Nautilus, and a module holding two GInterface subclasses is put where
`from gi.repository import Nautilus` will find it.  GInterface, not a plain
class: the provider subclasses both, and GObject's metaclass will not
register a type over a base that is not a GObject one.
"""
import os
import sys
import types
import warnings

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_extension():
    import gi
    from gi.repository import GObject

    real_require = gi.require_version

    def require(namespace, version):
        if namespace == "Nautilus":
            return None
        return real_require(namespace, version)

    gi.require_version = require

    stub = types.ModuleType("gi.repository.Nautilus")

    class ColumnProvider(GObject.GInterface):
        pass

    class InfoProvider(GObject.GInterface):
        pass

    class Column(GObject.GObject):
        pass

    class OperationResult:
        COMPLETE = 0

    stub.ColumnProvider = ColumnProvider
    stub.InfoProvider = InfoProvider
    stub.Column = Column
    stub.OperationResult = OperationResult
    sys.modules["gi.repository.Nautilus"] = stub

    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    with warnings.catch_warnings():
        # The stub interfaces have no implementation support, which GObject
        # says out loud.  Nothing here calls into them.
        warnings.simplefilter("ignore", RuntimeWarning)
        import show_folder_size
    return show_folder_size
