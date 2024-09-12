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
	def get(translator, client, speckle_object=None, wrapper=None):
		translators = {
			'Archicad2Revit': TranslatorArchicad2Revit,
		}
		return translators[translator](client, speckle_object, wrapper)

class Translator(ABC):

	def __init__(self, client, speckle_object=None, wrapper=None):
		self.log = None
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

	def get_stats(self):
		"""
		Retrieves object count by types.
		"""
		result = ', '.join([f'{e.name}: $m({len(e.elements)})' for e in self.object['elements']])
		return result

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

	def __init__(self, client, speckle_object=None, wrapper=None):
		self.log = LogWrapper.get_logger('app.translator.a2r')
		self.client = client
		self.object = speckle_object
		self.wrapper = wrapper

		self.source = 'archicad'
		self.target = 'revit'
		self.schema = self.get_schema('remap_archicad2revit')[self.target]

	def map(self):
		self.log.info(self.get_stats())

		# prepare the level structure before (!) the execution of remapping process
		# seems to be more stable to assign objects onto the existing levels
		levels = self.add_collection('Levels', 'Levels Type')
		self.object['@levels'] = levels
		for i in range(-10, 20):
			story = self.get_story_data(projectId='aeb487f0e6', objectId='0bb2effa506bd508d3ae0f5dce632044', idx=i)
			if story:
				self.log.info(f'Level found: $y("{story['name']}"), $m({story['elevation']})')
				level = self.map_story(story)
				self.object['@levels']['elements'].append(level)

		# iterate
		for collection in self.object['elements']:
			category = collection.name.lower()
			mapper = getattr(self, 'map_' + category)
			for i in range(0, len(collection['elements'])):
				collection['elements'][i] = mapper(
					speckle_object = collection['elements'][i]
				)

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

	def get_story_data(self, **parameters):
		"""
		Hope this is temporary solution and we'll be able to fetch levels from info section.
		"""
		query = """
			query Object($objectId: String!, $projectId: String!, $query: [JSONObject!], $select: [String], $orderBy: JSONObject, $depth: Int!, $limit: Int!) {
			  project(id: $projectId) {
			    object(id: $objectId) {
			      children(query: $query, select: $select, orderBy: $orderBy, depth: $depth, limit: $limit) {
			        totalCount
			        objects {
			          data
			        }
			      }
			    }
			  }
			}
		"""
		variables = {
			"projectId": parameters['projectId'],
			"objectId": parameters['objectId'],
			"query": [
				{
				  "field": "level.index",
				  "value": parameters['idx'],
				  "operator": "="
				}
			],
			"select": [
				"level.id",
				"level.name",
				"level.index",
				"level.elevation"
			],
			"orderBy": {
				"field": "level.index"
			},
			"depth": 3,
			"limit": 1
		}

		response = self.client.query(query, variables)
		result = response['data']['project']['object']['children']['objects']

		return result[0]['data']['level'] if result else None


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

		floor = self.override_schema(slab, self.schema['floor'], overrides)
		return bos.recompose_base(floor)

	def map_story(self, story, **parameters):
		"""
		Remap story > level schema
		"""
		bos = BaseObjectSerializer()

		level = bos.read_json(json.dumps (self.schema['level'], indent = 4))
		level.id = story['id']
		level.name = story.get('name', f"{story['index']} level on {story['elevation'] * 1000}")
		level.index = story['index']
		level.elevation = story['elevation']

		return level

	def map_wall(self, speckle_object, **parameters):
		
		return speckle_object