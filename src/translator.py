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

	def map_column(self, obj, selection, parameters=None):

		bos = BaseObjectSerializer()
		top = BaseObjectSerializer()
		column = bos.traverse_base(obj)[1]

		# need to retrieve top link info
		top_link = None
		top_link_story = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId], [parameters['properties']['TopLinkStory']])

		if top_link_story and not hasattr(top_link_story[0].propertyValues[0], 'error'):
			top_link_ref = re.search(r'Home \+ (\d+).*\((.*?)\)', top_link_story[0].propertyValues[0].propertyValue.value)

		if top_link_ref:
			top_link_range = int(top_link_ref.group(1))
			top_link_index = column['level']['index'] + top_link_range
			top_link = top.traverse_base(parameters['levels'][top_link_index])[1]

		if top_link == None:
			top_link = column['level']
			column['topOffset'] = column['height']

		inputs = {
			'topLevel': top_link,
			'rotation': column['slantDirectionAngle'],
			'baseOffset': column['bottomOffset'],
			'topOffset': column['topOffset'],
		}

		schema = self.schema['column']
		for key, value in schema.items():
			column[key] = inputs[key] if key in inputs else value

		obj = bos.recompose_base(column)

		return obj

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