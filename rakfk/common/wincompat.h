/*
    wincompat.h - Win32 -> POSIX compatibility surface for the headless Linux port.

    The RakSAMP client was written against Win32 (WinMain, windows.h, the _s CRT,
    GDI dialogs). RakNet underneath is already cross-platform. This header supplies
    just enough of the Win32 type/function surface for the client logic to compile
    and run headless on Linux:

      - scalar/handle types (BYTE/WORD/DWORD/BOOL/HWND/...) with Win32-correct widths
      - the secure CRT (_s) functions mapped onto the POSIX/snprintf equivalents
      - timing (GetTickCount/Sleep/GetLocalTime) on clock_gettime/nanosleep
      - a Winsock shim (SOCKET, WSAStartup, recvfrom int* overload) for rcon.cpp
      - no-op GUI stubs so the few non-guarded GUI calls link; the heavy GUI
        (window.cpp, the dialog thread, the teleport menu) is #ifdef _WIN32'd out
        and replaced with stdout logging in the port.

    DWORD is deliberately `unsigned int` (4 bytes): the packed SA-MP sync structs
    and RakNet BitStream writes depend on it being 32-bit, not Linux's 64-bit long.
*/
#ifndef RAKB_WINCOMPAT_H
#define RAKB_WINCOMPAT_H

#ifdef _WIN32
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #include <windows.h>
    #include <commctrl.h>
    #include <conio.h>
    #include <io.h>
    #include <tchar.h>
#else

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdarg>
#include <ctime>
#include <cmath>
#include <cerrno>
#include <unistd.h>
#include <pthread.h>
#include <signal.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>

/* MSVC fixed-width integer keywords used by the SAMP netcode (kyretardize, etc.) */
#define __int8  char
#define __int16 short
#define __int32 int
#define __int64 long long

/* ---- scalar types (Win32-correct widths) ---- */
typedef unsigned char       BYTE;
typedef unsigned short      WORD;
typedef unsigned int        DWORD;   /* 32-bit, NOT unsigned long (64-bit on Linux) */
typedef int                 BOOL;
typedef float               FLOAT;
typedef char                CHAR;
typedef unsigned char       UCHAR;
typedef char                TCHAR;
typedef char*               LPSTR;
typedef const char*         LPCSTR;
typedef char*               LPTSTR;
typedef const char*         LPCTSTR;
typedef char*               PCHAR;
typedef unsigned char*      PUCHAR;
typedef BYTE*               PBYTE;
typedef WORD*               PWORD;
typedef DWORD*              PDWORD;
typedef void*               PVOID;
typedef void*               LPVOID;
typedef const void*         LPCVOID;
typedef unsigned int        UINT;
typedef int                 INT;
typedef short               SHORT;
typedef unsigned short      USHORT;
typedef long                LONG;
typedef unsigned long       ULONG;
typedef long long           LONGLONG;
typedef unsigned long long  ULONGLONG;
typedef size_t              SIZE_T;

/* ---- handle types (opaque, headless) ---- */
typedef void*   HANDLE;
typedef void*   HWND;
typedef void*   HDC;
typedef void*   HINSTANCE;
typedef void*   HMODULE;
typedef void*   HFONT;
typedef void*   HBRUSH;
typedef void*   HICON;
typedef void*   HCURSOR;
typedef void*   HMENU;
typedef void*   HGDIOBJ;
typedef void*   HGLOBAL;
typedef void*   HBITMAP;
typedef void*   HPEN;
typedef void*   HRGN;
typedef void*   HKEY;
typedef uintptr_t WPARAM;
typedef intptr_t  LPARAM;
typedef intptr_t  LRESULT;
typedef unsigned short ATOM;
typedef DWORD   COLORREF;

#ifndef TRUE
#define TRUE 1
#endif
#ifndef FALSE
#define FALSE 0
#endif
#ifndef MAX_PATH
#define MAX_PATH 260
#endif
#define WINAPI
#define CALLBACK
#define APIENTRY
#define __cdecl
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define MAXDWORD 0xFFFFFFFFu

#define LOWORD(l) ((WORD)(((DWORD)(l)) & 0xFFFF))
#define HIWORD(l) ((WORD)((((DWORD)(l)) >> 16) & 0xFFFF))
#define LOBYTE(w) ((BYTE)(((WORD)(w)) & 0xFF))
#define HIBYTE(w) ((BYTE)((((WORD)(w)) >> 8) & 0xFF))
#define MAKEWORD(a,b) ((WORD)(((BYTE)(a)) | ((WORD)((BYTE)(b))) << 8))
#define RGB(r,g,b) ((COLORREF)(((BYTE)(r)) | ((WORD)((BYTE)(g)) << 8) | ((DWORD)((BYTE)(b)) << 16)))

