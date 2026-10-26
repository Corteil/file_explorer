"""File operations for the explorer. No badge imports, so it can be tested on a PC.

Long jobs (copy, move, delete) are generators that yield (done, total) after each chunk or
item, so the UI can draw progress and stay responsive. Errors are raised as FSError with a
message fit to show on the badge's screen.
"""
import os

try:
    import vfs
except ImportError:  # off the badge
    vfs = None

CHUNK = 2048
MIN_STORAGE = 256 << 10   # smaller mounts (hexpansion EEPROMs, ~8 KB) are not storage
S_IFDIR = 0x4000
SPACE_MARGIN = 16384      # free space to leave on the filesystem


class FSError(Exception):
    pass


# --- paths ---

def join(base, name):
    return base + name if base.endswith("/") else base + "/" + name


def parent(path):
    p = path.rstrip("/")
    return p[:p.rfind("/")] or "/"


def basename(path):
    return path.rstrip("/").rsplit("/", 1)[-1] or "/"


def human(n):
    if n >= 1 << 20:
        return "%.1f MB" % (n / (1 << 20))
    if n >= 1 << 10:
        return "%.1f KB" % (n / (1 << 10))
    return "%d B" % n


def exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def is_dir(path):
    try:
        return bool(os.stat(path)[0] & S_IFDIR)
    except OSError:
        return False


def size_of(path):
    return os.stat(path)[6]


# --- storages ---

def mounts():
    """Mount points, longest first, so the first one that prefixes a path is its own."""
    pts = ["/"]
    if vfs is not None:
        for _fs, p in vfs.mount():
            if p not in pts:
                pts.append(p)
    return sorted(pts, key=len, reverse=True)


def mount_of(path):
    for p in mounts():
        if p == "/" or path == p or path.startswith(p + "/"):
            return p
    return "/"


def storages():
    """[(label, path, total, free)] for the flash and every real storage mount. Slow on the
    badge's own flash (statvfs takes ~0.7 s), so callers cache it."""
    out = []
    for p in sorted(mounts(), key=len):
        if p != "/" and p.count("/") != 1:
            continue
        try:
            v = os.statvfs(p)
        except OSError:
            continue
        total = v[1] * v[2]
        if p != "/" and total < MIN_STORAGE:
            continue
        out.append(("Flash" if p == "/" else p[1:], p, total, v[1] * v[3]))
    return out


def free_space(path):
    v = os.statvfs(mount_of(path))
    return v[1] * v[3]


# --- listing ---

def listdir(path):
    """[(name, is_dir, size)], folders first then by name."""
    out = []
    if hasattr(os, "ilistdir"):
        for e in os.ilistdir(path):
            if e[0] in (".", ".."):
                continue
            out.append((e[0], bool(e[1] & S_IFDIR), e[3] if len(e) > 3 else 0))
    else:
        for name in os.listdir(path):
            st = os.stat(join(path, name))
            out.append((name, bool(st[0] & S_IFDIR), st[6]))
    out.sort(key=lambda e: (not e[1], e[0].lower()))
    return out


def walk(path):
    """[(relative path, is_dir, size)] for path and everything below it, parents first."""
    items = [("", True, 0)] if is_dir(path) else [("", False, size_of(path))]
    if items[0][1]:
        stack = [""]
        while stack:
            rel = stack.pop()
            for name, d, size in listdir(join(path, rel) if rel else path):
                r = join(rel, name) if rel else name
                items.append((r, d, size))
                if d:
                    stack.append(r)
    return items


# --- names ---

def check_name(name):
    name = name.strip()
    if not name or name in (".", ".."):
        raise FSError("Enter a name")
    if "/" in name:
        raise FSError("Name cannot contain /")
    if len(name) > 63:
        raise FSError("Name is too long")
    return name


