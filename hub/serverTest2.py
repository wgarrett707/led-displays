import sys, os
import termios, fcntl
import select
import time
import subprocess
import signal

K_LEFT = '\033[D'
K_RIGHT = '\033[C'
K_ENTER = '\n'
K_ESC = 27

numScripts = [2, 1, 1, 1, 1]
starts = {'stocks' : 'nice -n 10 sudo python3 /home/pi/led-scripts/stocks/FinnhubGeneratorFix2.py & nice -n -20 sudo python3 /home/pi/led-scripts/stocks/logoviewer12.py',
          'news' : 'sudo python3 /home/pi/led-scripts/news/getnews7.py',
          'weather' : 'sudo python3 /home/pi/led-scripts/weather/Generator3.py',
          'discord' : 'nice -n 10 sudo python3 /home/pi/led-scripts/discord/Generator4.py & nice -n -20 sudo python3 /home/pi/led-scripts/discord/logoviewer13.py',
          'subs' : 'sudo python3 /home/pi/led-scripts/subs/subs2.py'}

def sendInput(key):
    print('serverTest2: entered sendInput')
    f = open('/home/pi/led-scripts/hub/input.txt', 'w')
    print('serverTest2: opened file')
    f.write(str(time.time()) + '\n' + key)
    print('serverTest2: wrote to file')
    f.close()
    print('serverTest2: closed file')
    return

def keySettings():
    fd = sys.stdin.fileno()
    oldterm = termios.tcgetattr(fd)
    newattr = termios.tcgetattr(fd)
    newattr[3] = newattr[3] & ~termios.ICANON
    newattr[3] = newattr[3] & ~termios.ECHO
    termios.tcsetattr(fd, termios.TCSANOW, newattr)
    oldflags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, oldflags | os.O_NONBLOCK)

    return fd, oldterm, oldflags

def revertSettings(fd, oldterm, oldflags):
    termios.tcsetattr(fd, termios.TCSANOW, oldterm)
    fcntl.fcntl(fd, fcntl.F_SETFL, oldflags)
    quit()

def killScripts(program):
    #if program != 'hub':
        #time.sleep(5)
    f = open('/home/pi/led-scripts/hub/' + program + '.txt', 'r')
    pIDs = f.readlines()
    f.close()
    for process in pIDs:
        os.kill(int(process), signal.SIGKILL)
        print('Killed: ' + process)
    # Testing subprocess
    if program != 'hub':
        print('Running hub script...')
        subprocess.Popen('sudo python3 /home/pi/led-scripts/hub/keyPressTest4.py', shell=True)
        print('DONE RUNNING SUBPROCESS YAYAYAYAYAYAYAYAY')
        detectInput(True)
    return

def getProcesses(selection):
    processes = []
    for x in range(0, numScripts[selection - 1]):
        pid = socket.recv()
        processes.append(pid)
    return processes

def detectInput(boolean):
    isHubRunning = boolean
    while True:
        print('waiting for input')
        # Returns lists containing objects that are ready 
        inp, outp, err = select.select([sys.stdin], [], [])
        # Reads input from the keyboard and stores it in the 'c' variable
        c = sys.stdin.read()

        time.sleep(0.1)

        if isHubRunning:
            hubRunning(c)
        else:
            try:
                if ord(c) == K_ESC:
                    f = open('/home/pi/led-scripts/hub/running.txt', 'r')
                    activeProgram = f.read()
                    f.close()
                    killScripts(activeProgram)
            except:
                print('passed exception')
                pass
        if c == 'q':
            print('Q key')
            revertSettings(settings[0], settings[1], settings[2]) 

def hubRunning(c):
        if c == K_LEFT:
            print('Left arrow')
            sendInput('left')
            return 'left'
        elif c == K_RIGHT:
            print('Right arrow')
            sendInput('right')
            return 'right'
        elif c == K_ENTER:
            print('Enter')
            sendInput('enter')
            programSelected()
        return

def programSelected():
    time.sleep(1.2)
    f = open('/home/pi/led-scripts/hub/running.txt', 'r')
    activeProgram = f.read()
    f.close()

    subprocess.Popen(starts[activeProgram], shell=True)
    print('Started program!')
    killScripts('hub')
    detectInput(False)
    return

subprocess.Popen('sudo python3 /home/pi/led-scripts/hub/keyPressTest4.py', shell=True)
sys.path.append('/home/pi/led-scripts/hub/ledpackage.py')   
settings = keySettings()
print(settings)
time.sleep(2)
while True:
    detectInput(True)

