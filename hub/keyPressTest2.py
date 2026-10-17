
print('Started keyPress script')

from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont
import sys, os
import termios, fcntl
import subprocess
import select
import time

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 8
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 6
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

matrix = RGBMatrix(options = options)
canvas = Image.new('RGB', (256, 32), (0, 0, 0))
redCanvas = Image.new('RGB', (256, 32), (200, 0, 0))
matrixCanvas = matrix.CreateFrameCanvas()

selection = 1
img = []
K_UP = '\033[A'
K_DOWN = '\033[B'
K_LEFT = '\033[D'
K_RIGHT = '\033[C'
K_ENTER = '\n'

for x in range(0, 6):
    img.append(Image.open('/home/pi/led-scripts/hub/' + str(x + 1) + '.png'))

# Tell the other scripts what this script's PID is so it can kill it
f = open('/home/pi/led-scripts/hub/pidKill.txt', 'w')
processIdentifier = os.getpid()
print(processIdentifier)
f.writelines([str(processIdentifier)])
f.close()

matrixCanvas.SetImage(canvas, 0)
matrixCanvas = matrix.SwapOnVSync(matrixCanvas)

def selectNum(change):
    global selection
    if selection == 5 and change == 1:
        selection = 1
    elif selection == 1 and change == -1:
        selection = 5
    else:
        selection += change
    print(selection)
    display(selection)

def display(num):
    global matrixCanvas
    canvas.paste(img[num - 1], (0, 0))
    matrixCanvas.SetImage(canvas, 0)
    matrixCanvas = matrix.SwapOnVSync(matrixCanvas)

def keySettings():    
    # Identifies the file descriptor for the input device (usually "0")
    fd = sys.stdin.fileno()
    # Gets the old termios object from "fd"
    oldterm = termios.tcgetattr(fd)
    # Gets attributes of the "fd" object
    newattr = termios.tcgetattr(fd)
    # Sets attribute "lflag" to include the constant "ICANON"
    # This disables canonical mode, which basically makes input available immediately
    newattr[3] = newattr[3] & ~termios.ICANON
    # Sets attribute "lflag" to include the constant "ECHO"
    # This turns off echoing, which controls whether input is immediately re-echoed as output
    newattr[3] = newattr[3] & ~termios.ECHO
    # Changes "fd" to have the attributes established in "newattr"
    # "TCSANOW" means to do this action immediately
    termios.tcsetattr(fd, termios.TCSANOW, newattr)

    # Gets the old termios object from "fd"
    #oldterm = termios.tcgetattr(fd)
    
    # Returns the flags for "fd"
    # "fcntl.fcntl" just runs whatever instructions (like F_GETFL) you give it
    oldflags = fcntl.fcntl(fd, fcntl.F_GETFL)
    # Sets it to non-blocking
    # Pretty sure we do want blocking, but w/o this line it won't work
    fcntl.fcntl(fd, fcntl.F_SETFL, oldflags | os.O_NONBLOCK)

    return fd, oldterm, oldflags

def revertSettings(fd, oldterm, oldflags):
    termios.tcsetattr(fd, termios.TCSANOW, oldterm)
    fcntl.fcntl(fd, fcntl.F_SETFL, oldflags)

settings = keySettings()
print('Type some stuff')
while True:
    # Returns lists containing objects that are ready 
    inp, outp, err = select.select([sys.stdin], [], [])
    # Reads input from the keyboard and stores it in the 'c' variable
    c = sys.stdin.read()
    if c == 'q':
        break
    elif c == K_LEFT:
        print('Left arrow')
        selectNum(-1)
    elif c == K_RIGHT:
        print('Right arrow')
        selectNum(1)
    elif c == K_ENTER:
        print('Enter')
        if selection == 1:
            revertSettings(settings[0], settings[1], settings[2])
            display(6)
            print('Blank screen')
            subprocess.run('sudo python3 /home/pi/led-scripts/stocks/start.py', shell=True)

print('Finished keyPress script')
