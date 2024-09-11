import argparse
from datetime import datetime
import logging
import time

from source import *

LOG = logging.getLogger('app')
LOG.setLevel(logging.INFO)

class App():

	def __init__(self, services: list):

		for service in services:
			self.wrap(service)

	def wrap(self, service, *args, **kwargs):

		try:
			wrapper = globals()[service.capitalize() + 'Wrapper']
			wrapper_obj = wrapper(*args, **kwargs)
			if wrapper_obj:
				setattr(self, service, wrapper_obj)
		except Exception as e:
			raise e

	def translate(self, translator):

		speckle_object = self.speckle.retrieve('aeb487f0e6', 'e9971b52f2')
		a2r = TranslatorFactory.get(translator, client=self.speckle, speckle_object=speckle_object)

		# prepare the level structure before (!) the execution of remapping process
		# seems to be more stable to assign objects onto the existing levels
		levels = a2r.add_collection('Levels', 'Levels Type')
		speckle_object['@levels'] = levels
		for i in range(-10, 20):
			story = a2r.get_level(projectId='aeb487f0e6', objectId='24a2a23229c145db99f5782ce70f1661', idx=i)
			if story:
				LOG.info(f'found level {story['index']} {story['name']}')
				level = a2r.map_level(story)
				speckle_object['@levels']['elements'].append(level)


		# self.speckle.publish(speckle_object, 'test', 'levels 2b')

if __name__ == "__main__":

	ts = time.time()

	cmd = argparse.ArgumentParser()
	cmd.add_argument('-p', '--port', required=False, help='archicad port')
	cmd.add_argument('-t', '--translator', required=False, help='translator scheme')
	arg = cmd.parse_args()

	print (f'{datetime.now().strftime('%H:%M:%S')}:{int(datetime.now().microsecond/1000):03d} initializing...')
	app = App(['log', 'speckle'])
	app.translate('Archicad2Revit')


	print(f'\n{round(time.time() - ts, 2)} sec')
