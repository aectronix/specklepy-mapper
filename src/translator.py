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

	# todo: keep object in translator or write access methods

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
			'General_ElementID': 					self.wrapper.utilities.GetBuiltInPropertyId('General_ElementID'),
			'General_TopLinkStory': 				self.wrapper.utilities.GetBuiltInPropertyId('General_TopLinkStory'),
			'General_BottomElevationToHomeStory': 	self.wrapper.utilities.GetBuiltInPropertyId('General_BottomElevationToHomeStory'),
			'General_TopElevationToHomeStory': 		self.wrapper.utilities.GetBuiltInPropertyId('General_TopElevationToHomeStory'),
			'Zone_ZoneCategoryCode': 				self.wrapper.utilities.GetBuiltInPropertyId('Zone_ZoneCategoryCode'),
			'Geometry_ProfileHeight': 				self.wrapper.utilities.GetBuiltInPropertyId('Geometry_ProfileHeight'),
			'Geometry_ProfileWidth': 				self.wrapper.utilities.GetBuiltInPropertyId('Geometry_ProfileWidth'),
			'Zone_CalculatedArea': 					self.wrapper.utilities.GetBuiltInPropertyId('Zone_CalculatedArea'),
			'WindowDoor_Orientation': 				self.wrapper.utilities.GetBuiltInPropertyId('WindowDoor_Orientation'),
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

	@staticmethod
	def make_segment(start_x, start_y, start_z, end_x, end_y, end_z):
		segment = {}
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
		return segment

	def map_levels(self, obj):
		"""
		Remap level structure.
		"""
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

	def map_beam(self, obj, selection, *args):
		"""
		Remap beam schema.
		"""
		bos = BaseObjectSerializer()
		beam = bos.traverse_base(obj)[1]

		# width = round(beam['segments']['Segment #1']['assemblySegmentData']['nominalWidth']*1000)/1000
		# height = round(beam['segments']['Segment #1']['assemblySegmentData']['nominalHeight']*1000)/1000
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

		if beam['segments']['Segment #1']['assemblySegmentData']['buildingMaterial']:
			material = beam['segments']['Segment #1']['assemblySegmentData']['buildingMaterial']
		else:
			material = beam['segments']['Segment #1']['assemblySegmentData']['profileAttrName']

		surface = ''
		if 'topMaterial' in beam['segments']['Segment #1']:
			surface = ' ' + str(beam['segments']['Segment #1']['topMaterial'])

		w = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId], [self.propIds['Geometry_ProfileWidth']])
		h = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId], [self.propIds['Geometry_ProfileHeight']])

		width = ''
		if w: width = w[0].propertyValues[0].propertyValue.value

		height = ''
		if h: height = h[0].propertyValues[0].propertyValue.value

		overrides = {
			'type': 'Beam ' + str(material) + ' ' + str(width) + ' x ' + str(height) + str(surface),
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

		width = round(column['segments']['Segment #1']['assemblySegmentData']['nominalWidth']*1000)/1000
		height = round(column['segments']['Segment #1']['assemblySegmentData']['nominalHeight']*1000)/1000
		top_level = self.get_top_level(obj, selection, parameters)
		if top_level == None:
			top_level = column['level']
			column['topOffset'] = column['bottomOffset'] + column['height']

		typo = "Col"
		if column['segments']['Segment #1']['assemblySegmentData']['modelElemStructureType'] == 'Complex Profile':
			typo = column['segments']['Segment #1']['assemblySegmentData']['profileAttrName'] + ' ' + str(height) + 'x' + str(width)
		else:
			typo = column['segments']['Segment #1']['assemblySegmentData']['buildingMaterial'] + ' ' + str(height) + 'x' + str(width)

		overrides = {
			'type': typo,
			'topLevel': top_level,
			'rotation': column['slantDirectionAngle'],
			'baseOffset': column['bottomOffset'],
			'topOffset': column['topOffset'],
		}

		column = self.upd_schema(column, self.schema['column'], overrides)

		return bos.recompose_base(column)

	def map_curtainwall(self, obj, selection, *args, **parameters):
		pass

	def map_grid(self, obj, selection, *args, **parameters):
		pass

	def map_wido(self, obj, selection=None, parameters=None):
		"""
		Remap door and window schema.
		"""
		wido = obj

		wido_id = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId], [self.propIds['General_ElementID']])
		wido_orientation = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId], [self.propIds['WindowDoor_Orientation']])
		orientation = wido_orientation[0].propertyValues[0].propertyValue.value
		elemId = wido_id[0].propertyValues[0].propertyValue.value

		overrides = {
			'type': str(obj['libraryPart']) + ' ' + str(obj['width']) + ' x ' + str(obj['height']) + ' ' + str(elemId) + ' (' + str(orientation) + ')',
			'definition': {
				'type': str(obj['libraryPart'])  + ' ' + str(obj['width']) + ' x ' + str(obj['height']) + ' ' + str(elemId) + ' (' + str(orientation) + ')',
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

	def map_morph(self, obj, selection, *args):
		pass

	def map_object(self, obj, selection, *args):
		pass

	def map_opening(self, obj, selection, *args):
		"""
		Remap opening schema.
		"""
		pass

	def map_opening_horizontal(self, obj, **parameters):
		"""
		Remap opening schema for horizontal elements.
		"""
		height = obj['finiteBodyLength'] if obj['finiteBodyLength'] > 0 else parameters['host_height']
		overrides = {
			# 'height': height,
			'parameters': {
				'WALL_BASE_OFFSET': {
					'value': parameters['host_top_elevation'] - parameters['host_height'] + obj['extrusionStartOffSet'],	# todo
				}
			},
			'outline': {
				'segments': []
			}
		}
		shaft = self.upd_schema(obj, self.schema['shaft'], overrides)
		# flat list with x,y,z coordinates of each point
		# the last pair is redundant, as points to the first coordinates
		if 'value' in obj['outline']:
			coords = obj['outline']['value']
			for i in range(0, len(coords) // 3 - 2):
				sidx = i * 3
				eidx = (i + 1) * 3
				shaft['outline']['segments'].append(self.make_segment(
					coords[sidx], coords[sidx + 1], coords[sidx + 2],
					coords[eidx], coords[eidx + 1], coords[eidx + 2]
				))
			shaft['outline']['segments'].append(self.make_segment(
					coords[-6], coords[-5],coords[-4],
					coords[0], coords[1], coords[2]
			))

		return shaft

	def map_opening_vertical(self, obj, **parameters):
		"""
		Remap opening schema for vertical elements.
		"""
		# btm_height = obj['outline']['value'][2]
		# top_height = obj['outline']['value'][8]

		relations = {
			0: {'base': obj['anchorAltitude'] - obj['height'], 'top': obj['anchorAltitude']},
			1: {'base': obj['anchorAltitude'] - obj['height'], 'top': obj['anchorAltitude']},
			2: {'base': obj['anchorAltitude'] - obj['height'], 'top': obj['anchorAltitude']},
			3: {'base': obj['anchorAltitude'] - obj['height']/2, 'top': obj['anchorAltitude'] + obj['height']/2},
			4: {'base': obj['anchorAltitude'] - obj['height']/2, 'top': obj['anchorAltitude'] + obj['height']/2},
			5: {'base': obj['anchorAltitude'] - obj['height']/2, 'top': obj['anchorAltitude'] + obj['height']/2},
			6: {'base': obj['anchorAltitude'], 'top': obj['anchorAltitude'] + obj['height']},
			7: {'base': obj['anchorAltitude'], 'top': obj['anchorAltitude'] + obj['height']},
			8: {'base': obj['anchorAltitude'], 'top': obj['anchorAltitude'] + obj['height']}
		}

		top_offset = abs(parameters['host_top_offset']) if parameters['host_top_offset'] < 0 else 0

		overrides = {
			'parameters': {
				'WALL_BASE_OFFSET': {
					'value': relations[obj['anchorIndex']]['base'],
				},
				'WALL_TOP_OFFSET': {
					# 'value': 0,
					'value': -1 * (parameters['host_base_offset'] + parameters['host_height'] + -1*parameters['host_top_offset'] - relations[obj['anchorIndex']]['top']),
				},
			},
		}
		shaft = self.upd_schema(obj, self.schema['shaft_wall'], overrides)
		return shaft

	def	map_railing(self, obj, selection, *args):
		pass

	def map_roof(self, obj, selection, *args):
		"""
		Remap roof schema
		"""
		bos = BaseObjectSerializer()
		roof = bos.traverse_base(obj)[1]

		structure = str(roof['thickness']) + ' ' + roof['buildingMaterialName'] if roof['buildingMaterialName'] else roof['compositeName']
		btm_elevation_home = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId], [self.propIds['General_BottomElevationToHomeStory']])

		overrides = {
			'type': roof['structure'] + ' ' + structure,
			'parameters': {
				'ROOF_LEVEL_OFFSET_PARAM': {
					'value': btm_elevation_home[0].propertyValues[0].propertyValue.value
				}
			}
		}

		roof = self.upd_schema(roof, self.schema['roof'], overrides)

		# todo: check openings

		return bos.recompose_base(roof)

	def map_slab(self, obj, selection, *args):
		"""
		Remap slab schema.
		"""
		bos = BaseObjectSerializer()
		slab = bos.traverse_base(obj)[1]

		structure = str(slab['thickness']) + ' ' + slab['buildingMaterialName'] if slab['buildingMaterialName'] else slab['compositeName']
		top = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId], [self.propIds['General_TopElevationToHomeStory']])
		top_elevation = top[0].propertyValues[0].propertyValue.value

		overrides = {
			'type': slab['structure'] + ' ' + structure,
			'TopElevationToHomeStory': top_elevation,
			'parameters': {
				'FLOOR_HEIGHTABOVELEVEL_PARAM': {
					'value': top_elevation
				}
			}
		}

		# update child elements (doors, windows, openings etc)
		if 'elements' in slab and slab['elements']:
			for e in range (0, len(slab['elements'])):
				element = slab['elements'][e]
				print (element['applicationId'].lower()+'*')
				if element['elementType'] == 'Opening':
					opening = self.map_opening_horizontal(
						slab['elements'][e],
						host_height = slab['thickness'],
						host_top_elevation = top_elevation
					)
					opening['bottomLevel'] = slab['level']
					slab['elements'][e] = opening

		floor = self.upd_schema(slab, self.schema['floor'], overrides)

		return bos.recompose_base(floor)

	def map_stair(self, obj, selection, *args):
		pass

	def map_wall(self, obj, selection, subselection=None, parameters=None):
		"""
		Remap wall schema.
		"""
		bos = BaseObjectSerializer()
		wall = bos.traverse_base(obj)[1]

		# need to retrieve top link info
		if wall['buildingMaterialName']:
			material = wall['buildingMaterialName']
		elif wall['compositeName']:
			material = wall['compositeName']
		else:
			material = wall['profileName']
		material = str(wall['thickness']) + ' ' + material
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
			'type': str(wall['structure']) + ' ' + str(material),
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

		# update child elements (doors, windows, openings etc)
		if 'elements' in wall and wall['elements']:
			for e in range (0, len(wall['elements'])):
				element = wall['elements'][e]
				print (element['applicationId'].lower()+'*')
				if element['elementType'] == 'Door' or element['elementType'] == 'Window': #and element['applicationId'].lower() in subselection:
					wido = self.map_wido(
						wall['elements'][e],
						subselection[element['applicationId'].lower()],
						{'sx': sx, 'sy': sy, 'sz': sz, 'dx': direction['x'], 'dy': direction['y']}
					)
					wido['level'] = wall['level']
					wall['elements'][e] = wido

				elif element['elementType'] == 'Opening':
					opening = self.map_opening_vertical(
						wall['elements'][e],
						host_height = wall['height'],
						host_base_offset = wall['baseOffset'],
						host_top_offset = wall['topOffset']
					)
					wall['elements'][e] = opening

		wall = self.upd_schema(wall, self.schema['wall'], overrides)
		return bos.recompose_base(wall)

	def map_zone(self, obj, selection, *args, **parameters):
		"""
		Remap zone schema.
		"""
		bos = BaseObjectSerializer()
		zone = bos.traverse_base(obj)[1]

		div = ''
		part = ''
		category = ''
		apt_type = ''
		mod = 0

		calc_area = self.wrapper.commands.GetPropertyValuesOfElements([selection.typeOfElement.elementId], [self.propIds['Zone_CalculatedArea']])
		area = calc_area[0].propertyValues[0].propertyValue.value

		if 'elementProperties' in zone and 'Параметри по будинку' in zone['elementProperties']:
			zone_prop = zone['elementProperties']['Параметри по будинку']
			div = zone_prop['Розміщення відносно р з ']
			part = zone_prop['Віднесення до секції']
			category = zone_prop['Категорія']
			mod = zone_prop['Коефіцієнт']

		zone['type'] = 'Room'
		zone['category'] = 'Rooms'

		zone['boundries'] = []

		zone['parameters'] = {}
		zone['parameters']['speckle_type'] = 'Base'
		zone['parameters']['applicationId'] = None

		zone['parameters']['a8ea7f3f-749f-4ff6-a9a1-a8a6dab6f085'] = {
			'name': 'PTB_Division',
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': 'a8ea7f3f-749f-4ff6-a9a1-a8a6dab6f085',
			'applicationUnit': None,
			'applicationUnitType': None,
			'isReadOnly': False,
			'isShared': True,
			'isTypeParameter': False,
			'units': None,
			'value': div
		}

		zone['parameters']['da5873dd-45b6-4402-875e-3b0443eb71f2'] = {
			'name': 'PTB_BuildingPart',
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': 'da5873dd-45b6-4402-875e-3b0443eb71f2',
			'applicationUnit': None,
			'applicationUnitType': None,
			'isReadOnly': False,
			'isShared': True,
			'isTypeParameter': False,
			'units': None,
			'value': part
		}

		zone['parameters']['ALL_MODEL_INSTANCE_COMMENTS'] = {
			'name': 'Comments',
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': 'ALL_MODEL_INSTANCE_COMMENTS',
			'applicationUnit': None,
			'applicationUnitType': None,
			'isReadOnly': False,
			'isShared': True,
			'isTypeParameter': False,
			'units': None,
			'value': category
		}

		zone['parameters']['1f06fc4b-03e4-4ea2-917e-cf475cc0ea73'] = {
			'name': 'MRT_A_ApartmentID',
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': '1f06fc4b-03e4-4ea2-917e-cf475cc0ea73',
			'applicationUnit': None,
			'applicationUnitType': None,
			'isReadOnly': False,
			'isShared': True,
			'isTypeParameter': False,
			'units': None,
			'value': zone['number']
		}

		zone['parameters']['2aaea987-7ae4-4484-8062-fbd77fc0bfbd'] = {
			'name': 'MRT_A_ApartmentType',
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': '2aaea987-7ae4-4484-8062-fbd77fc0bfbd',
			'applicationUnit': None,
			'applicationUnitType': None,
			'isReadOnly': False,
			'isShared': True,
			'isTypeParameter': False,
			'units': None,
			'value': apt_type
		}

		zone['parameters']['4ff65744-b44a-40a8-a428-d9b649e4173b'] = {
			'name': 'MRT_A_RoomFixedArea',
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': '4ff65744-b44a-40a8-a428-d9b649e4173b',
			'applicationUnit': 'autodesk.unit.unit:squareMeters-1.0.1',
			'applicationUnitType': None,
			'isReadOnly': False,
			'isShared': True,
			'isTypeParameter': False,
			'units': 'm²',
			'value': area
		}

		zone['parameters']['75894bf8-8997-40ee-9130-d3dd46b1e109'] = {
			'name': 'PTB_A_RoomMod',
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': '75894bf8-8997-40ee-9130-d3dd46b1e109',
			'applicationUnit': 'autodesk.unit.unit:general-1.0.1',
			'applicationUnitType': None,
			'isReadOnly': False,
			'isShared': True,
			'isTypeParameter': False,
			'units': None,
			'value': mod
		}

		for segment in zone['outline']['segments']:

			obs = BaseObjectSerializer()
			boundry = obs.traverse_base(Base())[1]

			boundry = {}
			boundry['test'] = True

			boundry['level'] = zone['level']
			boundry['units'] = 'm'
			boundry['baseCurve'] = segment
			boundry['speckle_type'] = 'Objects.BuiltElements.Revit.Curve.RoomBoundaryLine'

			# zone['boundries'].append(obs.recompose_base(boundry))
			zone['boundries'].append(boundry)

		return bos.recompose_base(zone)