#!/bin/sh --init-file
# launcher.sh
# launch hub scripts at startup

cd /
cd home/pi/led-scripts/hub
sudo python3 keyPressTest4.py & sudo python3 serverTest3.py
cd /
