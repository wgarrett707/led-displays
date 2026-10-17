import subprocess

subprocess.run("nice -n 10 sudo python3 Generator4.py & nice -n -20 sudo python3 logoviewer13.py", shell=True)
