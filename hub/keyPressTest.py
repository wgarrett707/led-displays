#!/usr/bin/env python3.7

from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont
import keyboard

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

selection = 1
img = []

for x in range(0, 5):
    img.append(Image.open('/home/pi/led-scripts/hub/' + str(x + 1) + '.png'))

def on_press(key):
    if key == 'left':
        select(-1)
    elif key == 'right':
        select(1)
    
def select(change):
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
    canvas.paste(img[num - 1], (0, 0))
    matrixCanvas.SetImage(canvas, 0)
    matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
    
keyboard.on_press(on_press)

display(1)
