#pragma once
#include "mock_ethernet.h"

// EthernetUDP is the global mock type; expose it as the class name the .ino uses
using EthernetUDP = MockEthernetUDP;
