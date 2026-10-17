#!/usr/bin/python3
print('Started keyPress script')

from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont
import os
import subprocess
import ledpackage as lp
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
matrixCanvas = matrix.CreateFrameCanvas()

programs = ['stocks', 'news', 'weather', 'discord', 'subs']
selection = 1
img = []

for x in range(0, 6):
    img.append(Image.open('/home/pi/led-scripts/hub/' + str(x + 1) + '.png'))

matrixCanvas.SetImage(canvas, 0)
matrixCanvas = matrix.SwapOnVSync(matrixCanvas)

def remakeFile():
    pathToFile = '/home/pi/led-scripts/hub/input.txt'
    if os.path.exists(pathToFile):
        f = open(pathToFile, 'w')
        f.writelines([''])
    else:
        f = open(pathToFile, 'x')
    f.close()

def logProgram(num):
    f = open('/home/pi/led-scripts/hub/running.txt', 'w')
    f.write(programs[num])
    f.close()

def fetchInput(ts):
    f = open('/home/pi/led-scripts/hub/input.txt', 'r')
    contents = f.readlines()
    f.close()

    if contents != []:
        if contents[0] != ts:
            print('detected input')
            return contents[0], contents[1]
    return ts, False

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
    return

def display(num):
    global matrixCanvas
    canvas.paste(img[num - 1], (0, 0))
    matrixCanvas.SetImage(canvas, 0)
    matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
    return

remakeFile()
lp.recordPID('hub', str(os.getpid()))

display(1)
timestamp = None
print('Type some stuff')
while True:
    timestamp, userInput = fetchInput(timestamp)
    if userInput == 'left':
        selectNum(-1)
    elif userInput == 'right':
        selectNum(1)
    elif userInput == 'enter':
        logProgram(selection - 1)
        display(6)
    time.sleep(0.1)

print('Finished keyPress script')
