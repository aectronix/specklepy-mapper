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

		commit = self.speckle.retrieve('aeb487f0e6', 'c4150005f3')
		a2r = TranslatorFactory.get('Archicad2Revit', self.archicad)

		propId_TopLinkStory = self.archicad.utilities.GetBuiltInPropertyId('General_TopLinkStory')

		# level structure
		a2r.map_levels(commit)

		# elements
		selection = self.archicad.commands.GetSelectedElements()
		print (len(selection))
		selection_types = self.archicad.commands.GetTypesOfElements(selection)
		selection_types = sorted(selection_types, key=lambda x: x.typeOfElement.elementType)

		# go through selection, deal with each type of elements
		for selected in selection_types:
			elements = commit['elements'][0]['elements']
			element_guid = str(selected.typeOfElement.elementId.guid)
			element_type = str(selected.typeOfElement.elementType).lower()

			for i in range(0, len(elements)):
				if element_guid.lower() == elements[i]['applicationId'].lower():

					parameters = {
						'properties': {
							'TopLinkStory': propId_TopLinkStory
						},
						'levels': commit['@levels']
					}

					mapper = getattr(a2r, 'map_' + element_type)
					obj_remapped = mapper(elements[i], selected, parameters)

					elements[i] = obj_remapped


		self.speckle.publish(commit, 'columns exp 1c')