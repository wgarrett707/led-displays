import os, signal

def kill():
    f = open('/home/pi/led-scripts/hub/pidKill.txt', 'r')
    processIdentifier = f.read()
    os.kill(int(processIdentifier), signal.SIGKILL)
    f.close()