/* ---- minimal structs referenced by non-guarded code ---- */
typedef struct _RECT { LONG left, top, right, bottom; } RECT;
typedef struct _POINT { LONG x, y; } POINT;
typedef struct _SYSTEMTIME {
    WORD wYear, wMonth, wDayOfWeek, wDay, wHour, wMinute, wSecond, wMilliseconds;
} SYSTEMTIME;
typedef struct _MSG { HWND hwnd; UINT message; WPARAM wParam; LPARAM lParam; DWORD time; POINT pt; } MSG;
typedef struct _PAINTSTRUCT { HDC hdc; BOOL fErase; RECT rcPaint; BOOL fRestore; BOOL fIncUpdate; BYTE rgbReserved[32]; } PAINTSTRUCT;
typedef struct tagWNDCLASSEX {
    UINT cbSize; UINT style; void* lpfnWndProc; int cbClsExtra; int cbWndExtra;
    HINSTANCE hInstance; HICON hIcon; HCURSOR hCursor; HBRUSH hbrBackground;
    const char* lpszMenuName; const char* lpszClassName; HICON hIconSm;
} WNDCLASSEX;

/* a few list-box message ids used by the console-log path in main.cpp */
#ifndef LB_ADDSTRING
#define LB_ADDSTRING    0x0180
#define LB_GETCOUNT     0x018B
#define LB_SETCURSEL    0x0186
#define LB_SETTOPINDEX  0x0197
#define WM_DESTROY      0x0002
#endif

/* MessageBox flags */
#define MB_OK           0x00000000
#define MB_ICONERROR    0x00000010
#define MB_ICONHAND     0x00000010
#define MB_ICONWARNING  0x00000030
#define MB_ICONINFORMATION 0x00000040

/* ---- secure CRT (_s) mapped onto snprintf family ---- */
inline int sprintf_s(char* buf, size_t size, const char* fmt, ...) {
    va_list ap; va_start(ap, fmt); int r = vsnprintf(buf, size, fmt, ap); va_end(ap); return r;
}
template <size_t N> inline int sprintf_s(char (&buf)[N], const char* fmt, ...) {
    va_list ap; va_start(ap, fmt); int r = vsnprintf(buf, N, fmt, ap); va_end(ap); return r;
}
inline int vsprintf_s(char* buf, size_t size, const char* fmt, va_list ap) {
    return vsnprintf(buf, size, fmt, ap);
}
inline int strcpy_s(char* dst, size_t size, const char* src) {
    if (!dst || !size) return EINVAL;
    if (!src) { dst[0] = 0; return EINVAL; }
    strncpy(dst, src, size - 1); dst[size - 1] = 0; return 0;
}
template <size_t N> inline int strcpy_s(char (&dst)[N], const char* src) { return strcpy_s(dst, N, src); }
inline int strcat_s(char* dst, size_t size, const char* src) {
    if (!dst || !size) return EINVAL;
    size_t l = strlen(dst); if (l >= size) return EINVAL;
    strncpy(dst + l, src, size - l - 1); dst[size - 1] = 0; return 0;
}
template <size_t N> inline int strcat_s(char (&dst)[N], const char* src) { return strcat_s(dst, N, src); }
#ifndef _snprintf
#define _snprintf  snprintf
#endif
#ifndef _vsnprintf
#define _vsnprintf vsnprintf
#endif
#define wsprintf   sprintf
#define sscanf_s   sscanf
#define _stricmp   strcasecmp
#define _strnicmp  strncasecmp
#define stricmp    strcasecmp
#define strnicmp   strncasecmp
#define _finite    isfinite
#define _copysign  copysign
#define _hypot     hypot

/* ---- timing ---- */
inline DWORD GetTickCount() {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (DWORD)((uint64_t)ts.tv_sec * 1000ULL + (uint64_t)ts.tv_nsec / 1000000ULL);
}
inline void Sleep(DWORD ms) {
    struct timespec ts; ts.tv_sec = ms / 1000; ts.tv_nsec = (long)(ms % 1000) * 1000000L;
    nanosleep(&ts, NULL);
}
inline void GetLocalTime(SYSTEMTIME* st) {
    struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
    struct tm tmv; localtime_r(&ts.tv_sec, &tmv);
    st->wYear = (WORD)(tmv.tm_year + 1900); st->wMonth = (WORD)(tmv.tm_mon + 1);
    st->wDayOfWeek = (WORD)tmv.tm_wday; st->wDay = (WORD)tmv.tm_mday;
    st->wHour = (WORD)tmv.tm_hour; st->wMinute = (WORD)tmv.tm_min;
    st->wSecond = (WORD)tmv.tm_sec; st->wMilliseconds = (WORD)(ts.tv_nsec / 1000000);
}

