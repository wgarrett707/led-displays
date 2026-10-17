#!/usr/bin/env python
import time
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from samplebase import SampleBase
from PIL import Image

options = RGBMatrixOptions()
options.rows = 32
options.chain_length = 1
options.parallel = 1
options.hardware_mapping = 'regular'
options.brightness = 30
options.multiplexing = 6
options.led_rgb_sequence = "BGR"
options.pwm_lsb_nanoseconds = 350

matrix = RGBMatrix(options = options)

stockSymbols = ["ABT", "ADBE", "DLTR", "HSBC", "MMM"]

index = 0

class ImageScroller(SampleBase):
    print("test1")
    def run(self):
        while True:
	    print("test2")
            global index
            global stockSymbols
            image = Image.open("./logos2/" + stockSymbols[index] + ".png").convert('RGB')

            transparent = Image.open("transparent.png").convert('RGB')

            double_buffer = matrix.CreateFrameCanvas()
            img_width, img_height = image.size
            transparent.resize((img_width, img_height), Image.ANTIALIAS)

            # let's scroll
            xpos = matrix.width
        
            while True:
                if (xpos <= -img_width):
                    break

                
                double_buffer.SetImage(image, xpos)
		

                time.sleep(0.03)

                xpos = xpos - 1

            if index < len(stockSymbols):
                index += 1

            else:
                index = 0
           
# Main function
# e.g. call with
#  sudo ./image-scroller.py --chain=4
# if you have a chain of four
if __name__ == "__main__":
    image_scroller = ImageScroller()
    image_scroller.run()
    print("test")
