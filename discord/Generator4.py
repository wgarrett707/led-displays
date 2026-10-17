#!/usr/bin/env python3.7
import json
KEYS = json.load(open('/home/pi/led-scripts/apikeys.json'))
from PIL import Image, ImageDraw, ImageFont
import ledpackage as lp
import numpy as np
import discord
import os

lp.localPID('discord', str(os.getpid()))

FULL_PATH = '/home/pi/led-scripts/discord/'
headerFont = ImageFont.truetype(FULL_PATH + 'm5x7.ttf', size=16)
bodyFont = ImageFont.truetype(FULL_PATH + 'body.otf', size=20)
fileNum = 0

HIGHSCHOOL_HANGOUT = Image.open(FULL_PATH + 'icons/HighschoolHangout.png')
GALACTIC_EMPIRE = Image.open(FULL_PATH + 'icons/GalacticEmpire.png')
EXISTENCE = Image.open(FULL_PATH + 'icons/Existence.png')
DEFAULT = Image.open(FULL_PATH + 'icons/Default.png')


serverDict = {400057019161247745: HIGHSCHOOL_HANGOUT,
              763956986127319060: GALACTIC_EMPIRE,
              697500717333610526: EXISTENCE}
              
def delFiles():
    for x in range(0, 5):
        headerFile = FULL_PATH + 'header' + str(x + 1) + '.png'
        bodyFile = FULL_PATH + 'body' + str(x + 1) + '.png'
        if os.path.exists(headerFile):
            os.remove(headerFile)
        if os.path.exists(bodyFile):
            os.remove(bodyFile)

class MyClient(discord.Client):
    async def on_ready(self):
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')

    async def on_message(self, message):
        if not message.author.bot:
            global fileNum
            if fileNum < 5:
                fileNum += 1
            else:
                fileNum = 1
            headerText = "#" + str(message.channel) + " " + str(message.author)
            bodyText = message.content
            if bodyText == '':
                bodyText = '(attachment)'
            elif len(bodyText) > 75:
                bodyText = bodyText[:75] + '...'
            guildID = message.guild.id
            try:
                serverIcon = serverDict[guildID]
            except:
                serverIcon = DEFAULT
            img = Image.new('RGBA', (256, 37), color = (0, 0, 0, 0))
            img.paste(serverIcon, (0, 5))
            d = ImageDraw.Draw(img)
            d.fontmode = '1'
            d.text((33, 2), headerText, font=headerFont)
            img = img.crop((0, 5, 256, 37))
            img.save((FULL_PATH + 'header' + str(fileNum) + '.png'))

            img = Image.new('RGBA', (3000, 24), color = (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.text((0, 0), bodyText, font=bodyFont)

            # Converts image to an array
            image_data = np.asarray(img)
            # Finds the maximum in the given axis (idk why it's 2)
            image_data_bw = image_data.max(axis=2)
            # Finds the columns where the max value of the column is above 0, meaning it has content that isn't just transparency
            non_empty_columns = np.where(image_data_bw.max(axis=0)>0)[0]
            # Defines the region to crop the image
            cropBox = (4, 24, min(non_empty_columns), max(non_empty_columns))
            # Crops the image inside the array
            image_data_new = image_data[cropBox[0]:cropBox[1]+1, cropBox[2]:cropBox[3]+1 , :]
            # Creates the image from the array we made
            img = Image.fromarray(image_data_new)
        
            img.save((FULL_PATH + 'body' + str(fileNum) + '.png'))

delFiles()
client = MyClient()
client.run(KEYS['discord'])
