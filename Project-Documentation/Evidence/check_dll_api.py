"""
Print the real method signatures (with parameter names) and enum options from McsUsbNet.dll.

Why: the MCS library is a Windows .NET DLL, so it can't be loaded on a Mac or Linux laptop,
and calling a method with the wrong argument types only fails on the lab PC. This reads the
DLL's metadata directly, so you can check a call before you get rig time.

Run from the repo root (any OS):
    pip install dnfile
    python Project-Documentation/Evidence/check_dll_api.py                 # the classes the hardware code uses
    python Project-Documentation/Evidence/check_dll_api.py CStg200xBasicNet  # one class, all methods
"""
import sys
from pathlib import Path

import dnfile

REPO = Path(__file__).resolve().parents[2]
DLL = REPO / "Baseline-Protocol" / "Hardware" / "McsUsbNet.dll"

DEFAULT_CLASSES = {
    "CMcsUsbListNet": None,
    "CMcsUsbNet": {"Connect", "Disconnect"},
    "CMcsUsbDacqNet": {"SetDataMode", "GetResolutionPerDigit", "SetSamplerate", "GetChannelLayout",
                       "StartDacq", "StopDacq", "get_ChannelBlock"},
    "CMeaDeviceNet": {"EnableDigitalIn", "EnableChecksum", "SetNumberOfAnalogChannels"},
    "CSCUFunctionNet": {"SetDacqLegacyMode"},
    "ChannelBlockNet": None,
    "CStg200xBasicNet": {"SendStart", "SendStop", "SetVoltageMode", "SetCurrentMode", "SetElectrodeMode",
                         "SetElectrodeDacMux", "SetElectrodeEnable", "SetBlankingEnable",
                         "SetEnableAmplifierProtectionSwitch"},
    "CStg200xDownloadBasicNet": {"SetupTrigger", "get_Stimulus"},
    "CStg200xDownloadNet": {"PrepareAndSendData"},
    "CStimulusFunctionNet": {"CreateSideband", "PrepareAndSendData", "SendStart", "SendStop", "SetupTrigger"},
}
ENUMS = ["DataModeEnumNet", "ChannelBlockTypeNet", "SampleSizeNet", "SampleDstSizeNet", "STG_DestinationEnumNet",
         "ElectrodeModeEnumNet", "ElectrodeDacMuxEnumNet", "DacqGroupChannelEnumNet", "DigitalDatastreamEnableEnumNet"]

ELEM = {0x01: "void", 0x02: "bool", 0x03: "char", 0x04: "sbyte", 0x05: "byte", 0x06: "short", 0x07: "ushort",
        0x08: "int", 0x09: "uint", 0x0a: "long", 0x0b: "ulong", 0x0c: "float", 0x0d: "double", 0x0e: "string",
        0x16: "TypedRef", 0x18: "IntPtr", 0x19: "UIntPtr", 0x1c: "object"}

pe = dnfile.dnPE(str(DLL))
md = pe.net.mdtables


def type_name(tag, idx):
    table = {0: md.TypeDef, 1: md.TypeRef}.get(tag)
    return str(table.rows[idx - 1].TypeName) if table else f"TypeSpec#{idx}"


class Sig:
    def __init__(self, blob):
        self.b, self.i = bytes(blob), 0

    def byte(self):
        self.i += 1
        return self.b[self.i - 1]

    def cint(self):
        b0 = self.byte()
        if b0 & 0x80 == 0:
            return b0
        if b0 & 0xC0 == 0x80:
            return ((b0 & 0x3F) << 8) | self.byte()
        return ((b0 & 0x1F) << 24) | (self.byte() << 16) | (self.byte() << 8) | self.byte()

    def tdor(self):
        v = self.cint()
        return type_name(v & 3, v >> 2)

    def type(self):
        t = self.byte()
        if t in (0x1f, 0x20):  # C++/CLI modifiers (IsLong, IsConst...): skip
            self.tdor()
            return self.type()
        if t in ELEM:
            return ELEM[t]
        if t == 0x10:
            return "ref " + self.type()
        if t == 0x0f:
            return self.type() + "*"
        if t in (0x11, 0x12):
            return self.tdor()
        if t == 0x1d:
            return self.type() + "[]"
        if t == 0x15:
            self.byte()
            base, n = self.tdor(), self.cint()
            return f"{base}<{', '.join(self.type() for _ in range(n))}>"
        if t in (0x13, 0x1e):
            return f"T{self.cint()}"
        return f"<0x{t:02x}>"


def signature(method_row):
    blob = method_row.Signature
    s = Sig(blob.value if hasattr(blob, "value") else blob)
    if s.byte() & 0x10:
        s.cint()
    n = s.cint()
    ret = s.type()
    params = [s.type() for _ in range(n)]
    names = {}
    for p in method_row.ParamList:
        names[p.row.Sequence] = str(p.row.Name)
    return ret, [f"{ty} {names.get(i + 1, f'p{i + 1}')}" for i, ty in enumerate(params)]


def visibility(typedef):
    f = typedef.Flags
    for attr, label in [("tdPublic", "public"), ("tdNestedPublic", "public"), ("tdNotPublic", "INTERNAL")]:
        if getattr(f, attr, False):
            return label
    return "?"


def dump_class(name, only=None):
    for t in md.TypeDef.rows:
        if str(t.TypeName) != name:
            continue
        base = ""
        if t.Extends and t.Extends.row is not None:
            base = str(t.Extends.row.TypeName)
        print(f"\n### {name}  (inherits {base})\n")
        print("```")
        for m in t.MethodList:
            mname = str(m.row.Name)
            if only and mname not in only:
                continue
            ret, args = signature(m.row)
            print(f"{ret} {mname}({', '.join(args)})")
        print("```")


def dump_enums():
    print("\n## Enum options\n")
    for t in md.TypeDef.rows:
        if str(t.TypeName) in ENUMS + ["SampleSize", "SampleDstSize"]:
            fields = [str(f.row.Name) for f in t.FieldList if str(f.row.Name) != "value__"]
            print(f"- `{t.TypeName}` ({visibility(t)}): {', '.join(fields) or '(no public options)'}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for cls in sys.argv[1:]:
            dump_class(cls)
    else:
        print("# McsUsbNet.dll API reference (generated)\n")
        print(f"Generated by `Project-Documentation/Evidence/check_dll_api.py` from `{DLL.relative_to(REPO)}`.")
        print("Only the methods the hardware code uses (or should use) are listed. `ref` parameters come back")
        print("from pythonnet as extra return values, e.g. `data, n = ReadFramesI32(ch, 0, frames, 0)`.")
        for cls, only in DEFAULT_CLASSES.items():
            dump_class(cls, only)
        dump_enums()
