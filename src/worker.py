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

		commit = self.speckle.retrieve('aeb487f0e6', '486fa0fe2a')
		a2r = TranslatorFactory.get('Archicad2Revit', self.archicad)

		types = {}
		for e in commit['elements']:
			types[e.name.lower()] = e

		# level structure
		a2r.map_levels(commit)

		# elements
		selection = self.archicad.commands.GetSelectedElements()	
		selection_typed = self.archicad.commands.GetTypesOfElements(selection)
		print (len(selection_typed))

		# recompose received selection
		selection_types = {}
		for s in selection_typed:
			element_type = str(s.typeOfElement.elementType).lower()
			element_guid = str(s.typeOfElement.elementId.guid)
			if not element_type in selection_types:
				selection_types[element_type] = {}
			selection_types[element_type][element_guid] = s

		parameters = {
			'column': {
				'levels': commit['@levels']
			}
		}

		for t in selection_types:
			objects = types[t]['elements'] if t in types else []
			mapper = getattr(a2r, 'map_' + t)
			for i in range(0, len(objects)):
				guid = objects[i]['applicationId'].lower()
				if guid in selection_types[t]:
					
					subselection = {}
					if objects[i]['elements']:
						for e in objects[i]['elements']:
							subselection[e['applicationId'].lower()] = selection_types[e['elementType'].lower()][e['applicationId'].lower()]

					objects[i] = mapper(
						objects[i],											# speckle object
						selection_types[t][guid],							# selectec ac element
						subselection,										# selected sub element (wido, opening etc)
						parameters[t] if t in parameters else None)			# additional parameters

		self.speckle.publish(commit, 'windows exp 1a')