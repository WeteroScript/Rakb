/*
    window_linux.cpp - headless stubs for the Win32 GUI globals/functions that the
    rest of the client references. The real GUI lives in window.cpp (#ifdef _WIN32).
    On Linux there is no window: SetUpWindow is a no-op and the teleport menu is
    rendered as text by misc_funcs.cpp.
*/
#include "main.h"

#ifndef _WIN32

HWND      hwnd = 0, texthwnd = 0, loghwnd = 0, inputhwnd = 0;
HINSTANCE g_hInst = 0;

BOOL   bTeleportMenuActive = 0;
HFONT  hTeleportMenuFont = 0;
HANDLE hTeleportMenuThread = 0;
HWND   hwndTeleportMenu = 0;

void SetUpWindow(HINSTANCE) { /* headless: no window */ }

LRESULT CALLBACK TeleportMenuProc(HWND, UINT, WPARAM, LPARAM) { return 0; }
DWORD   WINAPI   TeleportMenuThread(PVOID) { return 0; }

#endif /* !_WIN32 */
