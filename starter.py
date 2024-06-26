import argparse
import time

from src.worker import Worker

ts = time.time()

cmd = argparse.ArgumentParser()
cmd.add_argument('-p', '--port', required=False, help='archicad port')
arg = cmd.parse_args()

worker = Worker()
worker.wrap('archicad')
worker.translate()

print(f'\n{round(time.time() - ts, 2)} sec')
