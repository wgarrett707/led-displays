#!/usr/bin/env python3.7
print('testing')
import subprocess
print('testing2')
subprocess.run('sudo python3 /home/pi/led-scripts/hub/keyPressTest4.py & sudo python3 /home/pi/led-scripts/hub/serverTest3.py', shell=True)
