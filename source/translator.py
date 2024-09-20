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
		collection = Collection()
		collection.name = name
		collection.collectionType = typename
		collection.elements = []
		collection.id = collection.get_id(decompose=True)
		return collection

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

	@staticmethod
	def get_vector_direction(line):
		# delta
		dx = line['end']['x'] - line['start']['x']
		dy = line['end']['y'] - line['start']['y']
		# magnitude
		vm = math.sqrt(dx**2 + dy**2)
		# vector direction
		vx = dx / vm
		vy = dy / vm

		return {'x': vx, 'y': vy}

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
				entity[key] = parameters[key] if parameters and key in parameters else value
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
		self.collections = {}

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
		# self.log_stats()
		# # prepare the level structure before (!) the execution of remapping process
		# # seems to be more stable to assign objects onto the existing levels
		# levels = self.add_collection('Levels', 'Levels Type')
		# self.object['@levels'] = levels
		# for i in range(-10, 20):
		# 	story = self.client.query('get_level_data', 'aeb487f0e6', self.object.id, i)
		# 	if story:
		# 		self.log.info(f'Level found: $y("{story['name']}"), $m({story['elevation']})')
		# 		level = self.map_story(story)
		# 		self.object['@levels']['elements'].append(level)

		boundaries = self.add_collection('Room Separation Lines', 'Revit Category')
		self.object['elements'].append(boundaries)
		# # register custom collections
		self.collections['boundaries'] = len(self.object['elements'])-1


		# iterate
		for collection in self.object['elements']:
			category = collection.name.lower()
			if collection.name == 'Room Separation Lines': # rewrite & add more
				pass
			elif category in self.categories:
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

	def map_door(self, speckle_object, **parameters):

		return speckle_object

	def map_opening(self, speckle_object, **parameters):
		"""
		Remap opening > shaft
		"""
		def map_opening_horizontal(speckle_object, **parameters):
			""" shaft openings in slabs, roofs, meshes? """
			return speckle_object

		def map_opening_vertical(speckle_object, **parameters):
			""" shaft openings in walls """
			return speckle_object

		if parameters['host'] == 'slab' or parameters['host'] == 'roof':
			return map_opening_horizontal(speckle_object)
		elif parameters['host'] == 'wall':
			return map_opening_vertical(speckle_object)

	def map_slab(self, speckle_object, **parameters):
		"""
		Remap slab > floor schema.
		"""
		bos = BaseObjectSerializer()
		slab = bos.traverse_base(speckle_object)[1]

		general = self.get_general_parameters(slab)
		top_offset = general.get('Top Elevation To Home Story', 0) if general else 0  # revit uses top elevation
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

		if floor.get('elements', None):
			for e in range (0, len(floor['elements'])):
				element = floor['elements'][e]
				element_type = element['elementType'].lower()
				if element_type in self.categories:
					self.map_opening(
						speckle_object = floor['elements'][e],
						host = floor['elementType'].lower()
					)

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
		"""
		Remap wall schema.
		"""
		bos = BaseObjectSerializer()
		wall = bos.traverse_base(speckle_object)[1]

		# ref line locations
		baseline = {
			'Center': 0,		# Wall Centerline
			'Core Center': 1,	# Core Centerline
			'Outside': 2,		# Finish Face: Exterior
			'Inside': 3,		# Finish Face: Interior
			'Core Outside': 4,	# Core Face: Exterior
			'Core Inside': 5	# Core Face: Inside
		}

		# ref line coordinates
		sx = wall['baseLine']['start']['x']
		sy = wall['baseLine']['start']['y']
		sz = wall['baseLine']['start']['z']
		ex = wall['baseLine']['end']['x']
		ey = wall['baseLine']['end']['y']

		fix = wall['thickness'] / 2
		out = wall['offsetFromOutside'] if wall['offsetFromOutside'] else 0

		flip = -1 if wall['flipped'] == True else 1
		direction = self.get_vector_direction({'start': {'x': sx, 'y': sy }, 'end': {'x': ex, 'y': ey}})

		off_x = (out - fix) * direction['y'] * flip * -1
		off_y = (out - fix) * direction['x'] * flip

		overrides = {
			'type': str(wall['structure']),
			# 'topLevel': top_level,
			'topOffset': wall['topOffset'],
			'parameters': {
				'WALL_KEY_REF_PARAM': {
					'value': baseline[wall['referenceLineLocation']]
				}
			},
			'baseLine': {
				'start': {'x': sx + off_x, 'y': sy + off_y},
				'end': {'x': ex + off_x, 'y': ey  + off_y}
			}
		}
		wall = self.override_schema(wall, self.schema['revit']['wall'], overrides)

		# curved walls
		if wall['arcAngle']:

			t = fix

			# chord midpoint
			dx = (sx + ex) / 2
			dy = (sy + ey) / 2

			# radius to origin circle
			chord = wall['baseLine']['length']
			radius = chord / (2 * math.sin(wall['arcAngle']/2))

			# angles
			slope = (ey - sy) / (ex - sx)
			slope_angle = math.atan(-1/slope) # bisector chord normale
			start_angle = (math.pi/2-wall['arcAngle']/2) - (math.pi/2-slope_angle)
			end_angle = math.pi - (math.pi/2-wall['arcAngle']/2) - (math.pi/2-slope_angle)

			# chord midpoint
			hypo = math.sqrt(radius**2 - (chord/2)**2)

			# direction vectors
			mvx = -int(math.copysign(1, dx-sx)) * int(math.copysign(1, slope_angle))	# mid
			svx =  int(math.copysign(1, dx-sx)) * int(math.copysign(1, slope_angle))	# start
			evx =  int(math.copysign(1, dx-sx)) * int(math.copysign(1, slope_angle))	# end
			
			# midpoint
			mx = dx + (radius - hypo) * math.cos(slope_angle) * mvx
			my = dy + (radius - hypo) * math.sin(slope_angle) * mvx

			# updated coordinates
			mdx = mx + (t * math.cos(slope_angle) * -mvx)
			mdy = my + (t * math.sin(slope_angle) * -mvx)
			sdx = sx + (t * math.cos(start_angle) * svx)
			sdy = sy + (t * math.sin(start_angle) * svx)
			edx = ex + (t * math.cos(end_angle) * evx)
			edy = ey + (t * math.sin(end_angle) * evx)

			wall['baseLine']['plane'] = {
				'units': 'm',
				'speckle_type': 'Objects.Geometry.Plane',
				'xdir': {
					'x': 1,
					'y': 0,
					'z': 0,
					'units': 'm',
					'speckle_type': 'Objects.Geometry.Vector'
				},
				'ydir': {
					'x': 0,
					'y': 1,
					'z': 0,
					'units': 'm',
					'speckle_type': 'Objects.Geometry.Vector'
				},
				'normal': {
					'x': 0,
					'y': 0,
					'z': 1,
					'units': 'm',
					'speckle_type': 'Objects.Geometry.Vector'
				},
				'origin': {
					'x': 0,
					'y': 0,
					'z': 0,
					'units': 'm',
					'speckle_type': 'Objects.Geometry.Point'
				}
			}
			# wall['baseLine']['radius'] = r
			# wall['baseLine']['length'] = d

			wall['baseLine']['startAngle'] = 0
			wall['baseLine']['endAngle'] = 0

			wall['baseLine']['startPoint'] = wall['baseLine']['start']
			wall['baseLine']['startPoint']['x'] = sdx
			wall['baseLine']['startPoint']['y'] = sdy
			wall['baseLine']['endPoint'] = wall['baseLine']['end']
			wall['baseLine']['endPoint']['x'] = edx
			wall['baseLine']['endPoint']['y'] = edy
			wall['baseLine']['midPoint'] = {
				'x': mdx,
				'y': mdy,
				'z': sz,
				'units': 'm',
				'speckle_type': 'Objects.Geometry.Point'
			}

			wall['baseLine']['angleRadians'] = wall['arcAngle']
			wall['baseLine']['speckle_type'] = 'Objects.Geometry.Arc'

			wall['startPoint'] = None
			wall['endPoint'] = None

		# map sub elements
		if wall.get('elements'):
			for e in range (0, len(wall['elements'])):
				element = wall['elements'][e]
				element_type = element['elementType'].lower()
				if element_type in self.categories:
					sub_mapper = getattr(self, 'map_' + element_type)
					sub = sub_mapper(
						speckle_object = wall['elements'][e],
						host = wall['elementType'].lower()
					)
					sub['level'] = wall['level']
					wall['elements'][e] = sub
				else:
					self.log.warning(f'Translation skipped for category: $y("{element['elementType']}")')

		return bos.recompose_base(wall)

	def map_window(self, speckle_object, **parameters):
		"""
		Remap zone > room schema.
		"""
		window = speckle_object

		# overrides = {
		# 	'definition': {
		# 		'type': 'Window'
		# 	},
		# 	'transform': {
		# 		'matrix': [
		# 			1, 0, 0, 	0,
		# 			0, 1, 0, 	0,
		# 			0, 0, 1,	0,
		# 			0, 0, 0,	1
		# 		]
		# 	}
		# }

		# window = self.override_schema(window, self.schema['revit']['window'], overrides)

		return window

	def map_zone(self, speckle_object, **parameters):
		"""
		Remap zone > room schema.
		"""
		bos = BaseObjectSerializer()
		zone = bos.traverse_base(speckle_object)[1]

		zone['category'] = 'Rooms'
		zone['builtInCategory'] = 'OST_Rooms'
		zone['speckle_type'] = 'Objects.BuiltElements.Room'
		zone['type'] = 'Room'

		for segment in zone['outline']['segments']:
			obs = BaseObjectSerializer()

			boundary = obs.traverse_base(Base())[1]
			boundary = {}
			boundary['level'] = zone['level']
			boundary['units'] = 'm'
			boundary['baseCurve'] = segment
			boundary['speckle_type'] = 'Objects.BuiltElements.Revit.Curve.RoomBoundaryLine'
			boundaryObj = obs.recompose_base(boundary)

			if self.object['elements'][self.collections['boundaries']]:
				self.object['elements'][self.collections['boundaries']]['elements'].append(boundaryObj)

		overrides = {
			'type': 'Room'
		}

		room = self.override_schema(zone, self.schema['revit']['room'], overrides)

		return bos.recompose_base(zone)