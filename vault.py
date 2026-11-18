from pathlib import Path
from datetime import datetime
import hashlib
import sqlite3
import threading
import tempfile
import json
import os

ROOT = Path(__file__).resolve().parent
DB = ROOT / "vault.sqlite3"

# 真正被監控的資料夾。
WATCH = ROOT / "protected"
LOG = ROOT / "events.jsonl"

LOCK = threading.RLock()
STOP = threading.Event()
LAST = {}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def connect():
    return sqlite3.connect(DB)


def target_path(name):
    # 避免檔名指向監控資料夾以外的位置。
    if (
        not name
        or name in (".", "..")
        or len(name) > 150
        or any(c in name for c in '/\\')
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("檔名不符合規則")

    return WATCH / name


def write_file(name, data):
    """先完成暫存檔，再替換目標，避免讀到半份內容。"""
    target = target_path(name)

    with tempfile.NamedTemporaryFile(dir=WATCH, delete=False) as f:
        temp = Path(f.name)
        f.write(data)

    try:
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def record(kind, name):
    entry = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kind": kind,
        "name": name
    }

    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"[{entry['time']}] {kind}：{name}", flush=True)


def initialize():
    WATCH.mkdir(exist_ok=True)

    with LOCK, connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS files (
                name TEXT PRIMARY KEY,
                original BLOB NOT NULL,
                current BLOB NOT NULL,
                original_hash TEXT NOT NULL
            )
        """)

        # 記住哪些檔案已經搬進實際資料夾。
        db.execute("""
            CREATE TABLE IF NOT EXISTS materialized (
                name TEXT PRIMARY KEY
            )
        """)

        rows = db.execute(
            "SELECT name, current FROM files"
        ).fetchall()

        for name, data in rows:
            done = db.execute(
                "SELECT 1 FROM materialized WHERE name = ?", (name,)
            ).fetchone()

            if not done:
                target = target_path(name)

                # 若已存在就保留，不默默覆蓋。
                if not target.exists() and not target.is_symlink():
                    write_file(name, data)

                db.execute(
                    "INSERT INTO materialized VALUES (?)", (name,)
                )


def upload(name, data):
    target_path(name)

    if len(data) > 5 * 1024 * 1024:
        raise ValueError("每個上傳檔案最大 5 MiB")

    with LOCK, connect() as db:
        exists = db.execute(
            "SELECT 1 FROM files WHERE name = ?", (name,)
        ).fetchone()

        if exists:
            # 保留原始備份，只更新目前檔案。
            write_file(name, data)
            db.execute(
                "UPDATE files SET current = ? WHERE name = ?",
                (data, name)
            )
            message = "已更新受監控檔案，原始備份保持不變"
        else:
            write_file(name, data)
            db.execute(
                "INSERT INTO files VALUES (?, ?, ?, ?)",
                (name, data, data, digest(data))
            )
            message = "已建立原始備份，並加入背景監控"

        db.execute(
            "INSERT OR IGNORE INTO materialized VALUES (?)", (name,)
        )
        record("上傳", name)

    return message


def list_files():
    results = []

    with LOCK, connect() as db:
        rows = db.execute(
            "SELECT name, original_hash FROM files ORDER BY name"
        ).fetchall()

        for name, expected in rows:
            target = target_path(name)
            current_hash = "無法取得"
            size = 0

            try:
                if target.is_symlink():
                    status = "異常：符號連結"
                elif not target.exists():
                    status = "已刪除"
                elif not target.is_file():
                    status = "異常：不是一般檔案"
                else:
                    # 限制讀取量，避免意外讀入巨大檔案。
                    with target.open("rb") as f:
                        data = f.read(5 * 1024 * 1024 + 1)

                    size = len(data)

                    if size > 5 * 1024 * 1024:
                        status = "異常：檔案超過限制"
                    else:
                        current_hash = digest(data)
                        status = "正常" if current_hash == expected else "已修改"

            except OSError:
                status = "讀取失敗"

            results.append({
                "name": name,
                "status": status,
                "original_hash": expected,
                "current_hash": current_hash,
                "size": size
            })

    return results


def restore(name):
    with LOCK, connect() as db:
        row = db.execute(
            "SELECT original, original_hash FROM files WHERE name = ?",
            (name,)
        ).fetchone()

        if row is None:
            raise ValueError("找不到檔案")

        original, expected = row

        if digest(original) != expected:
            raise ValueError("備份驗證失敗，停止還原")

        write_file(name, original)

        if digest(target_path(name).read_bytes()) != expected:
            raise ValueError("還原後驗證失敗")

        db.execute(
            "UPDATE files SET current = ? WHERE name = ?",
            (original, name)
        )
        record("還原成功", name)

    return "還原成功，實際檔案已恢復原始內容"


def watch_loop():
    while not STOP.is_set():
        try:
            with LOCK:
                for item in list_files():
                    name = item["name"]
                    state = (item["status"], item["current_hash"])

                    # 只有狀態或內容改變時才記錄，避免一直重複。
                    if LAST.get(name) != state:
                        record(item["status"], name)
                        LAST[name] = state

        except Exception as error:
            print("背景監控錯誤：", error, flush=True)

        STOP.wait(2)


initialize()

# 在背景執行，不阻塞網頁服務。
threading.Thread(target=watch_loop, daemon=True).start()


def delete_entry(name):
    import time

    with LOCK:
        target = target_path(name)

        with connect() as db:
            found = db.execute(
                "SELECT 1 FROM files WHERE name = ?", (name,)
            ).fetchone()

        if found is None:
            raise ValueError("這份檔案已不存在")

        archive = ROOT / "deleted-backups" / str(time.time_ns())
        archive.mkdir(parents=True)

        with connect() as source:
            with sqlite3.connect(archive / "vault.sqlite3") as dest:
                source.backup(dest)

        moved = False

        try:
            if target.exists() or target.is_symlink():
                os.replace(target, archive / name)
                moved = True

            with connect() as db:
                db.execute(
                    "DELETE FROM materialized WHERE name = ?", (name,)
                )
                db.execute(
                    "DELETE FROM files WHERE name = ?", (name,)
                )

        except Exception:
            if moved:
                os.replace(archive / name, target)
            raise

        LAST.pop(name, None)

    return "已移除檔案與基準，刪除前的備份已保留"
