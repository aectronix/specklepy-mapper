import json
import math
import os
import re

from abc import ABC, abstractmethod
from specklepy.objects.base import Base
from specklepy.objects.other import Collection
from specklepy.serialization.base_object_serializer import BaseObjectSerializer

class TranslatorFactory:

	@staticmethod
	def get(translator, client, speckle_object=None, wrapper=None):

		translators = {
			'Archicad2Revit': TranslatorArchicad2Revit
		}

		return translators[translator](client, speckle_object, wrapper)

class Translator(ABC):

	def __init__(self, client, speckle_object=None, wrapper=None):

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
		source = os.path.join(os.path.dirname(os.path.abspath(__file__)).replace('source', 'schemas'), name + '.json')
		with open(source, 'r') as file:
			schema = json.load(file)
		if schema:
			return schema

	@staticmethod
	def map_by_schema(entity, schema, parameters):
		for key, value in schema.items():
			if not isinstance(value, dict):
				entity[key] = parameters[key] if key in parameters else value
			else:
				if not key in entity:
					dummy = {} if isinstance(value, dict) else None
					entity[key] = dummy
				self.map_by_schema(entity[key], value, parameters[key])
		return entity

class TranslatorArchicad2Revit(Translator):

	def __init__(self, client, speckle_object=None, wrapper=None):

		self.client = client
		self.object = speckle_object
		self.wrapper = wrapper

		self.source = 'archicad'
		self.target = 'revit'
		self.schema = self.get_schema('remap_archicad2revit')

	def get_level(self, **parameters):
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

	def map_level(self, story, **parameters):

		bos = BaseObjectSerializer()

		level = bos.read_json(json.dumps (self.schema['revit']['level'], indent = 4))
		level.id = story['id']
		level.name = story.get('name', f"{story['index']} level on {story['elevation'] * 1000}")
		level.index = story['index']
		level.elevation = story['elevation']

		return level