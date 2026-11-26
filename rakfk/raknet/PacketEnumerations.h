/// \file
/// \brief All the packet identifiers used by RakNet.  Packet identifiers comprise the first byte of any message.
///
/// This file is part of RakNet Copyright 2003 Kevin Jenkins.
///
/// Usage of RakNet is subject to the appropriate license agreement.
/// Creative Commons Licensees are subject to the
/// license found at
/// http://creativecommons.org/licenses/by-nc/2.5/
/// Single application licensees are subject to the license found at
/// http://www.rakkarsoft.com/SingleApplicationLicense.html
/// Custom license users are subject to the terms therein.
/// GPL license users are subject to the GNU General Public
/// License as published by the Free
/// Software Foundation; either version 2 of the License, or (at your
/// option) any later version.

#ifndef __PACKET_ENUMERATIONS_H
#define __PACKET_ENUMERATIONS_H

#include "SAMP_VER.h"

enum PacketEnumeration
{
	ID_USER_INTERFACE_SYNC = 1,
	ID_UNOCCUPIED_SYNC = 2,
	ID_VEHICLE_SYNC = 3,
	ID_TURNLIGHTS_SYNC = 4,
	ID_PASSENGER_SYNC = 5,
	ID_AIM_SYNC = 6,
	ID_SPECTATOR_SYNC = 7,
	ID_STATS_UPDATE = 8,
	ID_PLAYER_SYNC = 9,
	ID_TRAILER_SYNC = 10,
	ID_WEAPONS_UPDATE = 11,
	ID_BULLET_SYNC = 12,
	ID_NEW_INCOMING_CONNECTION = 16,
	ID_CONNECTION_LOST = 17,
	ID_DISCONNECTION_NOTIFICATION = 18,
	ID_TIMESTAMP = 19,
	ID_CONNECTION_ATTEMPT_FAILED = 20,
	ID_MODIFIED_PACKET = 21,
	ID_NO_FREE_INCOMING_CONNECTIONS = 22,
	ID_CONNECTION_REQUEST_ACCEPTED = 23,
	ID_PONG = 24,
	ID_CONNECTION_BANNED = 25,
	ID_INVALID_PASSWORD = 26,
	ID_RPC = 29,
	ID_CONNECTED_PONG = 30,
	ID_PING = 31,
	ID_INTERNAL_PING = 32,
	ID_PING_OPEN_CONNECTIONS = 33,
	ID_DETECT_LOST_CONNECTIONS = 34,
	ID_AUTH_KEY = 35,
	ID_OPEN_CONNECTION_REQUEST = 36,
	ID_CONNECTION_REQUEST = 37,
	ID_OPEN_CONNECTION_REPLY = 38,
	ID_REQUEST_STATIC_DATA = 39,
	ID_SECURED_CONNECTION_RESPONSE = 40,
	ID_SECURED_CONNECTION_CONFIRMATION = 41,
	ID_RPC_MAPPING = 42,
	ID_RPC_REPLY = 43,
	ID_BROADCAST_PINGS = 44,
	ID_SET_RANDOM_NUMBER_SEED = 45,
	ID_RSA_PUBLIC_KEY_MISMATCH = 46,
	ID_RECEIVED_STATIC_DATA = 47,
	ID_REMOTE_DISCONNECTION_NOTIFICATION = 48,
	ID_REMOTE_CONNECTION_LOST = 49,
	ID_REMOTE_NEW_INCOMING_CONNECTION = 50,
	ID_REMOTE_EXISTING_CONNECTION = 51,
	ID_REMOTE_STATIC_DATA = 52,
	ID_OPEN_CONNECTION_COOKIE = 53,
	ID_ADVERTISE_SYSTEM = 53,
	ID_INVALID_PASS = 54,
	ID_RCON_COMMAND = 201,
	ID_RCON_RESPONCE = 202,
	ID_MARKERS_SYNC = 208,
};

#endif

