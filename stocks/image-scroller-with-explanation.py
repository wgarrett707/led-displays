#!/usr/bin/env python
#The above line specifies what file the Raspberry Pi should run this script with (python)

import time
#The below line imports samplebase.py, which is a file written by hzeller that needs to be in the same folder as this script in order to work properly
from samplebase import SampleBase
from PIL import Image

#This creates a class that uses samplebase.py. When this class is binded to a variable (aka object), the object can then be sent through different functions within the class.
class ImageScroller(SampleBase):

    #This creates a function called "__init__", which initializes the object. By saying "(self, *args, **kwargs)", the function binds the attributes given (in this instance, the
    #attributes are the nonkeyworded/unnamed (*args) and keyworded/named (**kwargs) arguments passed into the function) with the rest of the function. "self" is a necessary part
    #when creating a function, as it allows the actual object (in this case, image_scroller) to be changed and given attributes.
    def __init__(self, *args, **kwargs):
        #This "super" command allows the class to repeat a function from another class. By saying "(ImageScroller, self)", the "super" command knows to grab the other function
        #from the samplebase.py script (since ImageScroller calls SampleBase at the beginning). Then it calls the ".__init__" function from samplebase.py along with the
        #*args and **kwargs.
        super(ImageScroller, self).__init__(*args, **kwargs)
        #This adds another argument to the giant list of arguments in samplebase.py. I'm pretty sure this lets you put additional arguments in the command prompt when opening
        #a project, such as "--led-multiplexing" and "--led-rgb-sequence". The argument added here is "-i", which lets you choose an image to run.
        self.parser.add_argument("-i", "--image", help="The image to display", default="../../../examples-api-use/runtext.ppm")
	print("test2")

    #This creates another function called "run", which opens the image and scrolls it on the screen.
    def run(self):
        #This statement basically states "if the 'self' object (which is the same as 'image_scroller' as seen later on) does not have an 'image' attribute, then run the
        #following code." __dict__ is just a collection of all of the attributes an object has.
        if not 'image' in self.__dict__:
            #When 'self' does not have an 'image' attribute, this next line of code defines one. It pulls the image path that is stated in the command prompt when you run the
            #program and opens it using the "Image" module. Then it converts it into RGB colors so that the LED matrix can display it properly.
            self.image = Image.open(self.args.image).convert('RGB')
        #This line uses a command built into the "Image" module. The command ".resize" should have the size (width, height) and type of resampling in the parentheses following
        #it according to the module's documentation. In this case, the LED matrix width and height are acting as the size, and the mode "ANTIALIAS" (which is good for reducing
        #glitchiness and visual defects when converting images from high resolution to low resolution).
        self.image.resize((self.matrix.width, self.matrix.height), Image.ANTIALIAS)
        #Creates the actual canvas that pixels and images will be put on for the LED matrix. See more at https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/include/led-matrix.h
        #and at about line 260 on the link it will explain more.
        double_buffer = self.matrix.CreateFrameCanvas()
        #Once again, "Image.size" is a command built into the "Image" module. "Image.size" is the width and height of the image in that order, so what this line is doing is setting
        #two variables ("img_width" and "img_height") to the width and height of the actual image that is going to be displayed.
        img_width, img_height = self.image.size

        #These last lines actually make the image change position and updates the matrix panel to give a scrolling effect.
        #This line is pretty simple, all it is doing is setting the x-position of the image to zero
        xpos = 0
        #These next lines that are indented are within a "while True" loop, meaning it will keep repeating forever.
        while True:
            #This line simply adds one to the x-position value. This is the same as "xpos = xpos + 1".
            xpos += 1
            
            #These next two lines just check to see if the image has went off screen, and if it has, it loops back to its original position. The first line, the "if" statement,
            #checks to see if the x-position has went above the width of the image. If it has, the x-position is set to zero so that it starts from the beginning again.
            if (xpos > img_width):
                xpos = 0
                
            #These two lines actually define what will be displayed on the LED matrix panel. The "SetImage" function is defined within "core.pyx" in the rpi-rgb-led-matrix files
            #and it takes the image file as its first parameter and the offset x-value as its second parameter (there are other parameters too, view them at
            #https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/bindings/python/rgbmatrix/core.pyx on line 12). I'm not sure what the first line below this message does,
            #since it is overwritten right away in the second line below this message. The second line below this message defines the image file parameter mentioned earlier as
            #the file that was opened, resized, and converted into RGB previously in the code. The second parameter is the offset x-value, and this line sets that to a quick
            #addition problem: -xpos + img_width. This essentially takes the xpos variable value, makes it negative, and adds it to the width of the image. This means that the
            #offset x-value will get smaller and smaller as this code loops, creating the scrolling effect.
            double_buffer.SetImage(self.image, -xpos)
            double_buffer.SetImage(self.image, -xpos + img_width)

            #This line displays all of the stuff we've typed earlier. This means that we never actually displayed anything on the LED panels until now, we've only said what WILL
            #be on the LED panels. "SwapOnVSync" essentially swaps out the active display (which is just a blank screen the first time this runs) with the supplied display (which
            #is what the "SetImage" function did just a line earlier). So each time the "SetImage" function is run, the supplied display changes and
            #finally the "SwapOnVSync" function displays it on the LED matrix panels.
            double_buffer = self.matrix.SwapOnVSync(double_buffer)
            #This just simply waits 0.01 seconds. This is here just so that the scrolling isn't super duper fast.
            time.sleep(0.5)
	    print("test3")

# Main function
# e.g. call with
#  sudo ./image-scroller.py --chain=4
# if you have a chain of four
if __name__ == "__main__":
    image_scroller = ImageScroller()
    if (not image_scroller.process()):
        image_scroller.print_help()
        print("test")

#Things I'm still confused about:
# 1. How does this script call "self.args" if that was only defined in samplebase.py? Does that mean that all variables from samplebase.py are now in this script?
# 2. According to this line: "self.image.resize((self.matrix.width, self.matrix.height), Image.ANTIALIAS)", the image width and height are set to the width and height of the
#    LED matrix panel. But if that's true, the image would have to be 32x32, meaning it doesn't need to scroll since it already fits in the screen.
#    Answer: I'm thinking that maybe it does change the image's resolution to that of the matrix panels, but it keeps the same aspect ratio. This would cause only part of the
#    image to show, which could then be scrolled by changing the x-position.
# 3. Why is there two separate lines that do SetImage.()? Wouldn't there only need to be one since the panel isn't actually being updated until after those two lines?
