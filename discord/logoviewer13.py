#!/usr/bin/env python3.7
import time
import os
import ledpackage as lp
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageChops

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

FULL_PATH = '/home/pi/led-scripts/discord/'
msgTimes = [0, 0, 0, 0, 0]
msgToCheck = 0
        
#Making a canvas big enough to fit what the matrix panels will show along with space outside of the matrix panels where images will be prepared
canvas = Image.new('RGB', (300, 32), (0, 0, 0))
matrixCanvas = matrix.CreateFrameCanvas()

# Opening and displaying a "no new notifications" screen
start = (Image.open(FULL_PATH + 'icons/Start.png')).convert('RGB')
matrixCanvas.SetImage(start)
matrixCanvas = matrix.SwapOnVSync(matrixCanvas)

time.sleep(5)
lp.recordPID('discord', str(os.getpid()))
 
while True:
    if msgToCheck < 5:
        msgToCheck += 1
    else:
        msgToCheck = 1

    while True:
        if os.path.exists(FULL_PATH + 'body' + str(msgToCheck) + '.png'):
            if os.path.getmtime(FULL_PATH + 'body' + str(msgToCheck) + '.png') == msgTimes[msgToCheck - 1]:
                time.sleep(2)
            else:
                msgTimes[msgToCheck - 1] = os.path.getmtime(FULL_PATH + 'body' + str(msgToCheck) + '.png')
                break
        else:
            time.sleep(0.25)
    
    try:
        header = Image.open((FULL_PATH + 'header' + str(msgToCheck) + '.png')).convert('RGB')
    except:
        time.sleep(0.5)
        header = Image.open((FULL_PATH + 'header' + str(msgToCheck) + '.png')).convert('RGB')

    body = Image.open(FULL_PATH + 'body' + str(msgToCheck) + '.png').convert('RGB')
    
    canvas.paste(header, (0, 0))
    canvas.paste(body, (34, 11))

    bWidth, bHeight = body.size
    matrixCanvas.SetImage(canvas, 0)
    matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
    cropNum = 0
    time.sleep(3)
    if bWidth > 224:  
        while True:
            if cropNum == bWidth - 224:
                time.sleep(3)
                break
            body = body.crop((1, 0, bWidth, 20))
            canvas.paste(body, (32, 11))

            matrixCanvas.SetImage(canvas, 0)

            matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
            time.sleep(0.02)

            cropNum += 1
