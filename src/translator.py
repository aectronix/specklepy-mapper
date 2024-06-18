import json
import os
import re

from abc import ABC, abstractmethod
from specklepy.objects.base import Base
from specklepy.serialization.base_object_serializer import BaseObjectSerializer

class TranslatorFactory:

	@staticmethod
	def get(translator, wrapper):

		translators = {
			'Archicad2Revit': TranslatorArchicad2Revit
		}

		return translators[translator](wrapper)

class Translator(ABC):

	def __init__(self, wrapper=None):

		self.source = None
		self.target = None
		self.wrapper = wrapper
		self.schema = None

	# @abstractmethod
	# def get_target_schema(self):
	# 	pass

	@staticmethod
	def get_schema(filename='schema.json'):
		source = os.path.join(os.path.dirname(os.path.abspath(__file__)).replace('src', ''), 'schema.json')
		with open(source, 'r') as file:
			schema = json.load(file)
		if schema:
			return schema

class TranslatorArchicad2Revit(Translator):

	def __init__(self, wrapper):

		self.source = 'archicad'
		self.target = 'revit'
		self.wrapper = wrapper
		self.schema = self.get_schema()[self.target]

		self.propIds = self.get_prop_ids()

	def get_prop_ids(self):

		propIds = {
			'General_TopLinkStory': self.wrapper.utilities.GetBuiltInPropertyId('General_TopLinkStory'),
		}

		return propIds

	#def get_prop_values(self):	todo

	def get_top_level(self, obj, selection, parameters=None):
		"""
		Retrieves topLevel instance for picked element, if exists.
		"""
		top_link_story = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId], [self.propIds['General_TopLinkStory']])
		
		if top_link_story and not hasattr(top_link_story[0].propertyValues[0], 'error'):
			top_link_ref = re.search(r'Home \+ (\d+).*\((.*?)\)', top_link_story[0].propertyValues[0].propertyValue.value)

			if top_link_ref:
				top_link_range = int(top_link_ref.group(1))
				top_link_index = obj['level']['index'] + top_link_range
				return BaseObjectSerializer().traverse_base(parameters['levels'][top_link_index])[1]

		return None

	def map_column(self, obj, selection, parameters=None):
		"""
		Remap column schema.
		"""
		bos = BaseObjectSerializer()
		column = bos.traverse_base(obj)[1]

		# need to retrieve top link info
		top_level = self.get_top_level(obj, selection, parameters)
		if top_level == None:
			top_level = column['level']
			column['topOffset'] = column['height']

		inputs = {
			'topLevel': top_level,
			'rotation': column['slantDirectionAngle'],
			'baseOffset': column['bottomOffset'],
			'topOffset': column['topOffset'],
		}

		schema = self.schema['column']
		for key, value in schema.items():
			column[key] = inputs[key] if key in inputs else value

		return bos.recompose_base(column)

	def map_slab(self, obj, selection):

		print ('slab')

	def map_levels(self, obj):

		obj['@levels'] = {}

		def new_level(schema, index, name, elevation):

			bos = BaseObjectSerializer()
			level = bos.traverse_base(Base())[1]

			for key, value in schema.items():
				level[key] = value

			if not name:
				name = str(index) + ' level on ' + str(elevation * 1000)

			level['index'] = index
			level['name'] = name
			level['elevation'] = elevation

			return bos.recompose_base(level)

		story_info = self.wrapper.tapir.run('GetStoryInfo', {})
		stories = story_info['stories']
		for story in stories[::-1]:
			level = new_level(self.schema['level'], story['index'], story['uName'], story['level'])
			# obj['@levels'].append(level)
			obj['@levels'][story['index']] = level


			# todo: according to level idx
			# todo: deal with unconnected