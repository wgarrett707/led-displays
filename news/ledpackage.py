from datetime import datetime
import time

numScripts = {'hub' : 1,
              'stocks' : 2,
              'news' : 1,
              'weather' : 1,
              'discord' : 2,
              'subs' : 1}

path = '/home/pi/led-scripts/hub/'

def localPID(name, pid):
    f = open(path + name + 'local.txt', 'w')
    f.write(pid)
    f.close()
    return

def recordPID(name, pid):
    scripts = numScripts[name]
    morePath = path + name
    if scripts == 1:
        f = open(morePath + '.txt', 'w')
        f.write(pid)
        f.close()
        return
    else:
        while True:
            f = open(morePath + 'local.txt', 'r')
            content = f.read()
            f.close()
            if content:
                f2 = open(morePath + '.txt', 'w')
                f2.writelines([pid, '\n' + content])
                f2.close()
                f3 = open(morePath + 'local.txt', 'w')
                f3.writelines([])
                f3.close()
                return
            else:
                time.sleep(1)

# ARGUMENTS:
# 'minutes' is the number of minutes on the clock as of when the function is called.
# 'interval' is an integer representing how many minutes to wait.
def waitAMinute(minutes, interval):
    waitUntil = minutes + interval
    if waitUntil >= 60:
        waitUntil -= 60
    while True:
        if datetime.now().minute == waitUntil:
            print(str(interval) + ' minute(s) waited.')
            return
        else:
            time.sleep(0.5)

                
            
        
