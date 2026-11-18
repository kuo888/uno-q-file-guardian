# UNO Q 檔案守護站

在 Arduino UNO Q 的 Linux 環境執行 Python 網頁服務，以 SHA-256 比較檔案內容，提供原始備份、背景監控、還原下載與刪除管理。Windows 電腦或手機透過同一區域網路的瀏覽器操作。

## 功能

- 新增受保護檔案：第一次上傳保存原始內容及 SHA-256 基準。
- 指定更新：在既有卡片上傳修改版，維持原本基準，不依所選來源檔名另建一筆。
- 背景監控：每輪檢查完等待 2 秒，檢查已登錄檔案的修改、刪除及讀取異常。
- 網頁更新：每次取得結果後等待 2 秒再更新。
- 還原並下載：驗證備份雜湊，還原板子上的實際檔案，重新驗證後提供下載。
- 刪除檔案與基準：先保存資料庫與檔案備份，再移除目前登錄項目。
- 事件紀錄：上傳、監控狀態變化與還原寫入 events.jsonl；目前刪除操作不額外寫入事件紀錄。

## 系統分工

| 元件 | 工作 |
| --- | --- |
| UNO Q Linux 端 | 執行 server.py、vault.py，保存檔案及 SQLite 資料庫 |
| Windows／手機瀏覽器 | 選檔、顯示狀態、提交更新與還原要求、下載檔案 |
| SHA-256 | 判斷位元組內容是否與原始基準一致 |
| SQLite | 保存原始內容、雜湊與登錄狀態 |

## 環境與啟動

目標平台為 UNO Q 的 Linux 系統。開發時使用 Python 3.13.5，全部使用 Python 標準函式庫，無需 pip 安裝。下載功能使用 Linux 檔案旗標，不以原生 Windows 作為伺服器平台。

將本專案放入板子的 `~/uno-file-guardian`，在 SSH 終端執行：

```bash
cd ~/uno-file-guardian
python3 server.py
```

瀏覽器開啟 `http://板子的IP:8080`。板子 IP 可在 SSH 中以 `hostname -I` 查詢。程式監聽 0.0.0.0:8080；0.0.0.0 不是瀏覽器要輸入的遠端位址。

按 Ctrl+C 停止。此版本沒有設定開機自動啟動，停止程式或 SSH 工作階段結束可能中止服務。

## 專案檔案

- `server.py`：HTTP API、HTML／JavaScript 介面與下載。
- `vault.py`：SQLite、檔案讀寫、雜湊比對、還原與背景執行緒。
- `examples/device-demo.txt`：可公開的原始測試資料。
- `examples/device-demo-modified.txt`：供「上傳修改版」操作的測試資料。
- `DEMO.md`：示範影片步驟及講稿。
- `.gitignore`：排除執行資料、備份及私人檔案。

執行時自動產生 `protected/`、`vault.sqlite3`。事件另存 `events.jsonl`，刪除前備份存 `deleted-backups/`。這些資料不應提交 GitHub。

## 操作方式

1. 在新增區上傳 examples/device-demo.txt，顯示正常並建立基準。
2. 在該卡片按「上傳修改版」，選 examples/device-demo-modified.txt，確認更新對象後顯示已修改。
3. 按「還原並下載」，確認狀態恢復正常，開啟剛下載的檔案檢查內容。
4. 不需要某筆資料時，按「刪除檔案與基準」，確認檔名後移除。

新增區只拒絕完全相同的既有檔名，不會自動合併帶 (1)、(2) 的檔案。更新請使用指定卡片的按鈕。

下載不會自動覆蓋 Windows 的原檔，瀏覽器可能為同名下載加上編號。還原的對象是 UNO Q 裡的檔案。

## 背景監控示範

先透過網頁登錄 device-demo.txt，保持 server.py 執行。從第二個 SSH 工作階段執行：

```bash
cd ~/uno-file-guardian
echo '測試：直接修改板子上的檔案' >> protected/device-demo.txt
```

不用重新上傳，監控終端應記錄變化，網頁會在後續更新中顯示已修改。還原後執行：

```bash
cat protected/device-demo.txt
tail -n 10 events.jsonl
```

只監控已登錄檔案；直接在資料夾建立任意新檔，不會自動加入基準。

## 限制

- 單一上傳及下載上限 5 MiB，尚未設定整體容量限制。
- 只有 HTTP，沒有帳號登入或權限分級，限可信任區域網路與非敏感示範資料使用。
- 每次啟動隨機產生的請求 token 不是帳號認證或私人 API 金鑰；有網頁存取權的人可取得它。
- 原始備份與檔案位於同一塊板子，無法防止整機損壞或具主機權限者同時竄改資料與基準。
- SHA-256 比對不會指出修改的文字位置、修改者或是否惡意。Word 內部資訊改變也可能造成雜湊不同。
- 程式只檢查內容，不保存完整權限、時間戳等檔案中繼資料。
- 偵測採輪詢，不能保證捕捉兩輪之間短暫修改後又恢復的狀況，也未提供固定最壞反應時間。
- 刪除前保留的備份需人工管理，不等同永久抹除。

## 技術參考

- Python HTTP server：https://docs.python.org/3/library/http.server.html
- Python hashlib：https://docs.python.org/3/library/hashlib.html
- Python sqlite3：https://docs.python.org/3/library/sqlite3.html
- Python threading：https://docs.python.org/3/library/threading.html
