# -*- coding: utf-8 -*-
"""Stand-ins for Revit, pyRevit and .NET, so the libraries can be imported and tested outside Revit with Python 3.

Import this module before any library: it registers fake Autodesk / System / pyrevit modules and puts the
extension's lib folder on the path. Anything the fakes don't define is a do-nothing stub, so a test only has to
build the few objects the code under test really uses."""
import os
import sys
import types

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the extension folder (holds lib\)

# ---------------------------------------------------------------- stand-ins for Revit, pyRevit and .NET
class Stub(object):
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, n):
        return Stub()

    def __call__(self, *a, **k):
        return Stub()

    def __iter__(self):
        return iter([])


class StubMeta(type):
    def __getattr__(cls, n):
        return Stub()


class EnumMeta(type):  # noqa
    def __getattr__(cls, n):
        return -(abs(hash(n)) % 9000000) - 1000000


class BIC(object, metaclass=EnumMeta):
    OST_FireAlarmDevices = -2008085
    OST_ConduitFitting = -2008128


class StorageType(object):
    String, Integer, Double, ElementId = "String", "Integer", "Double", "ElementId"


class Id(object):
    def __init__(self, v):
        self.Value = v

    def __eq__(self, o):
        return isinstance(o, Id) and o.Value == self.Value

    def __ne__(self, o):
        return not self == o

    def __hash__(self):
        return hash(self.Value)

    def __repr__(self):
        return "Id(%s)" % self.Value


Id.InvalidElementId = Id(-1)


class TransactionStatus(object):
    Uninitialized, Started, Committed, RolledBack = "Uninitialized", "Started", "Committed", "RolledBack"


class Scenario(object):
    mode = "ok"         # ok | rolledback | raise_set | raise_start
    rollbacks = 0
    names = []


class FakeTransaction(object):
    def __init__(self, doc, name):
        self.name, self.status = name, TransactionStatus.Uninitialized
        Scenario.names.append(name)

    def Start(self):
        if Scenario.mode == "raise_start":
            raise Exception("start failed")
        self.status = TransactionStatus.Started

    def Commit(self):
        if Scenario.mode == "rolledback":
            self.status = TransactionStatus.RolledBack
        else:
            self.status = TransactionStatus.Committed
        return self.status

    def RollBack(self):
        Scenario.rollbacks += 1
        self.status = TransactionStatus.RolledBack

    def GetStatus(self):
        return self.status

    def HasStarted(self):
        return self.status != TransactionStatus.Uninitialized

    def HasEnded(self):
        return self.status in (TransactionStatus.Committed, TransactionStatus.RolledBack)


class FakeGroup(FakeTransaction):
    def Start(self):
        self.status = TransactionStatus.Started

    def Assimilate(self):
        self.status = TransactionStatus.Committed

    def RollBack(self):
        self.status = TransactionStatus.RolledBack


class FakeCollector(object):
    def __init__(self, doc):
        self.doc, self.items = doc, []

    def OfCategory(self, c):
        return self

    def WhereElementIsNotElementType(self):
        self.items = list(self.doc.devices)
        return self

    def WhereElementIsElementType(self):
        self.items = list(self.doc.types.values())
        return self

    def ToElements(self):
        return list(self.items)

    def __iter__(self):
        return iter(self.items)


class Canceled(Exception):
    pass


class ConduitBase(object):
    pass


class WPFWindow(object):
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, n):
        return Stub()


def module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    m.__getattr__ = lambda n: StubMeta(n, (Stub,), {})
    sys.modules[name] = m
    return m


for n in ("Autodesk", "Autodesk.Revit", "Autodesk.Revit.UI", "Autodesk.Revit.UI.Selection", "System",
          "System.Windows", "System.Windows.Input", "System.Windows.Controls", "System.Windows.Media", "System.Collections", "System.Collections.Generic", "System.Data",
          "Microsoft", "Microsoft.Win32", "clr"):
    module(n)
class _List(object):
    def __getitem__(self, t):
        return lambda items: list(items)


sys.modules["System.Collections.Generic"].List = _List()
class BIP(object):
    CURVE_ELEM_LENGTH = "length"
    ALL_MODEL_INSTANCE_COMMENTS = "comments"
    SYMBOL_NAME_PARAM = "symbol name"


