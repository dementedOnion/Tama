from pathlib import Path
import pefile

root = Path("diagnostic_dist/TamaDiag/_internal").resolve()
search = [root, root / "PySide6", root / "shiboken6", Path(r"C:\Windows\System32")]
seen = set()


def resolve(name):
    for directory in search:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def exports(path):
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
    table = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
    if table is None:
        return set(), set()
    names = {symbol.name for symbol in table.symbols if symbol.name}
    ordinals = {symbol.ordinal for symbol in table.symbols}
    return names, ordinals


def inspect(path):
    path = path.resolve()
    if path in seen:
        return
    seen.add(path)
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
    for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        dll_name = entry.dll.decode(errors="replace")
        if dll_name.lower().startswith(("api-ms-", "ext-ms-")):
            continue
        target = resolve(dll_name)
        if target is None:
            print(f"MISSING DLL: {path.name} -> {dll_name}")
            continue
        names, ordinals = exports(target)
        for symbol in entry.imports:
            if symbol.name and symbol.name not in names:
                print(f"MISSING PROC: {path.name} -> {target} :: {symbol.name.decode(errors='replace')}")
            elif not symbol.name and symbol.ordinal not in ordinals:
                print(f"MISSING ORDINAL: {path.name} -> {target} :: {symbol.ordinal}")
        if root in target.parents:
            inspect(target)


inspect(root / "PySide6" / "QtCore.pyd")
