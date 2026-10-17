#!/usr/bin/env python
import sys
if sys.hexversion >= 0x3000000:
    print('Python 3.x hexversion %s is in use.' % hex(sys.hexversion))
if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")
