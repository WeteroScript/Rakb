/*
	SA-MP 0.3.7 auth-key algorithm.

	The server sends ID_AUTH_KEY with a random string; the client answers with
	SHA1(string) transformed byte-wise and hex-encoded. Ported from a working
	0.3.7 client reference. Fixed-width types keep this correct on Linux/ARM
	(where unsigned long is 8 bytes, unlike the original Windows build).
*/
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "samp_auth_037.h"

typedef unsigned char BYTE;

// --- SHA1 (standard, 32-bit words) ---
static uint32_t rotl32(uint32_t v, int s)
{
	return (v << s) | (v >> (32 - s));
}

static void samp_auth_sha1(const char* message, uint32_t out[5])
{
	uint32_t h0 = 0x67452301, h1 = 0xEFCDAB89, h2 = 0x98BADCFE,
	         h3 = 0x10325476, h4 = 0xC3D2E1F0;

	size_t len = strlen(message);
	uint64_t bitlen = (uint64_t)len * 8;

	// padding: 0x80, zeroes, 64-bit big-endian bit length
	size_t padded = len + 1;
	while (padded % 64 != 56)
		padded++;
	padded += 8;

	unsigned char* msg = new unsigned char[padded];
	memset(msg, 0, padded);
	memcpy(msg, message, len);
	msg[len] = 0x80;
	for (int i = 0; i < 8; i++)
		msg[padded - 1 - i] = (unsigned char)(bitlen >> (8 * i));

	for (size_t off = 0; off < padded; off += 64)
	{
		uint32_t w[80];
		for (int i = 0; i < 16; i++)
		{
			// big-endian word, memcpy keeps unaligned loads ARM-safe
			uint32_t v;
			memcpy(&v, msg + off + i * 4, 4);
			w[i] = ((v & 0xFF) << 24) | ((v & 0xFF00) << 8) |
			       ((v >> 8) & 0xFF00) | ((v >> 24) & 0xFF);
		}
		for (int i = 16; i < 80; i++)
			w[i] = rotl32(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);

		uint32_t a = h0, b = h1, c = h2, d = h3, e = h4;
		for (int i = 0; i < 80; i++)
		{
			uint32_t f, k;
			if (i < 20)      { f = (b & c) | ((~b) & d);            k = 0x5A827999; }
			else if (i < 40) { f = b ^ c ^ d;                       k = 0x6ED9EBA1; }
			else if (i < 60) { f = (b & c) | (b & d) | (c & d);     k = 0x8F1BBCDC; }
			else             { f = b ^ c ^ d;                       k = 0xCA62C1D6; }
			uint32_t temp = rotl32(a, 5) + f + e + k + w[i];
			e = d; d = c; c = rotl32(b, 30); b = a; a = temp;
		}
		h0 += a; h1 += b; h2 += c; h3 += d; h4 += e;
	}
	delete[] msg;

	out[0] = h0; out[1] = h1; out[2] = h2; out[3] = h3; out[4] = h4;
}

// --- 0.3.7 auth transforms ---

// after version change, may need to dump this again, but wasn't changed yet afaik
static const BYTE auth_hash_transform_table[100] = {
	0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
	0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x80,
	0x08, 0x06, 0x00, 0x00, 0x00, 0xE4, 0xB5, 0xB7, 0x0A, 0x00, 0x00, 0x00,
	0x09, 0x70, 0x48, 0x59, 0x73, 0x00, 0x00, 0x0B, 0x13, 0x00, 0x00, 0x0B,
	0x13, 0x01, 0x00, 0x9A, 0x9C, 0x18, 0x00, 0x00, 0x00, 0x04, 0x67, 0x41,
	0x4D, 0x41, 0x00, 0x00, 0xB1, 0x8E, 0x7C, 0xFB, 0x51, 0x93, 0x00, 0x00,
	0x00, 0x20, 0x63, 0x48, 0x52, 0x4D, 0x00, 0x00, 0x7A, 0x25, 0x00, 0x00,
	0x80, 0x83, 0x00, 0x00, 0xF9, 0xFF, 0x00, 0x00, 0x80, 0xE9, 0x00, 0x00,
	0x75, 0x30, 0x00, 0x00
};

static BYTE transform_auth_sha1(BYTE value, BYTE xorv)
{
	BYTE result = value;
	for (BYTE i = 0; i < 100; i++)
		result = result ^ auth_hash_transform_table[i] ^ xorv;
	return result;
}

// CAnimManager::AddAnimation has been hooked by kye, but resolved jmp address isn't in samp.dll
static const BYTE code_from_CAnimManager_AddAnimation[20] = {
	0xFF, 0x25, 0x34, 0x39, // gta_sa.exe + 0x4D3AA0
	0x4D, 0x00, 0x90, 0x90, // gta_sa.exe + 0x4D3AA4
	0x90, 0x90, 0x56, 0x57, // gta_sa.exe + 0x4D3AAC
	0x50, 0x8B, 0x44, 0x24, // gta_sa.exe + 0x4D3AA8
	0x14, 0x8D, 0x0C, 0x80  // gta_sa.exe + 0x4D3AB0
};

static char samp_sub_100517E0(BYTE a1)
{
	char result = a1 + '0';
	if (a1 + '0' > '9')
		result = a1 + '7';
	return result;
}

static void auth_stringify(char* out, const BYTE hash[20])
{
	for (int i = 0; i < 20; i++)
	{
		out[i * 2]     = samp_sub_100517E0(hash[i] >> 4);
		out[i * 2 + 1] = samp_sub_100517E0(hash[i] & 0xF);
	}
	out[40] = 0;
}

void gen_auth_key(char buf[260], const char* auth_in)
{
	if (!auth_in)
	{
		buf[0] = 0;
		return;
	}

	uint32_t out[5];
	samp_auth_sha1(auth_in, out);
	BYTE* pb_out = (BYTE*)out;

	for (BYTE i = 0; i < 5; i++)   pb_out[i] = transform_auth_sha1(pb_out[i], 0x2F);
	for (BYTE i = 5; i < 10; i++)  pb_out[i] = transform_auth_sha1(pb_out[i], 0x45);
	for (BYTE i = 10; i < 15; i++) pb_out[i] = transform_auth_sha1(pb_out[i], 0x6F);
	for (BYTE i = 15; i < 20; i++) pb_out[i] = transform_auth_sha1(pb_out[i], 0xDB);
	for (BYTE i = 0; i < 20; i++)  pb_out[i] ^= code_from_CAnimManager_AddAnimation[i];

	auth_stringify(buf, pb_out);
}
