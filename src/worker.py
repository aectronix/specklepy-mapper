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

		commit = self.speckle.retrieve('aeb487f0e6', '2c83bdc4b2')
		a2r = TranslatorFactory.get('Archicad2Revit', self.archicad)

		types = {
			'door': {
				'elements': []
			}
		}
		for e in commit['elements']:
			types[e.name.lower()] = e

		# level structure
		a2r.map_levels(commit)

		# elements
		selection = self.archicad.commands.GetSelectedElements()
		print (len(selection))
		selection_types = self.archicad.commands.GetTypesOfElements(selection)
		selection_types = sorted(selection_types, key=lambda x: x.typeOfElement.elementType)

		parameters = {
			'column': {
				'levels': commit['@levels']
			}
		}

		# go through selection, deal with each type of elements
		for selected in selection_types:
			element_guid = str(selected.typeOfElement.elementId.guid)
			element_type = str(selected.typeOfElement.elementType).lower()
			elements = types[element_type]['elements']

			for i in range(0, len(elements)):
				if elements[i]['applicationId'] and element_guid.lower() == elements[i]['applicationId'].lower():

					mapper = getattr(a2r, 'map_' + element_type)
					obj_remapped = mapper(elements[i], selected, parameters[element_type] if element_type in parameters else None)

					elements[i] = obj_remapped


		self.speckle.publish(commit, 'doors exp 1')