/* ---- process / module ---- */
inline void ExitProcess(int code) { exit(code); }
inline HMODULE GetModuleHandle(const char* = NULL) { return (HMODULE)0; }
inline DWORD GetCurrentThreadId() { return (DWORD)(uintptr_t)pthread_self(); }
inline DWORD GetModuleFileName(HMODULE, char* buf, DWORD size) {
    ssize_t n = readlink("/proc/self/exe", buf, size ? size - 1 : 0);
    if (n < 0) { if (size) buf[0] = 0; return 0; }
    buf[n] = 0; return (DWORD)n;
}
inline int MessageBox(HWND, const char* text, const char* caption, UINT) {
    fprintf(stderr, "[MessageBox] %s: %s\n", caption ? caption : "", text ? text : "");
    return 0;
}
/* Reconstruct the command line so -h/-p/-n/-z server overrides keep working. */
inline PCHAR GetCommandLineA() {
    static char buf[4096];
    static bool init = false;
    if (!init) {
        init = true; buf[0] = 0;
        FILE* f = fopen("/proc/self/cmdline", "rb");
        if (f) {
            size_t n = fread(buf, 1, sizeof(buf) - 1, f);
            fclose(f);
            for (size_t i = 0; i < n; i++) if (buf[i] == 0) buf[i] = ' ';
            while (n && buf[n - 1] == ' ') --n;
            buf[n] = 0;
        }
    }
    return buf;
}
inline BOOL SetConsoleTitle(const char*) { return TRUE; }

/* ---- threads: GUI worker threads are neutered headless ---- */
typedef DWORD (*LPTHREAD_START_ROUTINE)(PVOID);
inline HANDLE CreateThread(void*, size_t, LPTHREAD_START_ROUTINE, PVOID, DWORD, DWORD*) {
    /* Headless build never runs the Win32 GUI worker threads (dialog/teleport).
       The console input thread is created with pthreads directly in console.cpp. */
    return (HANDLE)0;
}
inline BOOL TerminateThread(HANDLE, DWORD) { return TRUE; }
inline BOOL CloseHandle(HANDLE) { return TRUE; }
inline DWORD WaitForSingleObject(HANDLE, DWORD) { return 0; }

/* ---- no-op GUI surface for the few non-guarded call sites ---- */
inline BOOL SetWindowText(HWND, const char*) { return TRUE; }
inline LRESULT SendMessage(HWND, UINT, WPARAM, LPARAM) { return 0; }
inline BOOL PostMessage(HWND, UINT, WPARAM, LPARAM) { return TRUE; }
inline void PostQuitMessage(int) {}
inline BOOL ShowWindow(HWND, int) { return TRUE; }
inline BOOL UpdateWindow(HWND) { return TRUE; }
inline BOOL DestroyWindow(HWND) { return TRUE; }
inline BOOL UnregisterClass(const char*, HINSTANCE) { return TRUE; }
inline BOOL SetForegroundWindow(HWND) { return TRUE; }
inline HWND GetConsoleWindow() { return (HWND)0; }
inline BOOL GetWindowRect(HWND, RECT* r) { if (r) { r->left = r->top = r->right = r->bottom = 0; } return FALSE; }
inline BOOL GetClientRect(HWND, RECT* r) { if (r) { r->left = r->top = r->right = r->bottom = 0; } return FALSE; }
inline HWND GetDlgItem(HWND, int) { return (HWND)0; }
inline int GetWindowText(HWND, char* buf, int max) { if (max) buf[0] = 0; return 0; }

/* ---- Winsock shim for rcon.cpp ---- */
typedef int SOCKET;
#ifndef INVALID_SOCKET
#define INVALID_SOCKET (-1)
#endif
#ifndef SOCKET_ERROR
#define SOCKET_ERROR (-1)
#endif
typedef struct _WSADATA { int _dummy; } WSADATA;
inline int WSAStartup(WORD, WSADATA*) { return 0; }
inline int WSACleanup() { return 0; }
#ifndef closesocket
#define closesocket close
#endif
/* rcon.cpp passes `int*` as the address length; POSIX wants socklen_t*. */
inline ssize_t recvfrom(int fd, void* buf, size_t len, int flags, sockaddr* addr, int* addrlen) {
    socklen_t l = addrlen ? (socklen_t)*addrlen : 0;
    ssize_t r = ::recvfrom(fd, buf, len, flags, addr, addrlen ? &l : NULL);
    if (addrlen) *addrlen = (int)l;
    return r;
}

#endif /* _WIN32 */
#endif /* RAKB_WINCOMPAT_H */
