#!/usr/bin/env python3.7
import time
import os
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageChops

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 3
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 6
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

matrix = RGBMatrix(options = options)

msgTimes = [0, 0, 0, 0, 0]
msgToCheck = 0
        
#Making a canvas big enough to fit what the matrix panels will show along with space outside of the matrix panels where images will be prepared
canvas = Image.new('RGB', (600, 32), (0, 0, 0))
matrixCanvas = matrix.CreateFrameCanvas()

time.sleep(5)
 
while True:
    if msgToCheck < 5:
        msgToCheck += 1
    else:
        msgToCheck = 1

    while True:
        if os.path.exists('body' + str(msgToCheck) + '.png'):
            if os.path.getmtime('body' + str(msgToCheck) + '.png') == msgTimes[msgToCheck - 1]:
                print(os.path.getmtime('body' + str(msgToCheck) + '.png'))
                print(msgTimes[msgToCheck - 1])
                print('Checking: ' + str(msgToCheck))
                time.sleep(2)
            else:
                print('Picture was updated, using it')
                msgTimes[msgToCheck - 1] = os.path.getmtime('body' + str(msgToCheck) + '.png')
                break
        else:
            print('Doesn\'t exist')
            time.sleep(0.25)
    
    try:
        header = Image.open(('header' + str(msgToCheck) + '.png')).convert('RGB')
    except:
        time.sleep(0.5)
        header = Image.open(('header' + str(msgToCheck) + '.png')).convert('RGB')

    body = Image.open('body' + str(msgToCheck) + '.png').convert('RGB')
    
    canvas.paste(header, (0, 0))
    canvas.paste(body, (32, 11))

    bWidth, bHeight = body.size
    matrixCanvas.SetImage(canvas, 0)
    matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
    cropNum = 0
    print('showing')
    time.sleep(3)
    if bWidth > 224:  
        while True:
            if cropNum == bWidth - 224:
                time.sleep(3)
                break
            canvas.paste(header, (0, 0))
            body = body.crop((1, 0, bWidth, 20))
            canvas.paste(body, (32, 11))

            matrixCanvas.SetImage(canvas, 0)

            matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
            time.sleep(0.02)

            cropNum += 1

# Main function
# e.g. call with
#  sudo ./image-scroller.py --chain=4
# if you have a chain of four
if __name__ == "__main__":
    print("test")
