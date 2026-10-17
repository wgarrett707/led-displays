print('Started keyPress script')

from rgbmatrix import RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont
import zmq
import time

context = zmq.Context()
socket = context.socket(zmq.PAIR)
socket.connect('tcp://localhost:5569')

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
starts = ['nice -n 10 sudo python3 /home/pi/led-scripts/stocks/FinnhubGeneratorFix2.py & nice -n -20 sudo python3 /home/pi/led-scripts/stocks/logoviewer12.py',
          '',
          '',
          '',
          '']
img = []

for x in range(0, 6):
    img.append(Image.open('/home/pi/led-scripts/hub/' + str(x + 1) + '.png'))

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
    print('displayed number')

time.sleep(2)
print('Type some stuff')
while True:
    print('waiting to receive message from other script')
    userInput = socket.recv_string()
    if userInput == 'enter':
        socket.send(choices[selection - 1])
        subprocess.run(starts[selection - 1], shell=True)
    elif userInput == 'left':
        selectNum(-1)
    else:
        selectNum(1)

print('Finished keyPress script')
