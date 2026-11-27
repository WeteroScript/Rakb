#ifndef SAMP_AUTH_037_H
#define SAMP_AUTH_037_H

// SA-MP 0.3.7 auth-key response (ID_AUTH_KEY). Ported from a working 0.3.7
// client; the 0.3.DL variant used a different hash and gets rejected.
void gen_auth_key(char buf[260], const char* auth_in);

#endif
