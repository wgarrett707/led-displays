#!/usr/bin/env python3.7
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont
import ledpackage as lp
import time
import os

# lp.recordPID('banana', str(os.getpid()))

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 3
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 1
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

matrix = RGBMatrix(options = options)

canvas = Image.new('RGB', (256, 32), (0, 0, 0))
matrixCanvas = matrix.CreateFrameCanvas()
pbj = []

for i in range(0, 8):
    pbj.append(Image.open("./sprites/pbj_" + str(i) + ".png").convert('RGB'))

while True:
    for img in pbj:
        canvas.paste(img, (0, 0))

        matrixCanvas.SetImage(canvas, 0)

        matrixCanvas = matrix.SwapOnVSync(matrixCanvas)
        time.sleep(0.1)
