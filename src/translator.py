import json
import math
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

	def upd_schema(self, obj, schema, parameters):

	    for key, value in schema.items():
	    	if not isinstance(value, dict):
	    		obj[key] = parameters[key] if key in parameters else value
	    	else:
	    		if not key in obj:
	    			dummy = {} if isinstance(value, dict) else None
	    			obj[key] = dummy
	    		self.upd_schema(obj[key], value, parameters[key])

	    return obj

	def get_prop_ids(self):

		propIds = {
			'General_TopLinkStory': 				self.wrapper.utilities.GetBuiltInPropertyId('General_TopLinkStory'),
			'General_BottomElevationToHomeStory': 	self.wrapper.utilities.GetBuiltInPropertyId('General_BottomElevationToHomeStory'),
			'General_TopElevationToHomeStory': 		self.wrapper.utilities.GetBuiltInPropertyId('General_TopElevationToHomeStory'),
			'Geometry_OpeningTotalThickness': 		self.wrapper.utilities.GetBuiltInPropertyId('Geometry_OpeningTotalThickness'),
		}

		return propIds

	def get_direction(self, line):
		# delta
		dx = line['end']['x'] - line['start']['x']
		dy = line['end']['y'] - line['start']['y']
		# magnitude
		vm = math.sqrt(dx**2 + dy**2)
		# vector direction
		vx = dx / vm
		vy = dy / vm

		return {'x': vx, 'y': vy}

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

	def map_beam(self, obj, selection, *args):
		"""
		Remap beam schema.
		"""
		bos = BaseObjectSerializer()
		beam = bos.traverse_base(obj)[1]

		justification = {
			0: {'jy': 0, 'jz': 0},	# left, top
			1: {'jy': 1, 'jz': 0},	# center, top
			2: {'jy': 3, 'jz': 0},	# right, top
			3: {'jy': 0, 'jz': 1},	# left, center
			4: {'jy': 1, 'jz': 1},	# center, center
			5: {'jy': 3, 'jz': 1},	# right, center
			6: {'jy': 0, 'jz': 3},	# left, bottom
			7: {'jy': 1, 'jz': 3},	# center, bottom
			8: {'jy': 3, 'jz': 3},	# right, bottom
		}

		overrides = {
			'type': 'beam',
			'parameters': {
				'Y_JUSTIFICATION': {
					'value': justification[beam['anchorPoint']]['jy']
				},
				'Z_JUSTIFICATION': {
					'value': justification[beam['anchorPoint']]['jz']
				},
				'Y_OFFSET_VALUE': {
					'value': beam['offset']
				}
			}
		}

		beam = self.upd_schema(beam, self.schema['beam'], overrides)

		return bos.recompose_base(beam)

	def map_column(self, obj, selection, subselection=None, parameters=None):
		"""
		Remap column schema.
		"""
		bos = BaseObjectSerializer()
		column = bos.traverse_base(obj)[1]

		# need to retrieve top link info
		top_level = self.get_top_level(obj, selection, parameters)
		if top_level == None:
			top_level = column['level']
			column['topOffset'] = column['bottomOffset'] + column['height']

		overrides = {
			'type': 'column',
			'topLevel': top_level,
			'rotation': column['slantDirectionAngle'],
			'baseOffset': column['bottomOffset'],
			'topOffset': column['topOffset'],
		}

		column = self.upd_schema(column, self.schema['column'], overrides)

		return bos.recompose_base(column)

	def map_wido(self, obj, selection=None, parameters=None):
		"""
		Remap door and window schema.
		"""
		wido = obj

		overrides = {
			'type': obj['elementType'],
			'definition': {
				'type': obj['elementType'],
			},
			'transform': {
				'matrix': [
					# displace by axes
					1, 0, 0, 	parameters['sx'] + wido['objLoc'] * parameters['dx'],
					0, 1, 0, 	parameters['sy'] + wido['objLoc'] * parameters['dy'],
					0, 0, 1,	parameters['sz'] + wido['lower'],
					# homogeneous 
					0, 0, 0,	1
				]
			}
		}

		wido = self.upd_schema(wido, self.schema[obj['elementType'].lower()], overrides)

		return wido

	def map_door(self, obj, selection=None, parameters=None):
		return self.map_wido(obj, selection, parameters)

	def map_window(self, obj, selection=None, parameters=None):
		return self.map_wido(obj, selection, parameters)

	def map_opening(self, obj, selection, *args):
		"""
		Remap roof schema.
		"""

		def newShaft(appId):

			bos = BaseObjectSerializer()
			shaft = bos.traverse_base(Base())[1]

			# shaft['applicationId'] = appId.guid
			shaft['type'] = 'Opening Cut'
			shaft['bottomLevel'] = {}
			shaft['units'] = 'm'
			shaft['category'] = 'Shaft Openings'
			shaft['speckle_type'] = 'Objects.BuiltElements.Opening:Objects.BuiltElements.Revit.RevitOpening:Objects.BuiltElements.Revit.RevitShaft'
			shaft['builtInCategory'] = 'OST_ShaftOpening'
			shaft['outline'] = {
				'units': 'm',
				'closed': True,
				'speckle_type': 'Objects.Geometry.Polycurve',
				'segments': []
			}

			return bos.recompose_base(shaft)

		def newSegment(start_x, start_y, start_z, end_x, end_y, end_z):

			bos = BaseObjectSerializer()
			segment = bos.traverse_base(Base())[1]
			segment['start'] = {
				'x': start_x,
				'y': start_y,
				'z': start_z,
				'units': 'm',
				'speckle_type': 'Objects.Geometry.Point'
			}
			segment['end'] = {
				'x': end_x,
				'y': end_y,
				'z': end_z,
				'units': 'm',
				'speckle_type': 'Objects.Geometry.Point'
			}
			segment['units'] = 'm'
			segment['speckle_type'] = 'Objects.Geometry.Line'

			return bos.recompose_base(segment)

		bos = BaseObjectSerializer()
		opening = bos.traverse_base(obj)[1]

		bbox = self.wrapper.commands.Get2DBoundingBoxes([selection.typeOfElement.elementId])[0].boundingBox2D

		genHeight = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId,], [self.propIds['Geometry_OpeningTotalThickness']])
		height = genHeight[0].propertyValues[0].propertyValue.value
		bottomElv = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId,], [self.propIds['General_BottomElevationToHomeStory']])
		btmElv = bottomElv[0].propertyValues[0].propertyValue.value

		shaft = newShaft(selection.typeOfElement.elementId)
		shaft['bottomLevel'] = opening['level']
		shaft['height'] = height

		shaft['outline']['segments'].append(newSegment(bbox.xMin, bbox.yMin, btmElv,	bbox.xMin, bbox.yMax, btmElv))
		shaft['outline']['segments'].append(newSegment(bbox.xMin, bbox.yMax, btmElv,	bbox.xMax, bbox.yMax, btmElv))
		shaft['outline']['segments'].append(newSegment(bbox.xMax, bbox.yMax, btmElv,	bbox.xMax, bbox.yMin, btmElv))
		shaft['outline']['segments'].append(newSegment(bbox.xMax, bbox.yMin, btmElv,	bbox.xMin, bbox.yMin, btmElv))

		shaft['parameters'] = {}
		shaft['parameters']['speckle_type'] = 'Base'
		shaft['parameters']['applicationId'] = None

		shaft['parameters']['WALL_BASE_OFFSET'] = {
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': 'WALL_BASE_OFFSET',
			'applicationUnit': None,
			'applicationUnitType': 'autodesk.unit.unit:meters-1.0.1',
			'isReadOnly': False,
			'isShared': False,
			'isTypeParameter': False,
			'name': 'Base Offset',
			'units': 'm',
			'value': btmElv
		}

		return shaft

	def map_roof(self, obj, selection, *args):
		"""
		Remap roof schema.
		"""
		bos = BaseObjectSerializer()
		roof = bos.traverse_base(obj)[1]

		btm_elevation_home = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId], [self.propIds['General_BottomElevationToHomeStory']])

		overrides = {
			'type': 'roof',
			'parameters': {
				'ROOF_LEVEL_OFFSET_PARAM': {
					'value': btm_elevation_home[0].propertyValues[0].propertyValue.value
				}
			}
		}

		roof = self.upd_schema(roof, self.schema['roof'], overrides)

		return bos.recompose_base(roof)

	def map_slab(self, obj, selection, *args):
		"""
		Remap slab schema.
		"""
		bos = BaseObjectSerializer()
		floor = bos.traverse_base(obj)[1]

		top_elevation_home = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId], [self.propIds['General_TopElevationToHomeStory']])

		overrides = {
			'type': 'slab',
			'TopElevationToHomeStory': top_elevation_home[0].propertyValues[0].propertyValue.value,
			'parameters': {
				'FLOOR_HEIGHTABOVELEVEL_PARAM': {
					'value': top_elevation_home[0].propertyValues[0].propertyValue.value
				}
			}
		}

		floor = self.upd_schema(floor, self.schema['floor'], overrides)

		return bos.recompose_base(floor)

	def map_wall(self, obj, selection, subselection=None, parameters=None):
		"""
		Remap slab schema.
		"""
		bos = BaseObjectSerializer()
		wall = bos.traverse_base(obj)[1]

		# need to retrieve top link info
		top_level = self.get_top_level(obj, selection, parameters)
		if top_level == None:
			top_level = wall['level']
			wall['topOffset'] = wall['baseOffset'] + wall['height']

		ref_cases = {
			'Center': 0,		# Wall Centerline
			'Core Center': 1,	# Core Centerline
			'Outside': 2,		# Finish Face: Exterior
			'Inside': 3,		# Finish Face: Interior
			'Core Outside': 4,	# Core Face: Exterior
			'Core Inside': 5	# Core Face: Inside
		}

		sx = wall['baseLine']['start']['x']
		sy = wall['baseLine']['start']['y']
		sz = wall['baseLine']['start']['z']
		ex = wall['baseLine']['end']['x']
		ey = wall['baseLine']['end']['y']

		fix = wall['thickness'] / 2
		out = wall['offsetFromOutside'] if wall['offsetFromOutside'] else 0

		flip = -1 if wall['flipped'] == True else 1
		direction = self.get_direction({'start': {'x': sx, 'y': sy }, 'end': {'x': ex, 'y': ey}})

		off_x = (out - fix) * direction['y'] * flip * -1
		off_y = (out - fix) * direction['x'] * flip

		overrides = {
			'type': wall['structure'] + ' Wall',
			'topLevel': top_level,
			'topOffset': wall['topOffset'],
			'parameters': {
				'WALL_KEY_REF_PARAM': {
					'value': ref_cases[wall['referenceLineLocation']]
				}
			},
			'baseLine': {
				'start': {'x': sx + off_x, 'y': sy + off_y},
				'end': {'x': ex + off_x, 'y': ey  + off_y}
			}
		}

		# update child elements (doors, windows, etc)
		if wall['elements'] and (wall['hasDoor'] == True or wall['hasWindow'] == True):
			for e in range (0, len(wall['elements'])):
				element = wall['elements'][e]

				if element['elementType'] == 'Door' or element['elementType'] == 'Window': #and element['applicationId'].lower() in subselection:

					wido = self.map_wido(
						wall['elements'][e],
						subselection[element['applicationId'].lower()],
						{'sx': sx, 'sy': sy, 'sz': sz, 'dx': direction['x'], 'dy': direction['y']})

					wall['elements'][e] = wido

		wall = self.upd_schema(wall, self.schema['wall'], overrides)

		return bos.recompose_base(wall)




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
			obj['@levels'][story['index']] = level