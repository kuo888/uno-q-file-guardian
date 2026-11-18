from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs
import json
import secrets
import vault

TOKEN = secrets.token_urlsafe(32)

PAGE = """<!doctype html>
<html lang="zh-Hant">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>UNO Q 檔案守護站</title>
<style>
body{font-family:system-ui;background:#eef3f8;color:#17324d;
max-width:900px;margin:35px auto;padding:0 18px}
section,article{background:white;padding:22px;border-radius:14px;
margin:18px 0}
button{background:#087f83;color:white;border:0;padding:10px 16px;
border-radius:8px;cursor:pointer;font-size:16px}
button:disabled{opacity:.5}
code{display:block;overflow-wrap:anywhere;background:#f3f6fa;
padding:10px;font-size:13px}
.ok{color:#087f83}.changed{color:#c2410c}
#message{min-height:26px}
</style>

<h1>UNO Q 檔案守護站</h1>
<p>上傳檔案版本比對 · SHA-256 · 原始備份還原</p>

<section>
<h2>新增受保護檔案</h2>
<p>此處只新增檔案與原始基準；更新既有檔案，請使用下方卡片的「上傳修改版」。</p>
<p>單一檔案上限 5 MiB。還原只影響板子內的版本。</p>
<input type="file" id="file">
<button id="upload">新增並建立基準</button>
<p id="message" role="status"></p>
</section>

<div id="files"></div>

<script>
const token = "__TOKEN__";
const message = document.getElementById("message");

function element(tag, text) {
    const node = document.createElement(tag);
    node.textContent = text;
    return node;
}

async function refresh() {
    const response = await fetch("/api/files");
    const data = await response.json();
    if (!response.ok) throw Error(data.error);

    const area = document.getElementById("files");
    area.replaceChildren();

    if (!data.length) {
        area.append(element("p", "尚無上傳檔案，先選一個 test.txt。"));
    }

    for (const file of data) {
        const card = document.createElement("article");
        card.append(element("h2", file.name));

        const status = element("h3", file.status);
        status.className = file.status === "正常" ? "ok" : "changed";
        card.append(status);
        card.append(element("p", "目前大小：" + file.size + " bytes"));
        card.append(element("p", "原始 SHA-256"));
        card.append(element("code", file.original_hash));
        card.append(element("p", "目前 SHA-256"));
        card.append(element("code", file.current_hash));

        const button = element("button", "還原並下載");
        button.disabled = file.status === "正常";
        button.onclick = async () => {
            if (!confirm("確定還原 " + file.name + "？")) return;
            button.disabled = true;
            try {
                await change("/api/restore?name=" +
                    encodeURIComponent(file.name), new Uint8Array());

                const link = document.createElement("a");
                link.href = "/api/download?name=" +
                    encodeURIComponent(file.name);
                document.body.append(link);
                link.click();
                link.remove();
            } catch (error) {
                message.textContent = error.message;
                button.disabled = false;
            }
        };
        card.append(button);

        const deleteButton = element("button", "刪除檔案與基準");
        deleteButton.style.background = "#b42318";
        deleteButton.style.marginLeft = "12px";

        deleteButton.onclick = async () => {
            if (!confirm("確定刪除「" + file.name + "」的板子檔案與基準？")) return;

            deleteButton.disabled = true;

            try {
                await change(
                    "/api/delete?name=" + encodeURIComponent(file.name),
                    new Uint8Array()
                );
            } catch (error) {
                message.textContent = error.message;
                deleteButton.disabled = false;
            }
        };

        card.append(deleteButton);

        const update = element("button", "上傳修改版");
        update.style.marginLeft = "12px";

        const picker = document.createElement("input");
        picker.type = "file";
        picker.hidden = true;

        update.onclick = () => picker.click();

        picker.onchange = async () => {
            const selected = picker.files[0];
            if (!selected) return;

            if (selected.size > 5 * 1024 * 1024) {
                message.textContent = "檔案超過 5 MiB";
                picker.value = "";
                return;
            }

            const question =
                "要用「" + selected.name + "」的內容更新「" +
                file.name + "」嗎？原始備份不會改變。";

            if (!confirm(question)) {
                picker.value = "";
                return;
            }

            update.disabled = true;

            try {
                await change(
                    "/api/update?name=" + encodeURIComponent(file.name),
                    await selected.arrayBuffer()
                );
            } catch (error) {
                message.textContent = error.message;
            } finally {
                update.disabled = false;
                picker.value = "";
            }
        };

        card.append(update, picker);

        const download = element("a", "下載目前版本到電腦");
        download.href = "/api/download?name=" +
            encodeURIComponent(file.name);
        download.style.display = "inline-block";
        download.style.marginLeft = "16px";
        card.append(download);

        area.append(card);
    }
}

async function change(url, body) {
    message.textContent = "處理中，請稍候…";
    const response = await fetch(url, {
        method: "POST",
        headers: {"X-Guardian-Token": token},
        body: body
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error);
    message.textContent = result.message;
    await refresh();
}

document.getElementById("upload").onclick = async () => {
    const file = document.getElementById("file").files[0];
    if (!file) {
        message.textContent = "請先選擇檔案";
        return;
    }
    if (file.size > 5 * 1024 * 1024) {
        message.textContent = "檔案超過 5 MiB";
        return;
    }

    const button = document.getElementById("upload");
    button.disabled = true;
    try {
        await change("/api/create?name=" + encodeURIComponent(file.name),
                     await file.arrayBuffer());
    } catch (error) {
        message.textContent = error.message;
    } finally {
        button.disabled = false;
    }
};

async function poll() {
    try {
        await refresh();
    } catch (error) {
        message.textContent = "更新失敗：" + error.message;
    } finally {
        setTimeout(poll, 2000);
    }
}
poll();
</script>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def reply(self, data, code=200, html=False):
        raw = data.encode("utf-8") if html else json.dumps(
            data, ensure_ascii=False
        ).encode("utf-8")

        self.send_response(code)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8" if html
            else "application/json; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path

        if path == "/":
            self.reply(PAGE.replace("__TOKEN__", TOKEN), html=True)
        elif path == "/api/files":
            self.reply(vault.list_files())
        elif path == "/api/download":
            self.download_file()
        else:
            self.reply({"error": "找不到頁面"}, 404)


    def download_file(self):
        from urllib.parse import quote
        import os
        import stat

        try:
            name = parse_qs(
                urlsplit(self.path).query
            ).get("name", [""])[0]

            with vault.LOCK:
                with vault.connect() as db:
                    found = db.execute(
                        "SELECT 1 FROM files WHERE name = ?",
                        (name,)
                    ).fetchone()

                if found is None:
                    self.reply({"error": "找不到這個檔案"}, 404)
                    return

                target = vault.target_path(name)

                # 不跟隨符號連結，也不讓特殊檔案阻塞讀取。
                fd = os.open(
                    target,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                )

                with os.fdopen(fd, "rb") as f:
                    if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                        raise ValueError("只能下載一般檔案")

                    data = f.read(5 * 1024 * 1024 + 1)

                if len(data) > 5 * 1024 * 1024:
                    raise ValueError("檔案超過下載大小限制")

        except (OSError, ValueError) as error:
            self.reply({"error": str(error)}, 400)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header(
            "Content-Disposition",
            "attachment; filename*=UTF-8''" + quote(name, safe="")
        )
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.connection.settimeout(30)

        if not secrets.compare_digest(
            self.headers.get("X-Guardian-Token", ""), TOKEN
        ):
            self.close_connection = True
            self.reply({"error": "請重新整理網頁後再操作"}, 403)
            return

        try:
            route = urlsplit(self.path)
            name = parse_qs(route.query).get("name", [""])[0]
            size = int(self.headers.get("Content-Length", "0"))

            if not 0 <= size <= 5 * 1024 * 1024:
                self.close_connection = True
                self.reply({"error": "檔案超過大小限制"}, 413)
                return

            data = self.rfile.read(size)
            if len(data) != size:
                raise ValueError("上傳不完整，請重試")

            if route.path in ("/api/create", "/api/update"):
                # 檢查與寫入放在同一把鎖內，避免同時操作互相影響。
                with vault.LOCK:
                    with vault.connect() as db:
                        exists = db.execute(
                            "SELECT 1 FROM files WHERE name = ?",
                            (name,)
                        ).fetchone()

                    if route.path == "/api/create" and exists:
                        raise ValueError(
                            "此檔案已存在，請使用該卡片的「上傳修改版」"
                        )

                    if route.path == "/api/update" and not exists:
                        raise ValueError("指定檔案不存在，請重新整理網頁")

                    message = vault.upload(name, data)

            elif route.path == "/api/restore":
                message = vault.restore(name)

            elif route.path == "/api/delete":
                message = vault.delete_entry(name)
            else:
                self.reply({"error": "未知操作"}, 404)
                return

            self.reply({"message": message})

        except Exception as error:
            self.close_connection = True
            self.reply({"error": str(error)}, 400)


server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
print("上傳版本已啟動，連接埠：8080", flush=True)
server.serve_forever()
