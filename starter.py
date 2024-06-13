import argparse
from src.worker import Worker

cmd = argparse.ArgumentParser()
cmd.add_argument('-p', '--port', required=False, help='archicad port')
arg = cmd.parse_args()

worker = Worker()
worker.wrap('archicad')
worker.translate()

