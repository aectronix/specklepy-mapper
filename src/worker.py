import argparse
from .archicad import ArchicadWrapper
from .client import SpeckleWrapper
from .translator import TranslatorFactory

class Worker():

	def __init__(self):

		self.archicad = None
		self.revit = None
		self.speckle = None

		self.wrap('speckle')

	def wrap(self, service):

		try:
			wrapper = globals()[service.capitalize() + 'Wrapper']()
			if wrapper:
				setattr(self, service, wrapper)
		except Exception as e:
			raise e

	def translate(self):

		commit = self.speckle.retrieve('aeb487f0e6', '0e2c899179')

		a2r = TranslatorFactory.get('Archicad2Revit', self.archicad)
		a2r.map_levels(commit)

		self.speckle.publish(commit, 'levels 2')