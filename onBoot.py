#!/usr/bin/env python3.7

print('Started.')

from rgbmatrix import RGBMatrix, RGBMatrixOptions

print('1')

from PIL import Image, ImageDraw, ImageFont

print('2')

import time

print('3')

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 8
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 6
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

print('4')

matrix = RGBMatrix(options = options)

print('5')

canvas = Image.new('RGB', (256, 32), (0, 0, 0))

print('6')

matrixCanvas = matrix.CreateFrameCanvas()

print('7')

try:
    img = Image.open('./hub.png')
    
except Exception as e:
    print(e)

print('8')

canvas.paste(img, (0, 0))

print('9')

matrixCanvas.SetImage(canvas, 0)

print('10')

matrixCanvas = matrix.SwapOnVSync(matrixCanvas)

print('Done.')

time.sleep(15)

quit()

