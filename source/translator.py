import json
import math
import os
import re

from abc import ABC, abstractmethod
from specklepy.objects.base import Base
from specklepy.objects.other import Collection
from specklepy.serialization.base_object_serializer import BaseObjectSerializer

from .logging import LogWrapper

class TranslatorFactory:

	@staticmethod
	def get(translator, client, speckle_object=None, wrapper=None, **parameters):
		translators = {
			'Archicad2Revit': TranslatorArchicad2Revit,
		}
		return translators[translator](client, speckle_object, wrapper, **parameters)

class Translator(ABC):

	def __init__(self, client, speckle_object=None, wrapper=None, **parameters):
		self.log = None
		self.client = client
		self.object = speckle_object
		self.wrapper = wrapper

	def add_collection(self, name, typename, **parameters):
		bos = BaseObjectSerializer()
		collection = bos.traverse_base(Collection())[1]
		collection['name'] = name
		collection['collectionType'] = typename
		collection['elements'] = []
		return bos.recompose_base(collection)

	@staticmethod
	def get_schema(name):
		"""
		Loads translation schema.
		"""
		source = os.path.join(os.path.dirname(os.path.abspath(__file__)).replace('source', 'schemas'), name + '.json')
		with open(source, 'r') as file:
			schema = json.load(file)
		if schema:
			return schema

	@abstractmethod
	def map(self):
		"""
		Process the commit object and run mapping procedure
		"""
		pass

	def override_schema(self, entity, schema, parameters):
		"""
		Replaces existing object structure my the specified parameters of the given schema.
		Used to enable mapping options within the Revit environmnet while receving commits.
		"""
		for key, value in schema.items():
			if not isinstance(value, dict):
				entity[key] = parameters[key] if key in parameters else value
			else:
				if not key in entity:
					dummy = {} if isinstance(value, dict) else None
					entity[key] = dummy
				self.override_schema(entity[key], value, parameters[key])
		return entity

class TranslatorArchicad2Revit(Translator):

	def __init__(self, client, speckle_object=None, wrapper=None, **parameters):
		self.log = LogWrapper.get_logger('app.translator.a2r')
		self.client = client
		self.object = speckle_object
		self.wrapper = wrapper

		self.source = 'archicad'
		self.target = 'revit'
		self.schema = self.get_schema('remap_archicad2revit')
		self.categories = self.get_filtered_categories(parameters)

	def get_filtered_categories(self, parameters):
		"""
		Retrieves category names that were specified manually. Otherwise, keep the full list.
		"""
		categories = parameters.get('categories', [key for key, value in self.schema['archicad'].items()])
		return categories

	def get_element_properties(self, speckle_object):
		"""
		Retrieves properties data for the given object.
		"""
		if 'elementProperties' in speckle_object:
			return speckle_object['elementProperties']
		else:
			self.log.warning(f'No properties found for {speckle_object['elementType']}: $m({speckle_object['id']})')
		return None

	def get_general_parameters(self, speckle_object):
		"""
		Retrieves tool-specific parameters (elevations, areas, volumes etc) for the given object.
		"""
		properties = self.get_element_properties(speckle_object)
		if properties:
			if 'General Parameters' in properties:
				return properties['General Parameters']
			else:
				self.log.warning(f'No parameters found for {speckle_object['elementType']}: $m({speckle_object['id']})')
		return None

	def get_material_body(self, speckle_object):
		"""
		Retrieves the "body" of the given object, regarding it's structure.
		Could be the name of object building material, composite or profile.
		"""
		structure = {
		    'Basic': f'{speckle_object.get('buildingMaterialName')}',
		    'Composite': f'{speckle_object.get('compositeName')}',
		    'Profile': f'{speckle_object.get('profileName')}'
		}
		body = f'{structure[speckle_object['structure']]} ({speckle_object.get('thickness')}{speckle_object.get('units')})'
		return body if body else None

	def log_stats(self):
		"""
		Display some stats info
		"""
		total = self.client.query('get_total_count', 'aeb487f0e6', self.object.id, None)
		self.log.info(f'Commit object entities: $m({total})')
		for category in self.categories:
			count = self.client.query('get_total_count', 'aeb487f0e6', self.object.id, self.schema['archicad'][category]['speckle_type'])
			self.log.info(f'Total {category} objects: $m({count})')

	def map(self):
		self.log_stats()
		# prepare the level structure before (!) the execution of remapping process
		# seems to be more stable to assign objects onto the existing levels
		levels = self.add_collection('Levels', 'Levels Type')
		self.object['@levels'] = levels
		for i in range(-10, 20):
			story = self.client.query('get_level_data', 'aeb487f0e6', self.object.id, i)
			if story:
				self.log.info(f'Level found: $y("{story['name']}"), $m({story['elevation']})')
				level = self.map_story(story)
				self.object['@levels']['elements'].append(level)

		# iterate
		for collection in self.object['elements']:
			category = collection.name.lower()
			if category in self.categories:
				mapper = getattr(self, 'map_' + category)
				for i in range(0, len(collection['elements'])):
					collection['elements'][i] = mapper(
						speckle_object = collection['elements'][i]
					)
			else:
				self.log.warning(f'Translation skipped for category: $y("{collection.name}")')

	def map_beam(self, speckle_object, **parameters):
		
		return speckle_object


	def map_column(self, speckle_object, **parameters):
		
		return speckle_object

	def map_slab(self, speckle_object, **parameters):
		"""
		Remap slab > floor schema.
		"""
		bos = BaseObjectSerializer()
		slab = bos.traverse_base(speckle_object)[1]

		parameters = self.get_general_parameters(slab)
		top_offset = parameters.get('Top Elevation To Home Story', 0) # revit uses top elevation
		body = self.get_material_body(slab)

		overrides = {
			'type': body,
			'TopElevationToHomeStory': top_offset,
			'parameters': {
				'FLOOR_HEIGHTABOVELEVEL_PARAM': {
					'value': top_offset
				}
			}
		}

		floor = self.override_schema(slab, self.schema['revit']['floor'], overrides)
		return bos.recompose_base(floor)

	def map_story(self, story, **parameters):
		"""
		Remap story > level schema
		"""
		bos = BaseObjectSerializer()

		level = bos.read_json(json.dumps (self.schema['revit']['level'], indent = 4))
		level.id = story['id']
		level.name = story.get('name', f"{story['index']} level on {story['elevation'] * 1000}")
		level.index = story['index']
		level.elevation = story['elevation']

		return level

	def map_wall(self, speckle_object, **parameters):
		
		return speckle_object