def unique(path):
    """path, or path with " (2)", " (3)"... before the extension if it exists already."""
    if not exists(path):
        return path
    head, _, ext = basename(path).rpartition(".")
    if not head:
        head, ext = ext, ""
    for n in range(2, 100):
        name = "%s (%d)%s" % (head, n, "." + ext if ext else "")
        cand = join(parent(path), name)
        if not exists(cand):
            return cand
    raise FSError("Too many copies")


# --- operations ---

def mkdir(path):
    if exists(path):
        raise FSError("Name already exists")
    try:
        os.mkdir(path)
    except OSError:
        raise FSError("Could not create folder")


def rename(path, new_name):
    new_name = check_name(new_name)
    dst = join(parent(path), new_name)
    if dst == path:
        return dst
    if exists(dst):
        raise FSError("Name already exists")
    try:
        os.rename(path, dst)
    except OSError:
        raise FSError("Could not rename")
    return dst


def delete(path):
    """Generator: remove a file, or a folder and everything in it."""
    if path == "/" or path in mounts():
        raise FSError("Cannot delete a storage")
    items = walk(path)
    total = len(items)
    for n, (rel, d, _size) in enumerate(reversed(items)):
        p = join(path, rel) if rel else path
        try:
            os.rmdir(p) if d else os.remove(p)
        except OSError:
            raise FSError("Could not delete " + basename(p))
        yield n + 1, total


def copy(src, dst):
    """Generator: copy a file or folder to the new path dst, yielding (bytes done, bytes total)."""
    if exists(dst):
        raise FSError("Name already exists")
    if is_dir(src) and (dst == src or dst.startswith(src.rstrip("/") + "/")):
        raise FSError("Cannot copy into itself")
    items = walk(src)
    total = sum(s for _r, d, s in items if not d)
    try:
        if total + SPACE_MARGIN > free_space(dst if exists(parent(dst)) else "/"):
            raise FSError("Not enough space")
    except OSError:
        pass
    done = 0
    yield 0, max(total, 1)
    for rel, d, _size in items:
        s = join(src, rel) if rel else src
        t = join(dst, rel) if rel else dst
        try:
            if d:
                os.mkdir(t)
                continue
            with open(s, "rb") as fi, open(t, "wb") as fo:
                while True:
                    buf = fi.read(CHUNK)
                    if not buf:
                        break
                    fo.write(buf)
                    done += len(buf)
                    yield done, max(total, 1)
        except OSError:
            raise FSError("Copy failed at " + basename(s))
    yield max(total, 1), max(total, 1)


def move(src, dst):
    """Generator: rename within a storage, else copy then delete the original."""
    if exists(dst):
        raise FSError("Name already exists")
    if is_dir(src) and dst.startswith(src.rstrip("/") + "/"):
        raise FSError("Cannot move into itself")
    if mount_of(src) == mount_of(dst):
        try:
            os.rename(src, dst)
        except OSError:
            raise FSError("Could not move")
        yield 1, 1
        return
    for done, total in copy(src, dst):
        yield done, total * 2    # the copy is the first half
    for done, total in delete(src):
        yield total + done, total * 2


# --- reading ---

def read_at(path, offset, n):
    with open(path, "rb") as f:
        f.seek(offset)
        return f.read(n)


def sniff(path, limit=4096):
    """(is_text, text) for the start of a file. Binary data gives (False, "")."""
    data = read_at(path, 0, limit)
    if any(b < 9 or 13 < b < 32 for b in data):
        return False, ""
    try:
        return True, str(data, "utf-8")
    except Exception:
        return False, ""


def wrap(text, width):
    """Split text into lines of at most width characters."""
    lines = []
    for raw in text.replace("\r", "").split("\n"):
        raw = raw.replace("\t", "    ")
        while len(raw) > width:
            cut = raw.rfind(" ", 0, width)
            cut = cut if cut > width // 2 else width
            lines.append(raw[:cut])
            raw = raw[cut:].lstrip(" ") if cut != width else raw[cut:]
        lines.append(raw)
    return lines
