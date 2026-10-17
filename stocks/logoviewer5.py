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

stockSymbols = ["AAL", "AAPL", "ABT", "ADBE", "AMD", "AMZN", "AXP", "BA",
                "BBBY", "BBY", "BIG", "BP", "BRK-A", "CAT", "CBS", "COF",
                "COST", "CSCO", "CVS", "CVX", "DELL", "DG", "DIS", "DLTR",
                "DNKN", "DOW", "EBAY", "F", "FB", "FDX", "FITB", "GE", "GIS",
                "GM", "GOOG", "GS", "HAS", "HD", "HPQ", "HSBC", "HSY", "IBM",
                "KO", "MCD", "MMM", "NSRGY", "SVNDY", "XON"]

index = 0

class ImageScroller(SampleBase):
    print("test1")
    def run(self):
        while True:
	    print("test2")
            global index
            global stockSymbols
            image = Image.open("./logos/" + stockSymbols[index] + ".png").convert('RGB')

            transparent = Image.open("transparent.png").convert('RGB')

            double_buffer = matrix.CreateFrameCanvas()
            img_width, img_height = image.size
            transparent.resize((img_width + 1, img_height), Image.ANTIALIAS)

            # let's scroll
            xpos = 0
        
            while True:
                if (xpos > img_width * 2):
                    break

                double_buffer.SetImage(transparent, -xpos + img_width + 1)
                double_buffer.SetImage(image, -xpos + img_width)

                double_buffer = matrix.SwapOnVSync(double_buffer)
                time.sleep(0.01)
	        print("test3")

                xpos += 1

            index += 1


# Main function
# e.g. call with
#  sudo ./image-scroller.py --chain=4
# if you have a chain of four
if __name__ == "__main__":
    image_scroller = ImageScroller()
    image_scroller.run()
    print("test")