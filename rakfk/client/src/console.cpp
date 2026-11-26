/*
    Updated to 0.3.7 by P3ti
    Linux headless port: the console input thread becomes a stdin -> RunCommand
    control channel. The supervising Telegram bot writes commands to our stdin and
    reads our stdout log. On Windows the original AllocConsole/ReadConsole path is
    kept unchanged.
*/

#include "main.h"

#ifdef _WIN32

#include <fcntl.h>
#include <io.h>
#include <iostream>
#include <fstream>

char szInputBuffer[512];

DWORD WINAPI inputThread(PVOID p)
{
	HANDLE hStdInput = GetStdHandle(STD_INPUT_HANDLE);
	DWORD dwRead;

	while(1)
	{
		memset(szInputBuffer, 0, 512);

		SetConsoleMode(hStdInput, ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT | ENABLE_PROCESSED_INPUT);
		FlushConsoleInputBuffer(hStdInput);
		ReadConsole(hStdInput, szInputBuffer, 512, &dwRead, NULL);

		RunCommand(szInputBuffer, 0);

		Sleep(5);
	}

	return 0;
}

BOOL CtrlHandler(DWORD fdwCtrlType)
{
	switch(fdwCtrlType)
	{
		case CTRL_C_EVENT:
		case CTRL_CLOSE_EVENT:
		case CTRL_BREAK_EVENT:
		case CTRL_LOGOFF_EVENT:
		case CTRL_SHUTDOWN_EVENT:
			sampDisconnect(0);
			ExitProcess(0);
			return TRUE;

		default:
			return FALSE;
	}
}

void SetUpConsole()
{
	int hConHandle;
	long lStdHandle;
	FILE *fp;

	AllocConsole();

	// output
	lStdHandle = (long)GetStdHandle(STD_OUTPUT_HANDLE);
	hConHandle = _open_osfhandle(lStdHandle, _O_TEXT);
	fp = _fdopen( hConHandle, "w" );
	*stdout = *fp;
	setvbuf( stdout, NULL, _IONBF, 0 );

	// input
	lStdHandle = (long)GetStdHandle(STD_INPUT_HANDLE);
	hConHandle = _open_osfhandle(lStdHandle, _O_TEXT);
	fp = _fdopen( hConHandle, "r" );
	*stdin = *fp;
	setvbuf( stdin, NULL, _IONBF, 0 );

	// error
	lStdHandle = (long)GetStdHandle(STD_ERROR_HANDLE);
	hConHandle = _open_osfhandle(lStdHandle, _O_TEXT);
	fp = _fdopen( hConHandle, "w" );
	*stderr = *fp;
	setvbuf( stderr, NULL, _IONBF, 0 );

	std::ios::sync_with_stdio();

	SetConsoleTitle("RakSAMP " RAKSAMP_VERSION);
	CreateThread(NULL, 0, inputThread, NULL, 0, NULL);

	SetConsoleCtrlHandler((PHANDLER_ROUTINE)CtrlHandler, TRUE);
}

#else /* ---- Linux / POSIX headless ---- */

#include <pthread.h>
#include <signal.h>
#include <string.h>
#include <stdio.h>

static char szInputBuffer[512];

static void* inputThread(void*)
{
	while (fgets(szInputBuffer, sizeof(szInputBuffer), stdin) != NULL)
	{
		size_t len = strlen(szInputBuffer);
		while (len && (szInputBuffer[len - 1] == '\n' || szInputBuffer[len - 1] == '\r'))
			szInputBuffer[--len] = 0;

		if (len == 0)
			continue;

		/* RunCommand() in console mode trims the trailing two bytes (it was written
		   for ReadConsole's CRLF). Re-append CRLF so that trim is correct. */
		if (len + 2 < sizeof(szInputBuffer))
		{
			szInputBuffer[len]     = '\r';
			szInputBuffer[len + 1] = '\n';
			szInputBuffer[len + 2] = 0;
		}

		RunCommand(szInputBuffer, 0);
	}
	return NULL;
}

static void ctrlHandler(int)
{
	sampDisconnect(0);
	ExitProcess(0);
}

void SetUpConsole()
{
	/* Line-buffer stdout so the supervisor receives each log line immediately even
	   though our stdout is a pipe, not a tty. */
	setvbuf(stdout, NULL, _IOLBF, 0);

	signal(SIGINT,  ctrlHandler);
	signal(SIGTERM, ctrlHandler);
	signal(SIGPIPE, SIG_IGN);

	pthread_t t;
	pthread_create(&t, NULL, inputThread, NULL);
	pthread_detach(t);
}

/* Linux entry point: forward to the original WinMain() in main.cpp. */
int WinMain(HINSTANCE, HINSTANCE, LPSTR, int);
int main(int argc, char** argv)
{
	(void)argc; (void)argv;
	return WinMain((HINSTANCE)0, (HINSTANCE)0, (LPSTR)0, 0);
}

#endif /* _WIN32 */
