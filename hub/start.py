#!/usr/bin/env python3.7

import pty

pty.spawn('sudo python3 /home/pi/led-scripts/hub/keyPressTest4.py & sudo python3 /home/pi/led-scripts/hub/serverTest3.py')
