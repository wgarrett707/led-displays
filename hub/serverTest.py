import sys, os
import termios, fcntl
import select
import time
import zmq

K_LEFT = '\033[D'
K_RIGHT = '\033[C'
K_ENTER = '\n'

numScripts = [2, 1, 1, 1, 1]

context = zmq.Context()
socket = context.socket(zmq.PAIR)
socket.bind('tcp://*:5569')

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

def getProcesses(selection):
    processes = []
    for x in range(0, numScripts[selection - 1]):
        pid = socket.recv()
        processes.append(pid)
    return processes

def hubRunning():
    #hubProcess = socket.recv()

    while True:
        print('waiting for input')
        # Returns lists containing objects that are ready 
        inp, outp, err = select.select([sys.stdin], [], [])
        # Reads input from the keyboard and stores it in the 'c' variable
        c = sys.stdin.read()
        print(c)

        if c == K_LEFT:
            print('Left arrow')
            socket.send_string('left')
        elif c == K_RIGHT:
            print('Right arrow')
            socket.send_string('right')
        elif c == K_ENTER:
            print('Enter')
            socket.send_string('enter')
            programSelected()

def programSelected():
    selection = socket.recv()
    processes = getProcesses(selection)
    print(processes)
    
settings = keySettings()
print(settings)
hubRunning()

