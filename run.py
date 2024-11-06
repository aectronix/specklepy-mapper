import argparse
from datetime import datetime
import logging
import time

from source import *

class App():

	def __init__(self, services: list):
		self.log = LogWrapper.get_logger('app')
		try:
			for service in services:
				self.wrap(service)
		except Exception as e:
			raise e

	def wrap(self, service, *args, **kwargs):
		try:
			wrapper = globals()[service.capitalize() + 'Wrapper']
			wrapper_obj = wrapper(*args, **kwargs)
			if wrapper_obj:
				setattr(self, service, wrapper_obj)
		except Exception as e:
			raise e

	def translate(self, translator):

		streamId = 'aeb487f0e6' # project id
		commitId = 'f957f2f99f' # model / commid id

		speckle_object = self.speckle.retrieve(streamId, commitId)
		a2r = TranslatorFactory.get(translator, client=self.speckle, streamId = streamId, speckle_object=speckle_object)

		a2r.map()

		self.speckle.publish(speckle_object, streamId, 'zone', 'test4')

if __name__ == "__main__":

	ts = time.time()

	cmd = argparse.ArgumentParser()
	cmd.add_argument('-p', '--port', required=False, help='archicad port')
	cmd.add_argument('-t', '--translator', required=False, help='translator scheme')
	arg = cmd.parse_args()

	print (f'{datetime.now().strftime('%H:%M:%S')}:{int(datetime.now().microsecond/1000):03d} initializing...')
	app = App(['speckle'])
	app.translate('Archicad2Revit')

	print (f'{datetime.now().strftime('%H:%M:%S')}:{int(datetime.now().microsecond/1000):03d} completed in {round(time.time() - ts, 2)} sec')
