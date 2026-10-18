#!/usr/bin/env python3.7
print('testing')
import subprocess
print('testing2')
# Program shown at boot; Esc goes to the menu. Set to '' to boot to the menu instead.
BOOT_PROGRAM = 'lyrics'
if BOOT_PROGRAM:
    subprocess.run('sudo python3 /home/pi/led-scripts/hub/serverTest3.py ' + BOOT_PROGRAM, shell=True)
else:
    subprocess.run('sudo python3 /home/pi/led-scripts/hub/keyPressTest4.py & sudo python3 /home/pi/led-scripts/hub/serverTest3.py', shell=True)