POWER_SPEC, NUMBER_SPEC = "spec:power", "spec:number"


class SpecTypeId(object):
    ElectricalPower, ApparentPower, Number = POWER_SPEC, "spec:apparent", NUMBER_SPEC


class UnitTypeId(object):
    Watts = "unit:watts"


class UnitUtils(object):
    @staticmethod
    def ConvertFromInternalUnits(value, unit):
        assert unit == UnitTypeId.Watts
        return value * 0.09290304


module("Autodesk.Revit.DB", BuiltInCategory=BIC, StorageType=StorageType, ElementId=Id,
       TransactionStatus=TransactionStatus, Transaction=FakeTransaction, TransactionGroup=FakeGroup,
       FilteredElementCollector=FakeCollector, BuiltInParameter=BIP, SpecTypeId=SpecTypeId, UnitTypeId=UnitTypeId,
       UnitUtils=UnitUtils)
module("Autodesk.Revit.DB.Electrical", Conduit=ConduitBase)
module("Autodesk.Revit.Exceptions", OperationCanceledException=Canceled)
# packages hold their submodules, so "import Autodesk.Revit.DB as DB" finds the stand-in
for _name in list(sys.modules):
    if "." in _name and _name.split(".")[0] in ("Autodesk", "System", "Microsoft"):
        _parent, _child = _name.rsplit(".", 1)
        if _parent in sys.modules:
            setattr(sys.modules[_parent], _child, sys.modules[_name])


class UI(object):
    """What the tool asked and was told: forms.alert / toast / CommandSwitchWindow and picks."""
    answers = []        # scripted answers for CommandSwitchWindow.show / SelectFromList.show, in order
    alert_answer = None
    said = []

    @staticmethod
    def reset(answers=(), alert_answer=None):
        UI.answers, UI.alert_answer, UI.said = list(answers), alert_answer, []


class CommandSwitchWindow(object):
    @staticmethod
    def show(options, message=None, **k):
        UI.said.append(("menu", message, list(options)))
        return UI.answers.pop(0) if UI.answers else None


class SelectFromList(object):
    @staticmethod
    def show(options, title=None, **k):
        UI.said.append(("list", title, list(options)))
        return UI.answers.pop(0) if UI.answers else None


def alert(msg, title=None, **k):
    UI.said.append(("alert", msg))
    return UI.alert_answer


def toast(msg, title="pyRevit", **k):
    UI.said.append(("toast", msg, title))


forms = module("pyrevit.forms", alert=alert, toast=toast, CommandSwitchWindow=CommandSwitchWindow,
               SelectFromList=SelectFromList, WPFWindow=WPFWindow, ask_for_string=lambda **k: None)


class Selection(object):
    selected = []
    shown = []

    def GetElementIds(self):
        return list(Selection.selected)

    def SetElementIds(self, ids):
        Selection.shown.append([i.Value for i in ids])

    def PickObject(self, *a):
        raise Canceled()


class UIDoc(object):
    Selection = Selection()

    def RefreshActiveView(self):
        pass


class Revit(object):
    doc = None
    uidoc = UIDoc()


pyrevit = module("pyrevit", forms=forms, revit=Revit, script=Stub())
sys.modules["pyrevit.revit"] = Revit
os.environ.setdefault("APPDATA", "/tmp/appdata")
sys.path.insert(0, os.path.join(root, "lib"))


# ---- piping (VESDA Pipe Swap) ----
module("Autodesk.Revit.DB.Plumbing", Pipe=type("Pipe", (), {}))
sys.modules["Autodesk.Revit.DB"].Plumbing = sys.modules["Autodesk.Revit.DB.Plumbing"]
for _enum in ("PartType", "RoutingPreferenceRuleGroupType"):
    setattr(sys.modules["Autodesk.Revit.DB"], _enum, EnumMeta(_enum, (object,), {}))

# ---- extensible storage (the riser one-lines' data) ----
module("Autodesk.Revit.DB.ExtensibleStorage")
sys.modules["Autodesk.Revit.DB"].ExtensibleStorage = sys.modules["Autodesk.Revit.DB.ExtensibleStorage"]
