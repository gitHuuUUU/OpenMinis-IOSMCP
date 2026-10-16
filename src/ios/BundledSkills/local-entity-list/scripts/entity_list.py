#!/usr/bin/env python3
"""Entity list enumerator"""
import sys
print("""[entity-list] Enumerate game entities
Steps:
1. Find local player health/position in Cheat Engine
2. "Find what accesses this address" -> get player base pointer
3. Look at surrounding memory for entity array/list
4. Map structure:
   +0x00: vtable/type
   +0x04: entity ID
   +0x08: health (float)
   +0x10: position X (float)
   +0x14: position Y (float)
   +0x18: position Z (float)
   +0x30: team (int)
   +0x40: name (char*)
   +0x50: isAlive (byte)

Unity: GameObject->GetComponent<Player>()
UE: GWorld->PersistentLevel->Actors
Source: IClientEntityList->GetClientEntity(i)
""")
