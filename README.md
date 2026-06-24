# FLH SPC 統計製程管制監控台

## 安裝步驟（新電腦）

### 步驟 1：安裝必要軟體

1. 安裝 **Python**
   - 前往 https://www.python.org/downloads/
   - 點選最新版本下載並執行
   - ⚠️ 安裝時務必勾選 **"Add Python to PATH"**
   - 點 Install Now

2. 安裝 **Git**
   - 前往 https://git-scm.com/download/win
   - 下載並執行，一路點 Next 即可

---

### 步驟 2：Clone 專案

1. 在桌面空白處按右鍵 → **Open Git Bash here**
   （或開啟「開始」→ 搜尋 Git Bash → 開啟）

2. 在 Git Bash 輸入以下指令，按 Enter：

```bash
cd ~/Desktop
git clone https://github.com/hanchiho-84/flh-spc-dashboard.git
```

3. 等待下載完成，桌面會出現 `flh-spc-dashboard` 資料夾

---

### 步驟 3：安裝 Python 套件

在 Git Bash 繼續輸入：

```bash
cd flh-spc-dashboard
pip install pdfplumber lxml
```

等待安裝完成（約 1-2 分鐘）

---

### 步驟 4：啟動程式

1. 開啟 `flh-spc-dashboard` 資料夾
2. 雙擊 **`啟動伺服器.bat`**
3. 瀏覽器會自動開啟監控台
4. 桌面會自動建立「啟動SPC監控台」捷徑，之後直接點捷徑即可

---

## 注意事項

- 電腦需連接公司內網或 VPN，確保 `W:` 磁碟機可以存取
- 如果 `W:` 路徑不同，請修改 `server.py` 開頭的路徑設定：
  ```python
  W_DATA_FOLDER = r'W:\MFG\public\SPC raw data\CSV\Backup'
  W_XML_FOLDER  = r'W:\MFG\public\SPC raw data\XML\Backup'
  ```

## 更新程式

程式有更新時，在 Git Bash 執行：

```bash
cd ~/Desktop/flh-spc-dashboard
git pull
```
