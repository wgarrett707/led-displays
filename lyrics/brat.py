# brat theme: songs from Charli xcx's brat albums get the cover's look instead of the effect
# cycle - lowercase Arial Narrow, slightly blurred, in black on brat green.
import os
import numpy as np
import effects
import layout

GREEN = (138, 206, 0)   # #8ACE00, the cover's green
# Arial Narrow is a Microsoft font, so it isn't in the (public) repo: copy ARIALN.TTF from
# C:\Windows\Fonts on a PC. Without it the theme keeps the colours and uses the pixel font.
FONT_PATH = '/home/pi/led-scripts/lyrics/fonts/ARIALN.TTF'
FACE = (layout.Face(FONT_PATH, 16, smooth=True, blur=0.45, lowercase=True)
        if os.path.exists(FONT_PATH) else layout.PIXEL)


def matches(track):
    # brat, its deluxe edition, and "brat and it's completely different but also still brat"
    return (track.album.lower().startswith('brat')
            and any(artist.lower() == 'charli xcx' for artist in track.artists))


class Brat(effects.Effect):
    # Black text on brat green, cut straight in with no animation, like the cover
    name = 'brat'

    def __init__(self):
        self.background = np.empty((effects.H, effects.W, 3), np.float32)
        self.background[:] = GREEN

    def render(self, f):
        # The anti-aliased mask (not the 1-bit one other effects use) keeps the soft edges
        ink = getattr(f.text, '_bratInk', None)
        if ink is None:
            ink = (np.asarray(f.text.maskImage, np.float32) / 255 * f.text.shade)[:, :, None]
            f.text._bratInk = ink
        return self.background * (1 - ink)
